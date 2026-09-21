package org.socialblocker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.socialblocker.core.Autostart
import org.socialblocker.core.BLACKLIST
import org.socialblocker.core.BlockEngine
import org.socialblocker.core.BOOT
import org.socialblocker.core.Catalog
import org.socialblocker.core.Control
import org.socialblocker.core.Enforcer
import org.socialblocker.core.ListSource
import org.socialblocker.core.LockedError
import org.socialblocker.core.OFF
import org.socialblocker.core.RuleSet
import org.socialblocker.core.ScheduleRule
import org.socialblocker.core.Session
import org.socialblocker.core.State
import org.socialblocker.core.Store
import org.socialblocker.core.WHITELIST
import org.socialblocker.core.now
import java.io.File
import java.nio.file.Files
import java.util.Calendar

/**
 * The core runs on a plain JVM with no emulator, which is the payoff for
 * keeping Android out of it. Priorities follow the project's testing rules:
 * mode resolution, the engine's generated rule set, and locked-mode
 * enforcement — the three places where a bug means either a broken phone or a
 * focus session that quietly stopped working.
 *
 * The lists come from the repository's own data/ folder, the same files the
 * APK ships, so a malformed blocklist.json fails here rather than on a device.
 */
class CoreTest {

    /** Reads the repo's data/ directly — the test-side implementation of the
     *  port the app fills with assets/. */
    private class RepoLists : ListSource {
        private val dir = File("../../data")
        override fun read(name: String): String = File(dir, name).readText()
    }

    private class Recorder : Enforcer {
        var last: RuleSet? = null
        var applies = 0
        override fun apply(rules: RuleSet) { last = rules; applies++ }
    }

    private lateinit var tmp: File
    private lateinit var catalog: Catalog
    private lateinit var engine: BlockEngine
    private lateinit var store: Store
    private lateinit var enforcer: Recorder
    private lateinit var control: Control

    @Before
    fun setUp() {
        tmp = Files.createTempDirectory("sb-test").toFile()
        catalog = Catalog(RepoLists())
        engine = BlockEngine(catalog)
        store = Store(tmp, catalog)
        enforcer = Recorder()
        control = Control(store, engine, catalog, enforcer)
    }

    // --- the bundled data files --------------------------------------------

    @Test
    fun `bundled lists parse and are non-empty`() {
        assertTrue(catalog.defaultBlocklist().isNotEmpty())
        assertTrue(catalog.defaultWhitelist().isNotEmpty())
        assertTrue(catalog.universe().isNotEmpty())
        assertTrue(catalog.presets().isNotEmpty())
        assertTrue(catalog.presets().all { it.defaultMinutes > 0 })
        assertTrue(catalog.presets().all { it.mode == WHITELIST || it.mode == BLACKLIST })
    }

    // --- mode resolution ----------------------------------------------------

    @Test
    fun `an active session beats a schedule and the default`() {
        val state = State.defaults(catalog).apply {
            defaultMode = BLACKLIST
            schedules = listOf(allDayRule(BLACKLIST))
            session = Session(mode = WHITELIST, endsAt = now() + 600, locked = true)
        }
        assertEquals(WHITELIST to true, state.effective())
    }

    @Test
    fun `a matching schedule beats the default`() {
        val state = State.defaults(catalog).apply {
            defaultMode = OFF
            schedules = listOf(allDayRule(WHITELIST, locked = true))
        }
        assertEquals(WHITELIST to true, state.effective())
    }

    @Test
    fun `an expired session does not win`() {
        val state = State.defaults(catalog).apply {
            defaultMode = BLACKLIST
            session = Session(mode = WHITELIST, endsAt = now() - 1)
        }
        assertEquals(BLACKLIST to false, state.effective())
    }

