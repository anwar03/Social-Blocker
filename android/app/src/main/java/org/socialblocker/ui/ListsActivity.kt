package org.socialblocker.ui

import android.app.Activity
import android.os.Bundle
import android.view.Gravity
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import org.socialblocker.core.Control
import org.socialblocker.core.LockedError
import org.socialblocker.platform.App

/**
 * Edit the blacklist and the whitelist.
 *
 * Both lists are edited through `Control`, which is why "remove a domain"
 * behaves differently between them without this screen knowing why: shrinking
 * the blacklist during a locked blacklist session is refused, while adding to
 * the whitelist mid-lock is allowed. That asymmetry is a rule about focus, not
 * about a text field, so it lives in the use case.
 */
class ListsActivity : Activity() {

    private lateinit var control: Control
    private lateinit var p: Palette
    private lateinit var page: LinearLayout

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
        val (blocklist, whitelist) = control.lists()

        page.addView(listCard(
            title = "Blacklist",
            subtitle = "Blocked all day in blacklist mode.",
            entries = blocklist,
            onAdd = { control.addToBlocklist(listOf(it)) },
            onRemove = { control.removeFromBlocklist(listOf(it)) },
        ))
        page.addView(listCard(
            title = "Whitelist",
            subtitle = "The only sites that stay reachable during a whitelist session.",
            entries = whitelist,
            onAdd = { control.addToWhitelist(listOf(it)) },
            onRemove = { control.removeFromWhitelist(listOf(it)) },
        ))
    }

    private fun listCard(
        title: String, subtitle: String, entries: List<String>,
        onAdd: (String) -> Unit, onRemove: (String) -> Unit,
    ): LinearLayout {
        val card = card(p)
        card.addView(heading(p, "$title · ${entries.size}"))
        card.addView(body(p, subtitle, 12f, p.faint))

        val input = EditText(this).apply {
            hint = "example.com"
            setTextColor(p.text)
            setHintTextColor(p.faint)
            textSize = 15f
            setSingleLine()
            background = pillBackground(this@ListsActivity, p.sunk, p.line)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            layoutParams = LinearLayout.LayoutParams(0, dp(46), 1f)
                .apply { marginEnd = dp(8) }
        }
        val addRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { topMargin = dp(10); bottomMargin = dp(6) }
            addView(input)
            addView(Button(this@ListsActivity).apply {
                text = "Add"
                isAllCaps = false
                stateListAnimator = null
                setTextColor(p.onAccent)
                background = pillBackground(this@ListsActivity, p.teal, p.teal, 12)
                layoutParams = LinearLayout.LayoutParams(dp(84), dp(46))
                setOnClickListener {
                    val value = input.text.toString().trim()
                    if (value.isEmpty()) return@setOnClickListener
                    act { onAdd(value) }
                }
            })
        }
        card.addView(addRow)

        entries.forEach { domain ->
            card.addView(LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
                ).apply { topMargin = dp(2) }
                addView(TextView(this@ListsActivity).apply {
                    text = domain
                    setTextColor(p.muted)
                    textSize = 14f
                    layoutParams = LinearLayout.LayoutParams(
                        0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                })
                addView(Button(this@ListsActivity).apply {
                    text = "×"
                    isAllCaps = false
                    textSize = 16f
                    setTextColor(p.danger)
                    stateListAnimator = null
                    background = pillBackground(this@ListsActivity, p.card, p.line)
                    layoutParams = LinearLayout.LayoutParams(dp(48), dp(38))
                    setOnClickListener { act { onRemove(domain) } }
                })
            })
        }
        return card
    }

    /** Run a list edit, report a refusal, and redraw from the saved state
     *  rather than from what this screen thinks it did. */
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
}
