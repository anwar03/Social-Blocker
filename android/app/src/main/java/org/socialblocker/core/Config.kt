package org.socialblocker.core

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * Configuration, state model and mode resolution — the INNERMOST circle.
 *
 * This is the phone's `config.py`. It imports nothing from `vpn`, `ui` or
 * `platform`: no Android framework types appear in this file, which is exactly
 * why the whole layer is testable on a plain JVM.
 *
 * Effective-mode precedence is owned here and nowhere else:
 *     active session  >  matching schedule rule  >  default mode
 */

const val OFF = "off"
const val BLACKLIST = "blacklist"
const val WHITELIST = "whitelist"
val MODES = listOf(OFF, BLACKLIST, WHITELIST)

/** Where a session came from. A boot block is enforcement, not focus work, so
 *  it is deliberately excluded from the focus log (see Control.reapCompleted). */
const val MANUAL = "manual"
const val BOOT = "boot"

/** How many days of completed-session history to keep (bounds state.json). */
const val LOG_RETENTION_DAYS = 90L

/** Unix time in seconds, as a double — the desktop's `time.time()`. */
fun now(): Double = System.currentTimeMillis() / 1000.0

/** Local-calendar day number for a unix timestamp. Contiguous integers, so
 *  consecutive days differ by 1 — that is what makes the focus streak work.
 *  The exact analogue of the desktop's `date.fromtimestamp(ts).toordinal()`. */
fun dayOrd(ts: Double): Long =
    Instant.ofEpochMilli((ts * 1000).toLong())
        .atZone(ZoneId.systemDefault()).toLocalDate().toEpochDay()

private fun toMin(hhmm: String): Int {
    val parts = hhmm.split(":")
    return parts[0].trim().toInt() * 60 + parts[1].trim().toInt()
}

// --- Entities ---------------------------------------------------------------

/** An active focus block. */
data class Session(
    val mode: String = WHITELIST,
    val endsAt: Double = 0.0,
    val startedAt: Double = 0.0,
    val locked: Boolean = false,
    val source: String = MANUAL,
) {
    fun active(): Boolean = endsAt > now()
    fun remaining(): Int = maxOf(0, (endsAt - now()).toInt())

    fun toJson(): JSONObject = JSONObject()
        .put("mode", mode).put("ends_at", endsAt).put("started_at", startedAt)
        .put("locked", locked).put("source", source)

    companion object {
        fun fromJson(o: JSONObject?): Session {
            if (o == null) return Session()
            return Session(
                mode = o.optString("mode", WHITELIST),
                endsAt = o.optDouble("ends_at", 0.0),
                startedAt = o.optDouble("started_at", 0.0),
                locked = o.optBoolean("locked", false),
                source = o.optString("source", MANUAL),
            )
        }
    }
}

/**
 * A completed focus session, kept so we can show focus stats.
 *
 * `endsAt` doubles as a dedupe key: reaping the same expiry twice (the service
 * loop and a UI action racing) must not double-count it.
 */
data class FocusRecord(
    val endsAt: Double = 0.0,
    val minutes: Int = 0,
    val mode: String = WHITELIST,
    val locked: Boolean = false,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("ended_at", endsAt).put("minutes", minutes)
        .put("mode", mode).put("locked", locked)

    companion object {
        fun fromJson(o: JSONObject) = FocusRecord(
            endsAt = o.optDouble("ended_at", 0.0),
            minutes = o.optInt("minutes", 0),
            mode = o.optString("mode", WHITELIST),
            locked = o.optBoolean("locked", false),
        )
    }
}

/**
 * Automatically switch to [mode] during [start]..[end] on the given weekdays.
 * Times are "HH:MM" (24h); [days] holds ints with Mon=0 .. Sun=6, matching the
 * desktop's `time.localtime().tm_wday` so one state file describes both.
 */