    @Test
    fun `a disabled rule and a rule for another weekday are ignored`() {
        val today = todayIndex()
        val state = State.defaults(catalog).apply {
            defaultMode = OFF
            schedules = listOf(
                allDayRule(WHITELIST).copy(enabled = false),
                allDayRule(BLACKLIST).copy(days = listOf((today + 3) % 7)),
            )
        }
        assertEquals(OFF to false, state.effective())
    }

    // --- the engine ---------------------------------------------------------

    @Test
    fun `off blocks nothing, blacklist blocks the list, whitelist blocks the rest`() {
        val state = State.defaults(catalog)
        assertEquals(0, engine.domainsForMode(state, OFF).size)
        assertEquals(state.blocklist.size, engine.domainsForMode(state, BLACKLIST).size)

        state.whitelist = listOf("github.com")
        val blocked = engine.domainsForMode(state, WHITELIST)
        assertFalse(blocked.contains("github.com"))
        assertEquals(catalog.universe().size - 1, blocked.size)
    }

    @Test
    fun `re-deriving the same state gives an identical rule set`() {
        // The service re-evaluates every five seconds; an unstable digest would
        // make it log a transition and redraw the notification forever.
        val state = State.defaults(catalog).apply { defaultMode = BLACKLIST }
        val a = engine.rules(state)
        val b = engine.rules(state)
        assertEquals(a.digest, b.digest)
        assertEquals(a.blocked, b.blocked)
    }

    @Test
    fun `matching covers subdomains but not lookalike domains`() {
        val rules = RuleSet(BLACKLIST, false, setOf("instagram.com", "reddit.com"))
        assertTrue(rules.isBlocked("instagram.com"))
        assertTrue(rules.isBlocked("i.instagram.com"))
        assertTrue(rules.isBlocked("graph.i.instagram.com"))
        assertTrue(rules.isBlocked("WWW.Instagram.COM"))       // case and www
        assertFalse(rules.isBlocked("notinstagram.com"))       // the bug a naive endsWith would have
        assertFalse(rules.isBlocked("instagram.com.evil.net"))
        assertFalse(rules.isBlocked("example.com"))
    }

    @Test
    fun `an empty rule set blocks nothing`() {
        assertFalse(RuleSet.EMPTY.isBlocked("instagram.com"))
    }

    // --- locked-mode enforcement -------------------------------------------

    @Test(expected = LockedError::class)
    fun `a locked session refuses stop`() {
        control.startSession(30, WHITELIST, locked = true)
        control.stopSession()
    }

    @Test
    fun `a locked session still allows extend`() {
        control.startSession(30, WHITELIST, locked = true)
        val before = store.load().session.endsAt
        control.extendSession(15)
        assertEquals(before + 900, store.load().session.endsAt, 1.0)
    }

    @Test(expected = LockedError::class)
    fun `a locked session refuses turning the default mode off`() {
        control.startSession(30, WHITELIST, locked = true)
        control.setDefaultMode(OFF)
    }

    @Test(expected = LockedError::class)
    fun `a locked session cannot be replaced by a shorter one`() {
        control.startSession(60, WHITELIST, locked = true)
        control.startSession(1, BLACKLIST, locked = false)
    }

    @Test(expected = LockedError::class)
    fun `a locked blacklist session refuses shrinking the blocklist`() {
        control.startSession(30, BLACKLIST, locked = true)
        control.removeFromBlocklist(listOf("instagram.com"))
    }

    @Test
    fun `a locked whitelist session still allows widening the allow-list`() {
        control.startSession(30, WHITELIST, locked = true)
        control.addToWhitelist(listOf("Example.COM"))
        assertTrue(store.load().whitelist.contains("example.com"))
    }

    @Test
    fun `an unlocked session stops cleanly`() {
        control.startSession(30, WHITELIST, locked = false)
        control.stopSession()
        assertFalse(store.load().session.active())
        // Stopping early is not focus work, so nothing is logged.
        assertEquals(0, store.load().focusLog.size)
    }

    // --- the focus log ------------------------------------------------------

