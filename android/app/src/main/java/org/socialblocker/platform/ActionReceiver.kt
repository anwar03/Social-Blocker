package org.socialblocker.platform

import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.widget.Toast
import org.socialblocker.core.LockedError

/**
 * Handles the notification's "+15 min" and "Stop" buttons.
 *
 * Note what is NOT here: any check of whether the session is locked. That lives
 * in `Control` and only there — this receiver calls the use case and reports
 * whatever it says. Adding a second lock check here is how a codebase ends up
 * with two subtly different definitions of "locked".
 */
class ActionReceiver : BroadcastReceiver() {

    override fun onReceive(ctx: Context, intent: Intent) {
        val control = App.control(ctx)
        try {
            when (intent.action) {
                ACTION_EXTEND -> {
                    control.extendSession(15)
                    toast(ctx, "Extended by 15 minutes")
                }
                ACTION_STOP -> {
                    control.stopSession()
                    toast(ctx, "Focus session stopped")
                }
                else -> return
            }
        } catch (e: LockedError) {
            toast(ctx, e.message ?: "Locked")
        } catch (e: Exception) {
            Log.w("socialblocker", "notification action failed", e)
            toast(ctx, e.message ?: "Could not do that")
        }
        // Collapse the shade so the result of the tap is visible.
        ctx.getSystemService(NotificationManager::class.java)
    }

    private fun toast(ctx: Context, msg: String) =
        Toast.makeText(ctx, msg, Toast.LENGTH_LONG).show()

    companion object {
        const val ACTION_EXTEND = "org.socialblocker.EXTEND"
        const val ACTION_STOP = "org.socialblocker.STOP_SESSION"
    }
}
