package org.socialblocker.platform

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import org.socialblocker.R
import org.socialblocker.core.Status
import org.socialblocker.ui.MainActivity

/**
 * The persistent notification is this app's answer to the daemon's log.
 *
 * On the desktop you can run `socialblocker status` or read the journal to
 * answer "why is this site blocked right now?". A phone has no terminal, so the
 * ongoing notification carries the same three facts at all times: which mode is
 * being enforced, how many domains that is, and how long is left.
 */
object Notifications {

    const val CHANNEL_ENFORCE = "enforcement"
    const val CHANNEL_ALERT = "alerts"
    const val ID_ENFORCE = 1
    const val ID_ALERT = 2

    fun createChannels(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ENFORCE, "Enforcement",
                // LOW: it must be permanent, it must not buzz every 30 seconds.
                NotificationManager.IMPORTANCE_LOW,
            ).apply { description = "Shows what SocialBlocker is blocking right now." }
        )
        nm.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ALERT, "Protection alerts",
                // HIGH: reserved for "your locked session is no longer enforced",
                // which is the one thing the user must not miss.
                NotificationManager.IMPORTANCE_HIGH,
            ).apply { description = "Warns when enforcement stops unexpectedly." }
        )
    }

    /** The ongoing foreground notification for the enforcement service. */
    fun enforcing(ctx: Context, status: Status, blockedQueries: Long): android.app.Notification {
        val title = when {
            status.sessionActive && status.locked ->
                "Locked focus — ${fmt(status.sessionRemaining)} left"
            status.sessionActive -> "Focus — ${fmt(status.sessionRemaining)} left"
            status.effectiveMode == "off" -> "Watching (nothing blocked)"
            else -> "${status.effectiveMode.replaceFirstChar { it.uppercase() }} mode"
        }
        val text = "${status.blockedNow} domains blocked · $blockedQueries requests stopped today"

        val b = android.app.Notification.Builder(ctx, CHANNEL_ENFORCE)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_shield)
            .setOngoing(true)
            .setShowWhen(false)
            .setContentIntent(open(ctx))

        if (status.sessionActive) {
            // Extending is allowed even while locked, so it is always offered.
            b.addAction(action(ctx, "+15 min", ActionReceiver.ACTION_EXTEND))
            if (!status.locked) b.addAction(action(ctx, "Stop", ActionReceiver.ACTION_STOP))
        }
        return b.build()
    }

    /** Enforcement was interrupted while it still mattered. */
    fun interrupted(ctx: Context, locked: Boolean): android.app.Notification =
        android.app.Notification.Builder(ctx, CHANNEL_ALERT)
            .setContentTitle(
                if (locked) "Locked session is no longer enforced"
                else "SocialBlocker stopped"
            )
            .setContentText(
                if (locked) "The VPN was switched off. Tap to restore the block."
                else "Tap to turn protection back on."
            )
            .setSmallIcon(R.drawable.ic_shield)
            .setAutoCancel(true)
            .setContentIntent(open(ctx))
            .build()

    private fun open(ctx: Context): PendingIntent = PendingIntent.getActivity(
        ctx, 0, Intent(ctx, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
        PendingIntent.FLAG_IMMUTABLE,
    )

    private fun action(ctx: Context, label: String, what: String): android.app.Notification.Action {
        val pi = PendingIntent.getBroadcast(
            ctx, what.hashCode(),
            Intent(ctx, ActionReceiver::class.java).setAction(what),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return android.app.Notification.Action.Builder(null, label, pi).build()
    }

    fun fmt(seconds: Int): String {
        val m = seconds / 60
        return if (m >= 60) "${m / 60}h ${m % 60}m" else "${m}m"
    }
}
