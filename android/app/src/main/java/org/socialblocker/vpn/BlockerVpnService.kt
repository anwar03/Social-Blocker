package org.socialblocker.vpn

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Log
import org.socialblocker.core.Control
import org.socialblocker.core.RuleSet
import org.socialblocker.platform.App
import org.socialblocker.platform.Notifications
import org.socialblocker.platform.Platform
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.util.concurrent.Executors
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit

/**
 * Background enforcement — the phone's `daemon.py`.
 *
 * Two threads, matching the two jobs the desktop daemon does:
 *
 *  1. THE SINKHOLE reads DNS queries out of the tun device and answers the
 *     blocked ones itself. This is what /etc/hosts does on Linux, except it is
 *     asked the question directly, so it can match subdomains a hosts file
 *     could never enumerate.
 *
 *  2. THE POLICY LOOP re-evaluates every few seconds, so session expiry and
 *     schedule windows take effect on time without anyone opening the app.
 *
 * WHERE TAMPER REPAIR WENT. On Linux the daemon repairs an edited /etc/hosts,
 * because a userland tool can lose the file but not the root it runs as. Here
 * the rules live in this process's memory and cannot be edited at all — but the
 * *tunnel* can be revoked from system Settings, and that is the equivalent
 * hole. `onRevoke` handles it: one automatic re-establish attempt, then a
 * high-priority notification, because a locked session that has silently
 * stopped enforcing is the worst possible failure for this tool. The real fix
 * is system-enforced: Always-on VPN with "Block connections without VPN",
 * which the UI walks the user to.
 */
class BlockerVpnService : VpnService() {

    private lateinit var control: Control
    private lateinit var upstream: UpstreamDns

    @Volatile private var rules: RuleSet = RuleSet.EMPTY
    @Volatile private var running = false
    @Volatile private var blockedQueries = 0L
    private var revokeRetried = false

    private var tun: ParcelFileDescriptor? = null
    private var sinkhole: Thread? = null
    private var policy: Thread? = null

    /** Forwarding is blocking I/O with a timeout, so it needs its own threads.
     *  Bounded: a runaway app doing thousands of lookups must not be able to
     *  spawn thousands of sockets on the user's battery. */
    private val forwarders: ThreadPoolExecutor =
        Executors.newFixedThreadPool(FORWARDERS) as ThreadPoolExecutor

    /** Writes to the tun fd come from every forwarder thread; one lock. */
    private val writeLock = Any()
    private var tunOut: FileOutputStream? = null

