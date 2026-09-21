package org.socialblocker.platform

import android.app.Application
import android.content.Context
import org.socialblocker.core.Catalog
import org.socialblocker.core.Control
import org.socialblocker.core.BlockEngine
import org.socialblocker.core.ListSource
import org.socialblocker.core.Store

/**
 * Composition root — the one place the object graph is wired.
 *
 * The inner circles (`core`) never construct their own dependencies: the store
 * is handed a directory, the catalog is handed a [ListSource], and `Control` is
 * handed an [org.socialblocker.core.Enforcer]. That is what makes the whole
 * core testable on a plain JVM with a temp directory and the repository's own
 * `data/` folder — the same role the SOCIALBLOCKER_HOME / SOCIALBLOCKER_HOSTS
 * environment overrides play on the desktop.
 */
class App : Application() {

    lateinit var control: Control
        private set

    override fun onCreate() {
        super.onCreate()
        val catalog = Catalog(AssetListSource(this))
        val store = Store(filesDir, catalog)
        val engine = BlockEngine(catalog)
        val bridge = VpnBridge(this)
        control = Control(store, engine, catalog, bridge)
        Notifications.createChannels(this)
    }

    companion object {
        fun control(ctx: Context): Control =
            (ctx.applicationContext as App).control
    }
}

/** Reads the bundled lists out of the APK's assets. The Gradle script points
 *  the assets source set at the repository's `data/` folder, so these are
 *  literally the desktop tool's files — not a copy that drifts. */
class AssetListSource(private val ctx: Context) : ListSource {
    override fun read(name: String): String =
        ctx.assets.open(name).bufferedReader(Charsets.UTF_8).use { it.readText() }
}