    @Test
    fun `a completed session is logged exactly once`() {
        val ended = now() - 10
        seed(Session(mode = WHITELIST, startedAt = ended - 1500, endsAt = ended))

        assertTrue(control.reap())
        assertFalse(control.reap())       // idempotent: two racing reapers, one record
        val log = store.load().focusLog
        assertEquals(1, log.size)
        assertEquals(25, log[0].minutes)
        assertEquals(25, store.load().focusedTodayMin())
    }

    @Test
    fun `a boot block is enforced but never counted as focus`() {
        val ended = now() - 10
        seed(Session(mode = BLACKLIST, startedAt = ended - 18000, endsAt = ended, source = BOOT))
        control.reap()
        assertEquals(0, store.load().focusLog.size)
        assertEquals(0, store.load().streakDays())
    }

    // --- autostart ----------------------------------------------------------

    @Test
    fun `autostart arms once per boot and never twice`() {
        control.setAutostart(enabled = true, minutes = 60, mode = BLACKLIST, bootToken = "boot-1")
        // Enabling stamps the current boot, so this boot must not arm.
        assertNull(control.armBootSession("boot-1"))
        val armed = control.armBootSession("boot-2")
        assertNotNull(armed)
        assertEquals(BLACKLIST, armed!!.mode)
        assertNull(control.armBootSession("boot-2"))   // same boot, second call
        assertEquals(BOOT, store.load().session.source)
    }

    @Test
    fun `an unknown boot identity never arms`() {
        control.setAutostart(enabled = true, bootToken = "boot-1")
        assertNull(control.armBootSession(""))
    }

    @Test
    fun `rebooting does not shorten a locked session that survived it`() {
        control.setAutostart(enabled = true, minutes = 10, bootToken = "boot-1")
        control.startSession(120, WHITELIST, locked = true)
        val endsAt = store.load().session.endsAt

        assertNull(control.armBootSession("boot-2"))
        assertEquals(endsAt, store.load().session.endsAt, 0.001)
        // The boot is still recorded as handled, so it cannot arm later either.
        assertEquals("boot-2", store.load().autostart.lastBootToken)
    }

    // --- persistence --------------------------------------------------------

    @Test
    fun `state survives a round trip`() {
        val state = State.defaults(catalog).apply {
            defaultMode = WHITELIST
            schedules = listOf(ScheduleRule("07:30", "09:45", BLACKLIST, listOf(1, 3), true, true))
            autostart = Autostart(enabled = true, minutes = 45, mode = WHITELIST,
                locked = true, lastBootToken = "boot-9")
            session = Session(WHITELIST, now() + 60, now(), true)
        }
        store.save(state)
        val back = store.load()
        assertEquals(WHITELIST, back.defaultMode)
        assertEquals(state.schedules, back.schedules)
        assertEquals(state.autostart, back.autostart)
        assertTrue(back.session.locked)
        assertFalse(File(tmp, "state.json.tmp").exists())
    }

    @Test
    fun `a corrupt state file falls back to defaults instead of crashing`() {
        store.stateFile.writeText("{ this is not json")
        val back = store.load()
        assertEquals(BLACKLIST, back.defaultMode)
        assertTrue(back.blocklist.isNotEmpty())
    }

    @Test
    fun `every mutation re-applies the rules`() {
        val before = enforcer.applies
        control.setDefaultMode(BLACKLIST)
        assertEquals(before + 1, enforcer.applies)
        assertEquals(BLACKLIST, enforcer.last!!.mode)
    }

    // --- helpers ------------------------------------------------------------

    /** A rule that is certain to be matching right now. */
    private fun allDayRule(mode: String, locked: Boolean = false) =
        ScheduleRule("00:00", "24:00", mode, (0..6).toList(), locked, true)

    private fun todayIndex(): Int =
        (Calendar.getInstance().get(Calendar.DAY_OF_WEEK) + 5) % 7

    private fun seed(session: Session) {
        store.save(State.defaults(catalog).apply { this.session = session })
    }
}
