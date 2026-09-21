package org.socialblocker.platform

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.SystemClock
import android.util.Log
import org.socialblocker.vpn.BlockerVpnService

/**
 * Autostart — arm the configured block once per device boot, and bring the
 * enforcement service back up after a reboot or an app update.
 *
 * This is an OUTER adapter. It produces the boot token and hands it *inward* to
 * `Control.armBootSession`; the policy ("arm at most once per boot, never
 * shorten a running session") stays in the core where it can be tested.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(ctx: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action != Intent.ACTION_BOOT_COMPLETED &&
            action != Intent.ACTION_MY_PACKAGE_REPLACED
        ) return

        val control = App.control(ctx)

        // Consent is remembered across reboots, so if the user ever granted it
        // the service can come back on its own. If they have not, there is
        // nothing to restore and the UI will ask next time it is opened.
        if (VpnService.prepare(ctx) == null) {
            BlockerVpnService.start(ctx)
        }

        val armed = control.armBootSession(Platform.bootToken())
        if (armed != null) {
            Log.i(TAG, "autostart armed ${armed.mode} locked=${armed.locked} n=${armed.count}")
        }
    }

    companion object { private const val TAG = "socialblocker" }
}

object Platform {

    /**
     * A token that is stable for the life of this boot and differs after a
     * reboot — the idempotency key for autostart, and the direct analogue of
     * the desktop's `/proc/sys/kernel/random/boot_id`.
     *
     * Android exposes no boot id, so it is derived: wall-clock now minus time
     * since boot is the moment the device booted, rounded to the minute to
     * absorb small clock adjustments.
     *
     * THE SECOND GUARD IS THE IMPORTANT ONE. A large NTP correction hours after
     * boot would shift that derived value and look like a new boot, which would
     * arm a block the user never asked for — the unsafe direction. So a token
     * is only issued within 30 minutes of boot. Outside that window this
     * returns "", and `Control.armBootSession` already treats an unknown boot
     * identity as "do not arm" rather than "arm again".
     */
    fun bootToken(): String {
        val upMs = SystemClock.elapsedRealtime()
        if (upMs > 30 * 60 * 1000L) return ""
        val bootedAtMin = (System.currentTimeMillis() - upMs) / 60_000L
        return "boot-$bootedAtMin"
    }
}
