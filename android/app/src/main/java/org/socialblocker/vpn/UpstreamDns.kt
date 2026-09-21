package org.socialblocker.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import java.net.Inet4Address
import java.net.InetAddress

/**
 * Tracks the resolver the phone would have used if we were not in the way.
 *
 * A DNS sinkhole only sinks; every query it does *not* block has to be answered
 * by somebody, and silently substituting a public resolver of our choosing
 * would be a privacy decision taken on the user's behalf. So we follow the
 * underlying network's own DNS servers and only fall back when there are none.
 *
 * The callback is registered on a request that keeps the default NOT_VPN
 * capability, which is what stops us reading back our own tunnel's resolver and
 * building a loop.
 */
class UpstreamDns(private val ctx: Context) {

    @Volatile
    private var servers: List<InetAddress> = FALLBACK

    private val cm: ConnectivityManager =
        ctx.getSystemService(ConnectivityManager::class.java)

    private val callback = object : ConnectivityManager.NetworkCallback() {
        override fun onLinkPropertiesChanged(network: Network, lp: LinkProperties) {
            // IPv4 only: the tunnel advertises one IPv4 resolver, so a reply
            // has to come back over IPv4 to be wrapped in the packet we built.
            val v4 = lp.dnsServers.filterIsInstance<Inet4Address>()
            if (v4.isNotEmpty()) servers = v4
        }

        override fun onLost(network: Network) {
            servers = FALLBACK
        }
    }

    fun start() {
        val req = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        cm.registerNetworkCallback(req, callback)
    }

    fun stop() {
        runCatching { cm.unregisterNetworkCallback(callback) }
    }

    /** The resolver to forward an allowed query to. */
    fun primary(): InetAddress = servers.firstOrNull() ?: FALLBACK[0]

    companion object {
        /**
         * Used only when the network reports no resolver of its own (captive
         * portals and some tethered links do this). Quad9 and Cloudflare are
         * chosen because both publish a no-logging policy; neither ever sees a
         * query for a domain the user asked us to block, since those are
         * answered locally and never leave the phone.
         */
        private val FALLBACK: List<InetAddress> = listOf(
            InetAddress.getByAddress(byteArrayOf(9, 9, 9, 9)),
            InetAddress.getByAddress(byteArrayOf(1, 1, 1, 1)),
        )
    }
}
