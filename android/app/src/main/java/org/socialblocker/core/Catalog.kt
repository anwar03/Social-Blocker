package org.socialblocker.core

import org.json.JSONObject

/**
 * Where the bundled JSON lists come from.
 *
 * This is the port that keeps the core free of Android. On a phone the
 * implementation reads `assets/`; in a unit test it reads the repository's own
 * `data/` folder. Same files either way — the app module's Gradle script points
 * its assets source set straight at `../../data`, so the desktop tool and the
 * phone genuinely share one copy of the lists.
 */
interface ListSource {
    fun read(name: String): String
}

/** A quick-start focus preset (see data/presets.json). */
data class Preset(
    val name: String,
    val defaultMinutes: Int,
    val mode: String,
    val locked: Boolean,
    val blurb: String,
)

/**
 * The bundled default lists, parsed once and cached.
 *
 * Caching matters here in a way it does not on the desktop: the enforcement
 * loop re-evaluates policy every few seconds, and `universe.json` would
 * otherwise be re-parsed from the APK each time, on battery.
 */
class Catalog(private val source: ListSource) {

    private val blocklist: List<String> by lazy {
        val cats = JSONObject(source.read("blocklist.json")).getJSONObject("categories")
        val out = sortedSetOf<String>()
        cats.keys().forEach { key ->
            val arr = cats.getJSONArray(key)
            for (i in 0 until arr.length()) out.add(arr.getString(i))
        }
        out.toList()
    }

    private val whitelist: List<String> by lazy {
        val arr = JSONObject(source.read("whitelist.example.json")).getJSONArray("allow")
        (0 until arr.length()).map { arr.getString(it) }.toSortedSet().toList()
    }

    private val universe: List<String> by lazy {
        val arr = JSONObject(source.read("universe.json")).getJSONArray("domains")
        (0 until arr.length()).map { arr.getString(it) }.toSortedSet().toList()
    }

    private val presets: List<Preset> by lazy {
        val arr = JSONObject(source.read("presets.json")).getJSONArray("presets")
        (0 until arr.length()).map { i ->
            val o = arr.getJSONObject(i)
            Preset(
                name = o.optString("name", ""),
                defaultMinutes = o.optInt("default_minutes", 25),
                mode = o.optString("mode", WHITELIST),
                locked = o.optBoolean("locked", false),
                blurb = o.optString("blurb", ""),
            )
        }
    }

    fun defaultBlocklist(): List<String> = blocklist
    fun defaultWhitelist(): List<String> = whitelist
    fun universe(): List<String> = universe
    fun presets(): List<Preset> = presets
}