data class ScheduleRule(
    val start: String = "09:00",
    val end: String = "12:00",
    val mode: String = WHITELIST,
    val days: List<Int> = listOf(0, 1, 2, 3, 4),
    val locked: Boolean = false,
    val enabled: Boolean = true,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("start", start).put("end", end).put("mode", mode)
        .put("days", JSONArray(days)).put("locked", locked).put("enabled", enabled)

    companion object {
        fun fromJson(o: JSONObject): ScheduleRule {
            val arr = o.optJSONArray("days")
            val days = if (arr == null) listOf(0, 1, 2, 3, 4)
            else (0 until arr.length()).map { arr.getInt(it) }
            return ScheduleRule(
                start = o.optString("start", "09:00"),
                end = o.optString("end", "12:00"),
                mode = o.optString("mode", WHITELIST),
                days = days,
                locked = o.optBoolean("locked", false),
                enabled = o.optBoolean("enabled", true),
            )
        }
    }
}

/**
 * Arm a block automatically, once per device boot.
 *
 * [lastBootToken] is the dedupe key, and it is the whole reason this works: the
 * enforcement service is `START_STICKY` and Android restarts it freely, so
 * "arm a session when the service starts" would re-arm a full timer every time
 * the OS killed and revived it — you stop the block, the system restarts the
 * service, and it comes straight back. Keying on the *boot* makes arming happen
 * exactly once per boot.
 */
data class Autostart(
    val enabled: Boolean = false,
    val minutes: Int = 300,
    val mode: String = BLACKLIST,   // 5h of whitelist from unlock is too brutal a default
    val locked: Boolean = false,
    val lastBootToken: String = "",
) {
    fun toJson(): JSONObject = JSONObject()
        .put("enabled", enabled).put("minutes", minutes).put("mode", mode)
        .put("locked", locked).put("last_boot_id", lastBootToken)

    companion object {
        fun fromJson(o: JSONObject?): Autostart {
            if (o == null) return Autostart()
            return Autostart(
                enabled = o.optBoolean("enabled", false),
                minutes = o.optInt("minutes", 300),
                mode = o.optString("mode", BLACKLIST),
                locked = o.optBoolean("locked", false),
                // Same JSON key as the desktop's boot_id, so a state file copied
                // between the two stays readable.
                lastBootToken = o.optString("last_boot_id", ""),
            )
        }
    }
}

// --- Aggregate state --------------------------------------------------------

