package org.socialblocker.core

/**
 * Enforcement engine: translates the effective mode into the set of domains to
 * sinkhole. This is the phone's `hosts_engine.py`.
 *
 *     off        -> block nothing
 *     blacklist  -> block state.blocklist
 *     whitelist  -> block (universe - state.whitelist)
 *
 * The honest limitation is inherited unchanged: DNS cannot express "allow only
 * X" any better than /etc/hosts could, so whitelist mode blocks a curated
 * universe of common time-sinks minus your allow-list.
 *
 * ONE DELIBERATE DIFFERENCE FROM THE DESKTOP. /etc/hosts has no wildcards, so
 * the desktop engine enumerates `example.com`, `www.example.com`,
 * `m.example.com` and stops there. A DNS sinkhole is asked the question
 * directly, so it can answer for any subdomain — which is what makes this work
 * against *apps*: the Instagram app never resolves `instagram.com`, it resolves
 * `i.instagram.com` and `graph.instagram.com`. Matching is therefore
 * suffix-based on the base domain. Strictly more blocking than the desktop,
 * from the same list.
 */
class BlockEngine(private val catalog: Catalog) {

    /** The base domains to block for a given mode. */
    fun domainsForMode(state: State, mode: String): List<String> = when (mode) {
        BLACKLIST -> state.blocklist.map(::normalize).filter { it.isNotEmpty() }.toSortedSet().toList()
        WHITELIST -> {
            val allow = state.whitelist.map(::normalize).toSet()
            catalog.universe().map(::normalize).filter { it.isNotEmpty() && it !in allow }
                .toSortedSet().toList()
        }
        else -> emptyList()   // OFF
    }

    /** What should be enforced right now, ready for the sinkhole to consult. */
    fun rules(state: State): RuleSet {
        val (mode, locked) = state.effective()
        return RuleSet(mode, locked, domainsForMode(state, mode).toSet())
    }

    companion object {
        fun normalize(domain: String): String =
            domain.trim().lowercase().trimStart('.').trimEnd('.')
    }
}

/**
 * An immutable snapshot of "what is blocked right now".
 *
 * The desktop writes this to /etc/hosts and re-reads the file to detect
 * tampering; here it is just a value the sinkhole thread holds. [digest] plays
 * the part of `Applied.changed`: comparing digests is how the policy loop tells
 * an idle no-op apart from a real transition, so the log and the notification
 * only speak when something actually moved.
 */
data class RuleSet(
    val mode: String,
    val locked: Boolean,
    val blocked: Set<String>,
) {
    val count: Int get() = blocked.size

    val digest: String = "$mode|$locked|${blocked.size}|${blocked.hashCode()}"

    /**
     * Should this query name be sinkholed?
     *
     * Walks the name's suffixes, so `graph.i.instagram.com` matches the base
     * domain `instagram.com` in three comparisons rather than a scan of the
     * whole set. O(labels), not O(rules) — the DNS path is on the hot path of
     * every connection the phone makes, so a linear scan of ~700 domains per
     * query would be felt.
     */
    fun isBlocked(queryName: String): Boolean {
        if (blocked.isEmpty()) return false
        var name = BlockEngine.normalize(queryName)
        while (name.isNotEmpty()) {
            if (name in blocked) return true
            val dot = name.indexOf('.')
            if (dot < 0) return false
            name = name.substring(dot + 1)
        }
        return false
    }

    companion object {
        val EMPTY = RuleSet(OFF, false, emptySet())
    }
}
