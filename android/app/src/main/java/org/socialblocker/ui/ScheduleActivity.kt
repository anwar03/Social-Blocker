package org.socialblocker.ui

import android.app.Activity
import android.app.TimePickerDialog
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import org.socialblocker.core.BLACKLIST
import org.socialblocker.core.Control
import org.socialblocker.core.LockedError
import org.socialblocker.core.ScheduleRule
import org.socialblocker.core.WHITELIST
import org.socialblocker.platform.App

/**
 * Recurring rules: "whitelist mode on weekday mornings".
 *
 * A schedule sits between the all-day default and a focus session in the
 * precedence order — session beats schedule beats default — and that ordering
 * is resolved in `State.effective()`, never here. This screen only collects a
 * time range, a weekday set and a mode.
 */
class ScheduleActivity : Activity() {

    private lateinit var control: Control
    private lateinit var p: Palette
    private lateinit var page: LinearLayout

    // Draft rule, UI-local until Add is pressed.
    private var start = "09:00"
    private var end = "12:00"
    private var mode = WHITELIST
    private var locked = false
    private val days = mutableSetOf(0, 1, 2, 3, 4)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        control = App.control(this)
        p = Mist.of(this)
        page = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(p.fogTop)
            val pad = dp(16)
            setPadding(pad, dp(20), pad, dp(32))
        }
        setContentView(ScrollView(this).apply {
            setBackgroundColor(p.fogTop)
            addView(page, ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        })
        rebuild()
    }

    private fun rebuild() {
        page.removeAllViews()
        page.addView(existingCard())
        page.addView(composerCard())
    }

    private fun existingCard(): LinearLayout {
        val rules = control.schedules()
        val card = card(p)
        card.addView(heading(p, "Active rules · ${rules.size}"))
        if (rules.isEmpty()) {
            card.addView(body(p, "No schedule rules yet.", 13f, p.faint))
            return card
        }
        rules.forEachIndexed { index, r ->
            card.addView(LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply { topMargin = dp(4) }
                addView(TextView(this@ScheduleActivity).apply {
                    text = "${r.start}–${r.end} · ${r.mode}" +
                        (if (r.locked) " · locked" else "") + "\n" + dayNames(r.days)
                    setTextColor(p.muted)
                    textSize = 13f
                    layoutParams = LinearLayout.LayoutParams(
                        0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                })
                addView(Button(this@ScheduleActivity).apply {
                    text = "×"
                    isAllCaps = false
                    setTextColor(p.danger)
                    stateListAnimator = null
                    background = pillBackground(this@ScheduleActivity, p.card, p.line)
                    layoutParams = LinearLayout.LayoutParams(dp(48), dp(40))
                    setOnClickListener { act { control.removeSchedule(index) } }
                })
            })
        }
        card.addView(ghostButton(p, "Clear all", p.danger) {
            act { control.clearSchedules() }
        }.apply {
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(44)
            ).apply { topMargin = dp(10) }
        })
        return card
    }

    private fun composerCard(): LinearLayout {
        val card = card(p)
        card.addView(heading(p, "New rule"))

        val timeRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(ghostButton(p, "From $start") { pickTime(start) { start = it; rebuild() } })
            addView(ghostButton(p, "To $end") { pickTime(end) { end = it; rebuild() } })
        }
        card.addView(timeRow)

        val (modeRow, _) = pillGroup(
            p, listOf(BLACKLIST to "Blacklist", WHITELIST to "Whitelist"),
            { mode },
        ) { mode = it; rebuild() }
        card.addView(modeRow)

        // Mon=0 .. Sun=6, matching the state file the desktop writes.
        val dayRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = dp(10) }
        }
        DAY_LABELS.forEachIndexed { index, label ->
            dayRow.addView(Button(this).apply {
                text = label
                isAllCaps = false
                textSize = 12f
                stateListAnimator = null
                val on = index in days
                background = pillBackground(
                    this@ScheduleActivity, if (on) p.teal else p.card, if (on) p.teal else p.line)
                setTextColor(if (on) p.onAccent else p.muted)
                layoutParams = LinearLayout.LayoutParams(0, dp(42), 1f)
                    .apply { marginEnd = dp(4) }
                setOnClickListener {
                    if (!days.remove(index)) days.add(index)
                    rebuild()
                }
            })
        }
        card.addView(dayRow)

        val lockRow = switchRow(
            p, "Locked", "The window cannot be cut short once it opens.",
            { locked },
        ) { locked = it }
        card.addView(lockRow)

        card.addView(primaryButton(p, "Add rule") {
            if (days.isEmpty()) {
                Toast.makeText(this, "Pick at least one day.", Toast.LENGTH_LONG).show()
            } else if (toMinutes(start) >= toMinutes(end)) {
                // Overnight windows would need two rules; say so rather than
                // silently storing a range that can never match.
                Toast.makeText(
                    this,
                    "The end time must be after the start. For an overnight window, " +
                        "add two rules.", Toast.LENGTH_LONG
                ).show()
            } else {
                act {
                    control.addSchedule(
                        ScheduleRule(start, end, mode, days.sorted(), locked, true))
                }
            }
        })
        return card
    }

    private fun pickTime(current: String, onPicked: (String) -> Unit) {
        val parts = current.split(":")
        TimePickerDialog(this, { _, h, m ->
            onPicked(String.format("%02d:%02d", h, m))
        }, parts[0].toInt(), parts[1].toInt(), true).show()
    }

    private fun toMinutes(hhmm: String): Int {
        val parts = hhmm.split(":")
        return parts[0].toInt() * 60 + parts[1].toInt()
    }

    private fun dayNames(days: List<Int>): String =
        if (days.size == 7) "Every day"
        else days.sorted().joinToString(" ") { DAY_LABELS.getOrElse(it) { "?" } }

    private inline fun act(block: () -> Unit) {
        try {
            block()
        } catch (e: LockedError) {
            Toast.makeText(this, e.message, Toast.LENGTH_LONG).show()
        } catch (e: Exception) {
            Toast.makeText(this, e.message ?: "That did not work", Toast.LENGTH_LONG).show()
        }
        rebuild()
    }

    companion object {
        private val DAY_LABELS = listOf("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    }
}