/** The single source of truth every front-end and the service agree on. */
data class State(
    var defaultMode: String = BLACKLIST,
    var blocklist: List<String> = emptyList(),
    var whitelist: List<String> = emptyList(),
    var session: Session = Session(),
    var schedules: List<ScheduleRule> = emptyList(),
    var focusLog: List<FocusRecord> = emptyList(),
    var autostart: Autostart = Autostart(),
) {

    /**
     * The (mode, locked) pair that should be enforced right now.
     * Priority: active session > matching schedule rule > defaultMode.
     */
    fun effective(): Pair<String, Boolean> {
        if (session.active()) return session.mode to session.locked
        currentRule()?.let { return it.mode to it.locked }
        return defaultMode to false
    }

    fun currentRule(): ScheduleRule? {
        val cal = java.util.Calendar.getInstance()
        val nowMin = cal.get(java.util.Calendar.HOUR_OF_DAY) * 60 +
                cal.get(java.util.Calendar.MINUTE)
        // Calendar has Sunday=1..Saturday=7; the state file uses Mon=0..Sun=6.
        val wd = (cal.get(java.util.Calendar.DAY_OF_WEEK) + 5) % 7
        return schedules.firstOrNull { r ->
            r.enabled && wd in r.days && toMin(r.start) <= nowMin && nowMin < toMin(r.end)
        }
    }

    /** Total focused minutes from sessions that completed today (local). */
    fun focusedTodayMin(): Int {
        val today = dayOrd(now())
        return focusLog.filter { dayOrd(it.endsAt) == today }.sumOf { it.minutes }
    }

    /**
     * Consecutive days (up to today) with at least one completed session.
     * If nothing has completed today yet the streak is measured up to
     * yesterday, so an in-progress day does not reset it prematurely.
     */
    fun streakDays(): Int {
        val days = focusLog.filter { it.minutes > 0 }.map { dayOrd(it.endsAt) }.toSet()
        if (days.isEmpty()) return 0
        val today = dayOrd(now())
        var cursor = if (today in days) today else today - 1
        if (cursor !in days) return 0
        var streak = 0
        while (cursor in days) { streak++; cursor-- }
        return streak
    }

    /** Drop records older than the retention window (bounds state size). */
    fun pruneLog() {
        val cutoff = dayOrd(now()) - LOG_RETENTION_DAYS
        focusLog = focusLog.filter { dayOrd(it.endsAt) >= cutoff }
    }

    fun toJson(): JSONObject = JSONObject()
        .put("default_mode", defaultMode)
        .put("blocklist", JSONArray(blocklist))
        .put("whitelist", JSONArray(whitelist))
        .put("session", session.toJson())
        .put("schedules", JSONArray(schedules.map { it.toJson() }))
        .put("focus_log", JSONArray(focusLog.map { it.toJson() }))
        .put("autostart", autostart.toJson())

    companion object {
        /** A fresh state seeded from the bundled lists. */
        fun defaults(catalog: Catalog) = State(
            blocklist = catalog.defaultBlocklist(),
            whitelist = catalog.defaultWhitelist(),
        )

        fun fromJson(o: JSONObject, catalog: Catalog): State {
            val block = o.optJSONArray("blocklist").toStringList()
            val allow = o.optJSONArray("whitelist").toStringList()
            return State(
                defaultMode = o.optString("default_mode", BLACKLIST),
                blocklist = block.ifEmpty { catalog.defaultBlocklist() },
                whitelist = allow.ifEmpty { catalog.defaultWhitelist() },
                session = Session.fromJson(o.optJSONObject("session")),
                schedules = o.optJSONArray("schedules").mapObjects(ScheduleRule::fromJson),
                focusLog = o.optJSONArray("focus_log").mapObjects(FocusRecord::fromJson),
                autostart = Autostart.fromJson(o.optJSONObject("autostart")),
            )
        }
    }
}

private fun JSONArray?.toStringList(): List<String> =
    if (this == null) emptyList() else (0 until length()).map { getString(it) }

private fun <T> JSONArray?.mapObjects(f: (JSONObject) -> T): List<T> =
    if (this == null) emptyList() else (0 until length()).map { f(getJSONObject(it)) }

// --- Persistence ------------------------------------------------------------

/**
 * Loads and saves `state.json`.
 *
 * [dir] is injected rather than looked up: it is this codebase's answer to the
 * desktop's `SOCIALBLOCKER_HOME` override. Tests pass a temp directory, the app
 * passes `Context.filesDir`, and no inner code ever hard-codes a path.
 */
class Store(private val dir: File, private val catalog: Catalog) {

    val stateFile: File = File(dir, "state.json")

    fun load(): State {
        if (!stateFile.exists()) return State.defaults(catalog)
        return try {
            State.fromJson(JSONObject(stateFile.readText(Charsets.UTF_8)), catalog)
        } catch (e: Exception) {
            State.defaults(catalog)   // corrupt state -> fresh defaults, never a crash
        }
    }

    /**
     * Atomic save: write a temp file, fsync it, then rename over the target.
     *
     * A half-written state file is how a focus blocker loses a locked session,
     * so the durability step is not optional. `rename(2)` on the same
     * filesystem is atomic; the `fd.sync()` before it is what guarantees the
     * bytes are on disk first, rather than only in the page cache, if the
     * phone loses power a moment later.
     */
    fun save(state: State) {
        dir.mkdirs()
        val tmp = File(dir, "state.json.tmp")
        FileOutputStream(tmp).use { out ->
            out.write(state.toJson().toString(2).toByteArray(Charsets.UTF_8))
            out.flush()
            out.fd.sync()
        }
        if (!tmp.renameTo(stateFile)) {
            tmp.delete()
            throw java.io.IOException("could not replace ${stateFile.path}")
        }
    }
}
