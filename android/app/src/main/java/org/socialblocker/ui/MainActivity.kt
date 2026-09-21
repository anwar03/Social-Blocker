package org.socialblocker.ui

import android.app.Activity
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import org.socialblocker.core.BLACKLIST
import org.socialblocker.core.Control
import org.socialblocker.core.LockedError
import org.socialblocker.core.OFF
import org.socialblocker.core.Status
import org.socialblocker.core.WHITELIST
import org.socialblocker.platform.App
import org.socialblocker.platform.Notifications
import org.socialblocker.vpn.BlockerVpnService

/**
 * The main front-end. Deliberately thin: it parses input and calls `Control`.
 *
 * There is no business logic in this file and there must not be one — the
 * locked-session rule, the mode precedence and the focus stats all live in the
 * core, which is why the Quick Settings tile can offer the same operations in
 * twenty lines without duplicating any of it.
 */
class MainActivity : Activity() {

    private lateinit var control: Control
    private lateinit var p: Palette

    /** Re-render callbacks for anything that shows live state. */
    private val renders = mutableListOf<() -> Unit>()

    /**
     * One status read per frame, shared by every render callback.
     *
     * `Control.status()` loads and parses state.json. Letting each of the dozen
     * callbacks call it once a second turned a countdown into a dozen file
     * reads a second, on battery, forever. Read once, render many.
     */
    private lateinit var snap: Status
    private val ticker = Handler(Looper.getMainLooper())
    private var pendingAfterConsent: (() -> Unit)? = null

    // Focus composer state — UI-local until Start is pressed.
    private var composerMinutes = 25
    private var composerMode = WHITELIST
    private var composerLocked = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        control = App.control(this)
        p = Mist.of(this)
        snap = control.status()

