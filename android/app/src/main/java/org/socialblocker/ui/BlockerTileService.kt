package org.socialblocker.ui

import android.content.Intent
import android.net.VpnService
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.widget.Toast
import org.socialblocker.core.BLACKLIST
import org.socialblocker.core.LockedError
import org.socialblocker.core.OFF
import org.socialblocker.platform.App
import org.socialblocker.vpn.BlockerVpnService

/**
 * A Quick Settings tile — the second, deliberately thin front-end.
 *
 * This is the phone's version of the CLI: a different delivery mechanism over
 * the same use cases, and its job here is the same as the CLI's on the desktop.
 * If a rule cannot be expressed in these twenty lines without reaching past
 * `Control`, the rule is in the wrong place. Note in particular that the tile
 * does not decide whether a locked session may be interrupted; it calls
 * `setDefaultMode` and reports the refusal it gets back.
 */
class BlockerTileService : TileService() {

    override fun onStartListening() {
        super.onStartListening()
        render()
    }

    override fun onClick() {
        super.onClick()
        val control = App.control(this)
        try {
            val status = control.status()
            val next = if (status.defaultMode == OFF) BLACKLIST else OFF
            control.setDefaultMode(next)
            if (next != OFF && VpnService.prepare(this) == null) {
                BlockerVpnService.start(this)
            } else if (next != OFF) {
                // Consent is an Activity-only conversation; hand it over.
                openApp()
            }
        } catch (e: LockedError) {
            Toast.makeText(this, e.message, Toast.LENGTH_LONG).show()
        }
        render()
    }

    /** API 34 replaced the Intent overload with a PendingIntent one and made
     *  the old signature throw, so both are kept rather than one being
     *  suppressed. */
    private fun openApp() {
        val intent = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (android.os.Build.VERSION.SDK_INT >= 34) {
            startActivityAndCollapse(
                android.app.PendingIntent.getActivity(
                    this, 0, intent, android.app.PendingIntent.FLAG_IMMUTABLE)
            )
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(intent)
        }
    }

    private fun render() {
        val tile = qsTile ?: return
        val status = App.control(this).status()
        tile.state = if (status.effectiveMode == OFF) Tile.STATE_INACTIVE else Tile.STATE_ACTIVE
        tile.label = when {
            status.sessionActive && status.locked -> "Locked focus"
            status.sessionActive -> "Focus"
            status.effectiveMode == OFF -> "SocialBlocker off"
            else -> status.effectiveMode.replaceFirstChar { it.uppercase() }
        }
        tile.updateTile()
    }
}
