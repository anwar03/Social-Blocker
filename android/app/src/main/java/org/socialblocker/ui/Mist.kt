package org.socialblocker.ui

import android.content.Context
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView

/**
 * Mist and Ink — the desktop tool's two palettes, ported unchanged.
 *
 * The RGB values here are copied from `socialblocker/mistkit.py`, including the
 * alpha-over-card arithmetic for hairlines, so the phone and the desktop are
 * recognisably the same product rather than two apps with a shared name. Ink's
 * measured contrast against its own card (PINE 13.5, SLATE 7.1, TEAL 6.5,
 * AMBER 7.3, DANGER 5.0) carries over with the numbers.
 */
data class Palette(
    val dark: Boolean,
    val fogTop: Int, val fogBottom: Int,
    val card: Int, val raised: Int, val sunk: Int,
    val text: Int, val muted: Int, val faint: Int,
    val teal: Int, val tealDeep: Int, val amber: Int, val danger: Int,
    val line: Int, val onAccent: Int,
)

private fun rgb(r: Int, g: Int, b: Int) = Color.rgb(r, g, b)

/** Composite [fg] at [alpha] over [bg] — mistkit's `_over`, so hairlines land
 *  on the same value they do on the desktop. */
private fun over(fg: Int, bg: Int, alpha: Double): Int = rgb(
    (Color.red(fg) * alpha + Color.red(bg) * (1 - alpha)).toInt(),
    (Color.green(fg) * alpha + Color.green(bg) * (1 - alpha)).toInt(),
    (Color.blue(fg) * alpha + Color.blue(bg) * (1 - alpha)).toInt(),
)

object Mist {

    private val MIST_CARD = rgb(0xFB, 0xFD, 0xFD)
    private val INK_CARD = rgb(0x16, 0x24, 0x2A)

    val LIGHT = Palette(
        dark = false,
        fogTop = rgb(0xEE, 0xF3, 0xF4), fogBottom = rgb(0xD9, 0xE3, 0xE6),
        card = MIST_CARD, raised = Color.WHITE, sunk = rgb(0xEE, 0xF3, 0xF4),
        text = Color.parseColor("#16272c"),
        muted = Color.parseColor("#5f7378"),
        faint = Color.parseColor("#85989d"),
        teal = rgb(0x2F, 0x8F, 0x9D), tealDeep = rgb(0x21, 0x74, 0x80),
        amber = rgb(0xB9, 0x77, 0x2F), danger = Color.parseColor("#b6503f"),
        line = over(rgb(0x15, 0x26, 0x2B), MIST_CARD, 0.10),
        onAccent = Color.WHITE,
    )

    val DARK = Palette(
        dark = true,
        fogTop = rgb(0x0E, 0x18, 0x1C), fogBottom = rgb(0x08, 0x10, 0x13),
        card = INK_CARD, raised = rgb(0x1E, 0x2F, 0x36), sunk = rgb(0x0E, 0x18, 0x1C),
        text = Color.parseColor("#e6eef0"),
        muted = Color.parseColor("#9db1b7"),
        faint = Color.parseColor("#74898f"),
        teal = rgb(0x4F, 0xB3, 0xC2), tealDeep = rgb(0x86, 0xD5, 0xE0),
        amber = rgb(0xDF, 0xA4, 0x5F), danger = Color.parseColor("#e0705c"),
        line = over(rgb(0xC6, 0xDC, 0xE0), INK_CARD, 0.16),
        onAccent = INK_CARD,
    )

    /** Follow the system scheme, the way the desktop GUI follows the portal. */
    fun of(ctx: Context): Palette {
        val night = ctx.resources.configuration.uiMode and
            Configuration.UI_MODE_NIGHT_MASK == Configuration.UI_MODE_NIGHT_YES
        return if (night) DARK else LIGHT
    }
}

// --- view helpers -----------------------------------------------------------
//
// The UI is built in Kotlin rather than XML on purpose: with zero AndroidX and
// a palette that is computed rather than declared, an XML layout would need a
// second copy of every colour as a resource. One source, no drift.

fun Context.dp(v: Int): Int = TypedValue.applyDimension(
    TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics
).toInt()

const val CARD_RADIUS_DP = 14

fun cardBackground(ctx: Context, p: Palette, fill: Int = p.card): GradientDrawable =
    GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        cornerRadius = ctx.dp(CARD_RADIUS_DP).toFloat()
        setColor(fill)
        setStroke(maxOf(1, ctx.dp(1) / 2), p.line)
    }

fun pillBackground(ctx: Context, fill: Int, stroke: Int, radiusDp: Int = 10): GradientDrawable =
    GradientDrawable().apply {
        cornerRadius = ctx.dp(radiusDp).toFloat()
        setColor(fill)
        setStroke(maxOf(1, ctx.dp(1) / 2), stroke)
    }

fun Context.card(p: Palette): LinearLayout = LinearLayout(this).apply {
    orientation = LinearLayout.VERTICAL
    background = cardBackground(this@card, p)
    val pad = dp(16)
    setPadding(pad, pad, pad, pad)
    layoutParams = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
    ).apply { bottomMargin = dp(12) }
}