        val page = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(p.fogTop)
            val pad = dp(16)
            setPadding(pad, dp(24), pad, dp(32))
        }
        page.addView(hero())
        page.addView(protectionCard())
        page.addView(allDayCard())
        page.addView(focusCard())
        page.addView(autostartCard())
        page.addView(navCard())
        page.addView(honestyCard())

        setContentView(ScrollView(this).apply {
            setBackgroundColor(p.fogTop)
            addView(page, ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        })

        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), REQ_NOTIF)
        }
    }

    // --- hero ---------------------------------------------------------------

    private fun hero(): LinearLayout {
        val card = card(p)
        card.background = cardBackground(this, p, p.raised)

        val modeLine = TextView(this).apply {
            setTextColor(p.text); textSize = 26f
        }
        val subLine = body(p, "", 14f, p.muted)
        val statsLine = body(p, "", 13f, p.faint)

        card.addView(heading(p, "Enforcing now"))
        card.addView(modeLine)
        card.addView(subLine)
        card.addView(android.view.View(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(10))
        })
        card.addView(statsLine)

        renders += {
            val s = snap
            modeLine.text = when {
                s.sessionActive && s.locked -> "Locked · ${Notifications.fmt(s.sessionRemaining)} left"
                s.sessionActive -> "Focus · ${Notifications.fmt(s.sessionRemaining)} left"
                s.effectiveMode == OFF -> "Off"
                else -> s.effectiveMode.replaceFirstChar { it.uppercase() }
            }
            modeLine.setTextColor(if (s.locked) p.amber else p.text)
            subLine.text = if (s.effectiveMode == OFF) {
                "Nothing is blocked."
            } else {
                "${s.blockedNow} domains blocked in ${s.effectiveMode} mode" +
                    if (s.effectiveMode == WHITELIST)
                        " (${s.whitelistCount} allowed of ${s.universeSize})" else ""
            }
            statsLine.text = "Focused today ${s.focusedTodayMin} min · streak ${s.streakDays} d" +
                if (s.sessionSource == "boot") " · armed at boot" else ""
        }
        return card
    }

    // --- protection master switch -------------------------------------------

    private fun protectionCard(): LinearLayout {
        val card = card(p)
        card.addView(heading(p, "Protection"))

        val row = switchRow(
            p, "Enforcement service",
            "The phone's daemon. Without it nothing is blocked.",
            { BlockerVpnService.isRunning() },
        ) { on ->
            if (on) ensureVpn { toast("Protection on") }
            else stopProtection()
        }
        card.addView(row)
        renders += {
            val sw = row.switchView()
            val running = BlockerVpnService.isRunning()
            if (sw != null && sw.isChecked != running) {
                // Reflect reality without re-firing the listener: the service
                // can stop for reasons the UI never initiated.
                sw.setOnCheckedChangeListener(null)
                sw.isChecked = running
                sw.setOnCheckedChangeListener { _, v ->
                    if (v) ensureVpn { toast("Protection on") } else stopProtection()
                }
            }
        }

        card.addView(body(p, "", 12f, p.faint).apply {
            text = "Android lets any VPN be switched off from Settings, so a locked " +
                "session is only as strong as you let it be. Turn on Always-on VPN " +
                "with “Block connections without VPN” and the system enforces " +
                "it for you."
            setPadding(0, dp(8), 0, dp(4))
        })
        card.addView(ghostButton(p, "Open VPN settings") {
            startActivity(Intent(Settings.ACTION_VPN_SETTINGS))
        }.apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(44)
            ).apply { topMargin = dp(6) }
        })
        return card
    }

    // --- all-day mode -------------------------------------------------------

    private fun allDayCard(): LinearLayout {
        val card = card(p)
        card.addView(heading(p, "All-day mode"))
        val (row, render) = pillGroup(
            p,
            listOf(OFF to "Off", BLACKLIST to "Blacklist", WHITELIST to "Whitelist"),
            { snap.defaultMode },
        ) { mode ->
            guarded {
                control.setDefaultMode(mode)
                if (mode != OFF) ensureVpn { }
            }
        }
        card.addView(row)
        card.addView(body(p, "", 12f, p.faint).apply {
            text = "What is enforced when no focus session or schedule is running."
            setPadding(0, dp(10), 0, 0)
        })
        renders += render
        return card
    }

    // --- focus composer -----------------------------------------------------

    private fun focusCard(): LinearLayout {
        val card = card(p)
        card.addView(heading(p, "Focus session"))

        // Presets are a starting point, not a shortcut past the composer: they
        // pre-fill it, and the duration stays adjustable. Same contract as the
        // desktop's preset list.
        val presetRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        control.listPresets().forEach { preset ->
            presetRow.addView(ghostButton(p, preset.name) {
                composerMinutes = preset.defaultMinutes
                composerMode = preset.mode
                composerLocked = preset.locked
                renderAll()
                toast(preset.blurb.ifEmpty { "${preset.name} loaded" })
            })
        }
        card.addView(presetRow)

        card.addView(stepper(p, { composerMinutes }, "min", 5, 5, 480) { composerMinutes = it })

        val (modeRow, modeRender) = pillGroup(
            p, listOf(BLACKLIST to "Blacklist", WHITELIST to "Whitelist"),
            { composerMode },
        ) { composerMode = it; renderAll() }
        card.addView(modeRow)
        renders += modeRender

        val lockRow = switchRow(
            p, "Locked",
            "Cannot be stopped early. Extending stays allowed.",
            { composerLocked },
        ) { composerLocked = it }
        card.addView(lockRow)
        renders += { lockRow.switchView()?.isChecked = composerLocked }

        val start = primaryButton(p, "Start focus") {
            guarded {
                control.startSession(composerMinutes, composerMode, composerLocked)
                ensureVpn { }
                toast("Focus started")
            }
        }
        card.addView(start)

        val liveRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = dp(8) }
            addView(ghostButton(p, "+15 min") {
                guarded { control.extendSession(15); toast("Extended by 15 minutes") }
            })
            addView(ghostButton(p, "Stop", p.danger) {
                guarded { control.stopSession(); toast("Session stopped") }
            })
        }
        card.addView(liveRow)

        renders += {
            val active = snap.sessionActive
            start.visibility = if (active) ViewGroup.GONE else ViewGroup.VISIBLE
            presetRow.visibility = if (active) ViewGroup.GONE else ViewGroup.VISIBLE
            liveRow.visibility = if (active) ViewGroup.VISIBLE else ViewGroup.GONE
        }
        return card
    }

    // --- autostart ----------------------------------------------------------

    private fun autostartCard(): LinearLayout {
        val card = card(p)
        card.addView(heading(p, "Arm at boot"))

        var minutes = control.status().autostartMinutes
        val enabledRow = switchRow(
            p, "Block automatically after every restart",
            "Takes effect from the next boot, never this one.",
            { snap.autostartEnabled },
        ) { on ->
            guarded {
                control.setAutostart(
                    enabled = on, minutes = minutes,
                    bootToken = org.socialblocker.platform.Platform.bootToken(),
                )
            }
        }
        card.addView(enabledRow)
        card.addView(stepper(p, { minutes }, "min", 15, 15, 720) {
            minutes = it
            guarded { control.setAutostart(minutes = it) }
        })

        val (modeRow, modeRender) = pillGroup(
            p, listOf(BLACKLIST to "Blacklist", WHITELIST to "Whitelist"),
            { snap.autostartMode },
        ) { guarded { control.setAutostart(mode = it) } }
        card.addView(modeRow)
        renders += modeRender

        val lockRow = switchRow(
            p, "Locked", "Opt-in. A locked boot block cannot be stopped from here.",
            { snap.autostartLocked },
        ) { guarded { control.setAutostart(locked = it) } }
        card.addView(lockRow)

        renders += {
            val s = snap
            enabledRow.switchView()?.let { if (it.isChecked != s.autostartEnabled) it.isChecked = s.autostartEnabled }
            lockRow.switchView()?.let { if (it.isChecked != s.autostartLocked) it.isChecked = s.autostartLocked }
        }
        return card
    }

    // --- navigation ---------------------------------------------------------

    private fun navCard(): LinearLayout {
        val card = card(p)
        card.addView(heading(p, "Lists and schedules"))
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(ghostButton(p, "Edit lists") {
                startActivity(Intent(this@MainActivity, ListsActivity::class.java))
            })
            addView(ghostButton(p, "Schedules") {
                startActivity(Intent(this@MainActivity, ScheduleActivity::class.java))
            })
        }
        card.addView(row)
        val counts = body(p, "", 12f, p.faint).apply { setPadding(0, dp(10), 0, 0) }
        card.addView(counts)
        renders += {
            val s = snap
            counts.text = "${s.blocklistCount} blocked · ${s.whitelistCount} allowed · " +
                "${s.schedules} schedule rules"
        }
        return card
    }

    private fun honestyCard(): LinearLayout {
        val card = card(p)
        card.background = cardBackground(this, p, p.sunk)
        card.addView(heading(p, "What this cannot do"))
        card.addView(body(p, "", 12.5f, p.muted).apply {
            text = "Blocking works by answering DNS lookups, so a browser or app using " +
                "DNS-over-HTTPS, a Private DNS setting, or a hard-coded IP address goes " +
                "straight past it. “Allow only these sites” is impossible to " +
                "express in DNS, so whitelist mode blocks a curated set of time-sinks " +
                "minus your allow-list. This is a tool for a cooperative future self, " +
                "not a lock against someone determined to get round it."
        })
        return card
    }

    // --- plumbing -----------------------------------------------------------

    /** Run a use case and report a refusal instead of crashing on it. */
    private inline fun guarded(block: () -> Unit) {
        try {
            block()
        } catch (e: LockedError) {
            toast(e.message ?: "Locked")
        } catch (e: Exception) {
            toast(e.message ?: "That did not work")
        }
        renderAll()
    }

    private fun ensureVpn(then: () -> Unit) {
        val consent = VpnService.prepare(this)
        if (consent != null) {
            pendingAfterConsent = then
            startActivityForResult(consent, REQ_VPN)
        } else {
            BlockerVpnService.start(this)
            then()
            renderAll()
        }
    }

    private fun stopProtection() {
        // Stopping the service is a weakening operation, so it goes through the
        // same gate as everything else: refuse while a locked session runs.
        val s = control.status()
        if (s.sessionActive && s.locked) {
            toast("A locked focus session is running — ${Notifications.fmt(s.sessionRemaining)} left.")
            renderAll()
            return
        }
        BlockerVpnService.stop(this)
        toast("Protection off")
        renderAll()
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != REQ_VPN) return
        if (resultCode == RESULT_OK) {
            BlockerVpnService.start(this)
            pendingAfterConsent?.invoke()
        } else {
            toast("Without VPN permission nothing can be blocked.")
        }
        pendingAfterConsent = null
        renderAll()
    }

    private fun renderAll() {
        snap = control.status()
        renders.forEach { it() }
    }

    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_LONG).show()

    override fun onResume() {
        super.onResume()
        tick()
    }

    override fun onPause() {
        super.onPause()
        ticker.removeCallbacksAndMessages(null)
    }

    /** One second is the countdown's resolution; nothing here is expensive
     *  enough to need less, and anything slower makes the timer look stuck. */
    private fun tick() {
        renderAll()
        ticker.postDelayed({ tick() }, 1000)
    }

    companion object {
        private const val REQ_VPN = 1001
        private const val REQ_NOTIF = 1002
    }
}
