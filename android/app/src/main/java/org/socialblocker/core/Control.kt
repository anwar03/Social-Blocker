package org.socialblocker.core

/** Raised when the user tries to weaken protection during a locked session. */
class LockedError(message: String) : RuntimeException(message)

/**
 * What "apply the rules" means to the outside world.
 *
 * The desktop's `control.py` calls the hosts engine directly, because writing a
 * file needs no framework. On a phone the same step has to reach a *running
 * service*, which is an outer-circle thing — so it is injected here instead.
 * That keeps the dependency rule intact: `Control` never imports `vpn`.
 */
interface Enforcer {
    fun apply(rules: RuleSet)
}

/** Everything a front-end needs to render, derived in one place. */
data class Status(
    val defaultMode: String,
    val effectiveMode: String,
    val locked: Boolean,
    val sessionActive: Boolean,
    val sessionRemaining: Int,
    val sessionMode: String,
    val sessionSource: String,
    val sessionStartedAt: Double,
    val sessionTotal: Int,
    val blocklistCount: Int,
    val whitelistCount: Int,
    val schedules: Int,
    val blockedNow: Int,
    val universeSize: Int,
    val focusedTodayMin: Int,
    val streakDays: Int,
    val autostartEnabled: Boolean,
    val autostartMinutes: Int,
    val autostartMode: String,
    val autostartLocked: Boolean,
)

/**
 * High-level operations shared by the UI, the Quick Settings tile and the
 * enforcement service — the phone's `control.py`.
 *
 * Every mutation goes: load state -> change -> save state -> re-apply rules.
 * THE LOCKED-SESSION RULE IS ENFORCED HERE AND NOWHERE ELSE. Do not scatter a
 * lock check into an Activity or the notification handler; add the operation
 * here instead.
 *
 * Every mutating method is `@Synchronized`. The desktop got away without a lock
 * because its CLI, GUI and daemon are separate processes reconciled by an
 * atomic file rename. Here they are threads in one process sharing one file, so
 * two concurrent read-modify-writes would genuinely lose an update — "stop" and
 * "extend" arriving together could resurrect a finished session.
 */