    override fun onCreate() {
        super.onCreate()
        control = App.control(this)
        upstream = UpstreamDns(this)
        instance = this
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopEverything()
            stopSelf()
            return START_NOT_STICKY
        }
        if (!running) startEnforcing()
        // START_STICKY: if Android kills us for memory, it brings the blocker
        // back. Autostart cannot be re-armed by that revival because
        // Control.armBootSession is keyed on the boot, not on this process.
        return START_STICKY
    }

    private fun startEnforcing() {
        // startForeground() FIRST, before anything that can fail. We were
        // launched with startForegroundService(), which gives us a few seconds
        // to show a notification or the system kills the process with a
        // ForegroundServiceDidNotStartInTimeException — and bailing out early
        // on a failed establish() is exactly the path that would hit it.
        startForegroundNotification()

        val fd = establish() ?: run {
            Log.w(TAG, "could not establish the tunnel; consent may be missing")
            stopSelf()
            return
        }
        tun = fd
        tunOut = FileOutputStream(fd.fileDescriptor)
        running = true
        revokeRetried = false
        upstream.start()

        // Safe to call on every start: Control keys it on the boot token, and
        // Platform only issues one within 30 minutes of boot.
        control.armBootSession(Platform.bootToken())?.let {
            Log.i(TAG, "autostart armed ${it.mode} locked=${it.locked} n=${it.count}")
        }

        rules = control.refresh()
        Log.i(TAG, "enforcing ${describe(rules)}")

        sinkhole = Thread({ sinkholeLoop(fd) }, "sb-sinkhole").apply { start() }
        policy = Thread({ policyLoop() }, "sb-policy").apply { start() }
    }

    /**
     * Bring up a DNS-only tunnel.
     *
     * The route is the whole design. Rather than claiming 0.0.0.0/0 and having
     * to forward every packet the phone sends through userspace, we advertise a
     * private resolver address and route only that /32. DNS enters the tunnel;
     * everything else takes the normal path, untouched, at full speed. The cost
     * of being wrong here is the user's entire network throughput, so it is
     * worth stating plainly: this app never sees your traffic, only your
     * lookups.
     */
    private fun establish(): ParcelFileDescriptor? = try {
        Builder()
            .setSession("SocialBlocker")
            .addAddress(TUN_ADDRESS, 32)
            .addDnsServer(TUN_DNS)
            .addRoute(TUN_DNS, 32)
            .setBlocking(true)
            .setMtu(MTU)
            .setConfigureIntent(
                android.app.PendingIntent.getActivity(
                    this, 0,
                    Intent(this, org.socialblocker.ui.MainActivity::class.java),
                    android.app.PendingIntent.FLAG_IMMUTABLE,
                )
            )
            .establish()
    } catch (e: Exception) {
        Log.e(TAG, "establish failed", e)
        null
    }

    // --- 1. the sinkhole ----------------------------------------------------

    private fun sinkholeLoop(fd: ParcelFileDescriptor) {
        val input = FileInputStream(fd.fileDescriptor)
        val buf = ByteArray(MTU)
        while (running) {
            val n = try {
                input.read(buf)
            } catch (e: Exception) {
                if (running) Log.w(TAG, "tun read ended", e)
                break
            }
            if (n <= 0) continue

            val q = DnsPacket.parseQuery(buf, n) ?: continue
            val snapshot = rules

            if (snapshot.isBlocked(q.name)) {
                blockedQueries++
                // DEBUG, not INFO: this is the answer to "why is this site
                // blocked right now?", and it must be available without
                // becoming a log of everywhere the user goes.
                Log.d(TAG, "blocked ${q.name} (${snapshot.mode})")
                val answer = DnsPacket.blockedResponse(q, buf)
                writeReply(q, answer, answer.size)
            } else {
                val payload = buf.copyOfRange(q.dnsOffset, q.dnsOffset + q.dnsLength)
                try {
                    forwarders.execute { forward(q, payload) }
                } catch (e: Exception) {
                    // Queue full: drop. The client will retry, which is exactly
                    // what a resolver under load is supposed to make it do.
                    Log.d(TAG, "forwarder busy, dropped ${q.name}")
                }
            }
        }
    }

    /** Send an allowed query on to the real resolver and pipe the answer back. */
    private fun forward(q: DnsPacket.Query, payload: ByteArray) {
        try {
            DatagramSocket().use { sock ->
                // Without protect() this packet would be routed back into our
                // own tunnel and loop until the timeout.
                if (!protect(sock)) {
                    Log.w(TAG, "could not protect forwarding socket")
                    return
                }
                sock.soTimeout = UPSTREAM_TIMEOUT_MS
                val server = upstream.primary()
                sock.send(DatagramPacket(payload, payload.size, server, DnsPacket.DNS_PORT))

                val back = ByteArray(MAX_DNS_REPLY)
                val reply = DatagramPacket(back, back.size)
                sock.receive(reply)
                writeReply(q, back, reply.length)
            }
        } catch (e: java.net.SocketTimeoutException) {
            Log.d(TAG, "upstream timeout for ${q.name}")
        } catch (e: Exception) {
            Log.d(TAG, "forward failed for ${q.name}: ${e.message}")
        }
    }

    /** Wrap a DNS payload as a reply to [q] and write it into the tun device. */
    private fun writeReply(q: DnsPacket.Query, payload: ByteArray, length: Int) {
        val packet = DnsPacket.buildUdpPacket(
            srcIp = q.dstIp, dstIp = q.srcIp,       // swapped: this is the reply
            srcPort = q.dstPort, dstPort = q.srcPort,
            payload = payload, payloadLen = length, ipId = q.ipId,
        )
        synchronized(writeLock) {
            try {
                tunOut?.write(packet)
            } catch (e: Exception) {
                Log.d(TAG, "tun write failed: ${e.message}")
            }
        }
    }

    // --- 2. the policy loop -------------------------------------------------

    private fun policyLoop() {
        var lastDigest = rules.digest
        var lastNotified = 0L
        while (running) {
            try {
                // Log a focus session the moment it completes, so stats stay
                // current even if the app is never opened.
                if (control.reap()) Log.i(TAG, "focus session completed — logged")

                val fresh = control.refresh()
                val nowMs = System.currentTimeMillis()
                if (fresh.digest != lastDigest) {
                    Log.i(TAG, "enforcing ${describe(fresh)}")
                    lastDigest = fresh.digest
                    updateNotification()
                    lastNotified = nowMs
                } else if (nowMs - lastNotified >= NOTIFY_INTERVAL_MS) {
                    // The countdown has to move, but redrawing it every tick is
                    // notification jank for no information gained.
                    updateNotification()
                    lastNotified = nowMs
                }
            } catch (e: Exception) {
                Log.w(TAG, "policy tick failed", e)
            }
            try {
                Thread.sleep(TICK_MS)
            } catch (e: InterruptedException) {
                return
            }
        }
    }

    private fun describe(r: RuleSet) = "${r.mode} locked=${r.locked} n=${r.count}"

    // --- notification -------------------------------------------------------

    private fun startForegroundNotification() {
        val n = Notifications.enforcing(this, control.status(), blockedQueries)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                Notifications.ID_ENFORCE, n,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE,
            )
        } else {
            startForeground(Notifications.ID_ENFORCE, n)
        }
    }

    private fun updateNotification() {
        getSystemService(NotificationManager::class.java).notify(
            Notifications.ID_ENFORCE,
            Notifications.enforcing(this, control.status(), blockedQueries),
        )
    }

    // --- teardown -----------------------------------------------------------

    /**
     * The user (or another VPN) took the tunnel away.
     *
     * One silent retry, because the common cause is another VPN app winning a
     * handover and then going away again. After that we stop trying and say so
     * loudly: pretending to enforce a locked session we are not enforcing would
     * be the single most dishonest thing this app could do.
     */
    override fun onRevoke() {
        val wasLocked = rules.locked
        Log.w(TAG, "tunnel revoked (locked=$wasLocked)")
        stopEverything()

        if (wasLocked && !revokeRetried) {
            revokeRetried = true
            Thread {
                Thread.sleep(REVOKE_RETRY_MS)
                if (VpnService.prepare(this) == null) {
                    Log.i(TAG, "restoring the tunnel after revoke")
                    startEnforcing()
                } else {
                    alertInterrupted(true)
                }
            }.start()
        } else {
            alertInterrupted(wasLocked)
        }
        super.onRevoke()
    }

    private fun alertInterrupted(locked: Boolean) {
        getSystemService(NotificationManager::class.java)
            .notify(Notifications.ID_ALERT, Notifications.interrupted(this, locked))
    }

    private fun stopEverything() {
        running = false
        sinkhole?.interrupt()
        policy?.interrupt()
        sinkhole = null
        policy = null
        forwarders.shutdownNow()
        runCatching { forwarders.awaitTermination(1, TimeUnit.SECONDS) }
        upstream.stop()
        synchronized(writeLock) {
            runCatching { tunOut?.close() }
            tunOut = null
        }
        runCatching { tun?.close() }
        tun = null
    }

    override fun onDestroy() {
        stopEverything()
        instance = null
        super.onDestroy()
    }

    companion object {
        private const val TAG = "socialblocker"

        /** A link-local-ish private pair nothing else is likely to claim. */
        private const val TUN_ADDRESS = "10.111.222.1"
        private const val TUN_DNS = "10.111.222.2"

        private const val MTU = 1500
        private const val MAX_DNS_REPLY = 1500
        private const val FORWARDERS = 8
        private const val UPSTREAM_TIMEOUT_MS = 5_000
        private const val TICK_MS = 5_000L
        private const val NOTIFY_INTERVAL_MS = 30_000L
        private const val REVOKE_RETRY_MS = 3_000L

        const val ACTION_STOP = "org.socialblocker.VPN_STOP"

        @Volatile
        private var instance: BlockerVpnService? = null

        fun isRunning(): Boolean = instance?.running == true

        /** Hand the service a new rule set. Cheap by design: no teardown, no
         *  reconnect, not one dropped connection. */
        fun push(rules: RuleSet) {
            instance?.rules = rules
        }

        fun start(ctx: Context) {
            ctx.startForegroundService(Intent(ctx, BlockerVpnService::class.java))
        }

        fun stop(ctx: Context) {
            ctx.startService(
                Intent(ctx, BlockerVpnService::class.java).setAction(ACTION_STOP)
            )
        }
    }
}