fun Context.heading(p: Palette, text: String): TextView = TextView(this).apply {
    this.text = text.uppercase()
    setTextColor(p.faint)
    textSize = 11f
    letterSpacing = 0.12f
    setPadding(0, 0, 0, dp(10))
}

fun Context.body(p: Palette, text: String, size: Float = 14f, color: Int = p.muted): TextView =
    TextView(this).apply {
        this.text = text
        setTextColor(color)
        textSize = size
    }

/** A filled accent button — the Primary role from the desktop's widget kit. */
fun Context.primaryButton(p: Palette, label: String, onClick: () -> Unit): Button =
    Button(this).apply {
        text = label
        isAllCaps = false
        setTextColor(p.onAccent)
        background = pillBackground(this@primaryButton, p.teal, p.teal, 12)
        stateListAnimator = null
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(46)
        ).apply { topMargin = dp(8) }
    }

/** An outlined button — the Secondary role. */
fun Context.ghostButton(p: Palette, label: String, tint: Int = p.teal, onClick: () -> Unit): Button =
    Button(this).apply {
        text = label
        isAllCaps = false
        setTextColor(tint)
        background = pillBackground(this@ghostButton, p.card, p.line, 12)
        stateListAnimator = null
        setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(
            0, dp(44), 1f
        ).apply { marginEnd = dp(8) }
    }

/**
 * A segmented control: exactly one option selected, like the desktop's
 * `PillGroup`. Returns a function that re-renders it, so callers keep no view
 * references of their own.
 */
fun Context.pillGroup(
    p: Palette,
    options: List<Pair<String, String>>,     // value to label
    selected: () -> String,
    onPick: (String) -> Unit,
): Pair<LinearLayout, () -> Unit> {
    val row = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        )
    }
    val buttons = options.map { (value, label) ->
        Button(this).apply {
            text = label
            isAllCaps = false
            textSize = 13f
            stateListAnimator = null
            setOnClickListener { onPick(value) }
            layoutParams = LinearLayout.LayoutParams(0, dp(42), 1f)
                .apply { marginEnd = dp(6) }
            row.addView(this)
        }
    }
    val render = {
        val now = selected()
        options.forEachIndexed { i, (value, _) ->
            val on = value == now
            buttons[i].background = pillBackground(
                this, if (on) p.teal else p.card, if (on) p.teal else p.line
            )
            buttons[i].setTextColor(if (on) p.onAccent else p.muted)
        }
    }
    render()
    return row to render
}

/**
 * A `−  value unit  +` stepper. The desktop learned to derive the row height
 * from this widget rather than hand-tuning padding; the same rule applies here,
 * so anything placed beside it takes [HEIGHT_DP].
 */
fun Context.stepper(
    p: Palette,
    value: () -> Int,
    unit: String,
    step: Int,
    min: Int,
    max: Int,
    onChange: (Int) -> Unit,
): LinearLayout {
    val label = TextView(this).apply {
        gravity = Gravity.CENTER
        setTextColor(p.text)
        textSize = 15f
        layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f)
    }
    fun refresh() { label.text = "${value()} $unit" }

    fun arrow(sign: Int, glyph: String) = Button(this).apply {
        text = glyph
        isAllCaps = false
        textSize = 18f
        setTextColor(p.teal)
        stateListAnimator = null
        background = pillBackground(this@stepper, p.raised, p.line)
        setOnClickListener {
            val next = (value() + sign * step).coerceIn(min, max)
            onChange(next)
            refresh()
        }
        layoutParams = LinearLayout.LayoutParams(dp(52), ViewGroup.LayoutParams.MATCH_PARENT)
    }

    return LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        background = pillBackground(this@stepper, p.sunk, p.line)
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(HEIGHT_DP)
        ).apply { topMargin = dp(8); bottomMargin = dp(8) }
        addView(arrow(-1, "−"))
        addView(label)
        addView(arrow(+1, "+"))
        refresh()
    }
}

const val HEIGHT_DP = 46

/** A label + switch row. */
fun Context.switchRow(
    p: Palette, label: String, hint: String?,
    checked: () -> Boolean, onToggle: (Boolean) -> Unit,
): LinearLayout {
    val texts = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        addView(body(p, label, 15f, p.text))
        if (hint != null) addView(body(p, hint, 12f, p.faint))
    }
    val sw = android.widget.Switch(this).apply {
        isChecked = checked()
        setOnCheckedChangeListener { _, v -> onToggle(v) }
    }
    return LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { topMargin = dp(6); bottomMargin = dp(6) }
        addView(texts)
        addView(sw)
        // View.setTag(int, Object) rejects any key that is not a real resource
        // id, so the tag lives in res/values/ids.xml rather than as a literal.
        setTag(org.socialblocker.R.id.sb_switch, sw)
    }
}

fun View.switchView(): android.widget.Switch? =
    getTag(org.socialblocker.R.id.sb_switch) as? android.widget.Switch