class Control(
    private val store: Store,
    private val engine: BlockEngine,
    private val catalog: Catalog,
    private val enforcer: Enforcer,
) {

    private fun guardLocked(state: State) {
        if (state.session.active() && state.session.locked) {
            val mins = (state.session.remaining() + 59) / 60
            throw LockedError(
                "A locked focus session is running. It cannot be stopped for " +
                    "another $mins min. That is the point of locked mode."
            )
        }
    }

    /**
     * Record a focus session that has ended, then clear it. Returns whether
     * [state] changed.
     *
     * A session that runs to completion has no natural event to hook, so every
     * load path reaps here (and so does the service loop). Recording is deduped
     * on the session's `endsAt`, which makes it idempotent when two callers
     * race to reap the same expiry — the minutes are counted once.
     */
    private fun reapCompleted(state: State): Boolean {
        val s = state.session
        if (s.endsAt == 0.0 || s.active()) return false
        // A boot block is enforcement, not focus work. Logging it would report
        // ~300 "focused" minutes every single day and make the streak a lie.
        val already = s.source == BOOT ||
            state.focusLog.any { Math.abs(it.endsAt - s.endsAt) < 1.0 }
        if (!already) {
            val minutes = if (s.startedAt > 0) Math.round((s.endsAt - s.startedAt) / 60).toInt() else 0
            state.focusLog = state.focusLog + FocusRecord(
                endsAt = s.endsAt, minutes = maxOf(0, minutes),
                mode = s.mode, locked = s.locked,
            )
            state.pruneLog()
        }
        state.session = Session()   // cleared; the session is over
        return true
    }

    /** Load state and reap a just-completed session in memory. Callers that
     *  save afterwards persist the reap; read-only callers use [reap]. */
    private fun load(): State = store.load().also { reapCompleted(it) }

    private fun commit(state: State): RuleSet {
        store.save(state)
        val rules = engine.rules(state)
        enforcer.apply(rules)
        return rules
    }

    /** Persistently log a just-completed session, if there is one. Used by the
     *  service loop so stats stay current even if the UI is never opened. */
    @Synchronized
    fun reap(): Boolean {
        val state = store.load()
        if (reapCompleted(state)) { store.save(state); return true }
        return false
    }

    /** Re-apply whatever the state says should be enforced right now. */
    @Synchronized
    fun refresh(): RuleSet {
        val state = store.load()
        if (reapCompleted(state)) store.save(state)
        val rules = engine.rules(state)
        enforcer.apply(rules)
        return rules
    }

    // --- default (all-day) mode --------------------------------------------

    @Synchronized
    fun setDefaultMode(mode: String): RuleSet {
        require(mode in MODES) { "mode must be one of $MODES" }
        val state = load()
        // Weakening the default mode during a locked session is not allowed.
        if (mode == OFF || (mode == BLACKLIST && state.defaultMode == WHITELIST)) {
            guardLocked(state)
        }
        state.defaultMode = mode
        return commit(state)
    }

    // --- focus sessions -----------------------------------------------------

    @Synchronized
    fun startSession(minutes: Int, mode: String = WHITELIST, locked: Boolean = false): RuleSet {
        require(mode == BLACKLIST || mode == WHITELIST) {
            "session mode must be 'blacklist' or 'whitelist'"
        }
        require(minutes > 0) { "session length must be positive" }
        val state = load()
        if (state.session.active()) guardLocked(state)   // cannot replace a locked session
        val t = now()
        state.session = Session(
            mode = mode, startedAt = t, endsAt = t + minutes * 60, locked = locked,
        )
        return commit(state)
    }

    @Synchronized
    fun stopSession(): RuleSet {
        val state = load()
        guardLocked(state)
        state.session = Session()   // stopping early does not count as focus
        return commit(state)
    }

    /** Extending is always allowed — even during a locked session. */
    @Synchronized
    fun extendSession(minutes: Int): RuleSet {
        val state = load()
        if (!state.session.active()) throw IllegalStateException("no active session to extend")
        state.session = state.session.copy(endsAt = state.session.endsAt + minutes * 60)
        return commit(state)
    }

    // --- list editing -------------------------------------------------------

    @Synchronized
    fun addToBlocklist(domains: List<String>) {
        val state = load()
        val add = domains.map(BlockEngine::normalize).filter { it.isNotEmpty() }
        state.blocklist = (state.blocklist + add).toSortedSet().toList()
        commit(state)
    }

    @Synchronized
    fun removeFromBlocklist(domains: List<String>) {
        val state = load()
        // Shrinking protection during a locked blacklist session is blocked.
        if (state.session.active() && state.session.mode == BLACKLIST) guardLocked(state)
        val drop = domains.map(BlockEngine::normalize).toSet()
        state.blocklist = state.blocklist.filter { BlockEngine.normalize(it) !in drop }
        commit(state)
    }

    /** Allowing more sites is always fine, even mid-lock: it only loosens the
     *  strict whitelist a little, and that friction is expected. */
    @Synchronized
    fun addToWhitelist(domains: List<String>) {
        val state = load()
        val add = domains.map(BlockEngine::normalize).filter { it.isNotEmpty() }
        state.whitelist = (state.whitelist + add).toSortedSet().toList()
        commit(state)
    }

    @Synchronized
    fun removeFromWhitelist(domains: List<String>) {
        val state = load()
        val drop = domains.map(BlockEngine::normalize).toSet()
        state.whitelist = state.whitelist.filter { BlockEngine.normalize(it) !in drop }
        commit(state)
    }

    // --- schedules ----------------------------------------------------------

    @Synchronized
    fun addSchedule(rule: ScheduleRule) {
        val state = load()
        state.schedules = state.schedules + rule
        commit(state)
    }

    @Synchronized
    fun removeSchedule(index: Int) {
        val state = load()
        guardLocked(state)
        state.schedules = state.schedules.filterIndexed { i, _ -> i != index }
        commit(state)
    }

    @Synchronized
    fun clearSchedules() {
        val state = load()
        guardLocked(state)
        state.schedules = emptyList()
        commit(state)
    }

    @Synchronized
    fun schedules(): List<ScheduleRule> = store.load().schedules

    // --- autostart ----------------------------------------------------------

    /**
     * Update the boot-block config. Only the arguments passed are changed.
     *
     * No locked-mode guard: this configures the *next* boot and cannot shorten
     * or weaken the session running right now.
     */
    @Synchronized
    fun setAutostart(
        enabled: Boolean? = null,
        minutes: Int? = null,
        mode: String? = null,
        locked: Boolean? = null,
        bootToken: String = "",
    ): Autostart {
        val state = load()
        var a = state.autostart
        val wasEnabled = a.enabled

        if (mode != null) {
            require(mode == BLACKLIST || mode == WHITELIST) {
                "autostart mode must be 'blacklist' or 'whitelist'"
            }
            a = a.copy(mode = mode)
        }
        if (minutes != null) {
            require(minutes > 0) { "autostart length must be positive" }
            a = a.copy(minutes = minutes)
        }
        if (locked != null) a = a.copy(locked = locked)
        if (enabled != null) a = a.copy(enabled = enabled)

        // Turning it on stamps the current boot as already handled, so the
        // setting takes effect from the *next* boot. Without this, the next
        // time Android revived the service today it would arm a block the user
        // never asked for right now.
        if (a.enabled && !wasEnabled) a = a.copy(lastBootToken = bootToken)

        state.autostart = a
        store.save(state)
        return a
    }

    /**
     * Start the configured boot block, at most once per device boot.
     *
     * Called when BOOT_COMPLETED arrives and again whenever the service starts,
     * because Android gives no guarantee about which happens first. Returns
     * what was armed, or null. Skipped when:
     *  - autostart is off, or the boot identity is unknown (fail safe: never
     *    arm rather than risk arming repeatedly);
     *  - this boot was already handled (the START_STICKY revival case);
     *  - a session is already running — including a locked one that survived a
     *    reboot, which must not be shortened or replaced by rebooting.
     */
    @Synchronized
    fun armBootSession(bootToken: String): RuleSet? {
        val state = load()
        val a = state.autostart
        if (!a.enabled) return null
        if (bootToken.isEmpty() || bootToken == a.lastBootToken) return null

        state.autostart = a.copy(lastBootToken = bootToken)

        if (state.session.active()) {
            store.save(state)   // remember this boot; leave the session alone
            return null
        }

        // Written as one state object (key + session) so a single atomic save
        // records both — a crash cannot leave the boot marked as handled with
        // no session started. That is why this does not route through
        // startSession().
        val t = now()
        state.session = Session(
            mode = a.mode, startedAt = t, endsAt = t + a.minutes * 60,
            locked = a.locked, source = BOOT,
        )
        return commit(state)
    }

    // --- presets ------------------------------------------------------------

    fun listPresets(): List<Preset> = catalog.presets()

    /**
     * Start a focus session from a named preset.
     *
     * A preset is only a starting point: pass [minutes] to override its default
     * duration (the UI does this via the stepper). Locked-mode enforcement
     * still happens in [startSession] — presets never bypass the choke point.
     */
    fun startPreset(name: String, minutes: Int? = null): RuleSet {
        val p = catalog.presets().firstOrNull { it.name.equals(name, ignoreCase = true) }
            ?: throw IllegalArgumentException(
                "unknown preset '$name'. Available: " +
                    catalog.presets().joinToString(", ") { it.name }
            )
        return startSession(minutes ?: p.defaultMinutes, p.mode, p.locked)
    }

    // --- status -------------------------------------------------------------

    @Synchronized
    fun status(): Status {
        val state = store.load()
        if (reapCompleted(state)) store.save(state)
        val (mode, locked) = state.effective()
        // "blocked now" is the truthful effective count from the engine — the
        // same set it would sinkhole, so no front-end re-derives it.
        val blockedNow = engine.domainsForMode(state, mode).size
        return Status(
            defaultMode = state.defaultMode,
            effectiveMode = mode,
            locked = locked,
            sessionActive = state.session.active(),
            sessionRemaining = state.session.remaining(),
            sessionMode = state.session.mode,
            sessionSource = state.session.source,
            // Elapsed-fraction inputs for the progress ring. Derived here so no
            // front-end does arithmetic on the session entity, and so `extend`
            // rescales the total rather than overshooting it.
            sessionStartedAt = state.session.startedAt,
            sessionTotal = maxOf(0, (state.session.endsAt - state.session.startedAt).toInt()),
            blocklistCount = state.blocklist.size,
            whitelistCount = state.whitelist.size,
            schedules = state.schedules.size,
            blockedNow = blockedNow,
            universeSize = catalog.universe().size,
            focusedTodayMin = state.focusedTodayMin(),
            streakDays = state.streakDays(),
            autostartEnabled = state.autostart.enabled,
            autostartMinutes = state.autostart.minutes,
            autostartMode = state.autostart.mode,
            autostartLocked = state.autostart.locked,
        )
    }

    /** Read-only access for front-ends that need the raw lists. */
    fun lists(): Pair<List<String>, List<String>> {
        val s = store.load()
        return s.blocklist to s.whitelist
    }
}
