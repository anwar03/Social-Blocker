package org.socialblocker.platform

import android.content.Context
import android.net.VpnService
import org.socialblocker.core.Enforcer
import org.socialblocker.core.RuleSet
import org.socialblocker.vpn.BlockerVpnService

/**
 * The outer half of the `Enforcer` port.
 *
 * `Control` says "these are the rules now" and this decides what that means to
 * a running Android service. Pushing a new rule set is deliberately cheap —
 * the sinkhole holds it as a plain immutable value, so a mode change does not
 * tear down the tunnel and does not interrupt a single connection. The desktop
 * has to rewrite /etc/hosts and flush the resolver cache to do the same thing.
 */
class VpnBridge(private val ctx: Context) : Enforcer {

    override fun apply(rules: RuleSet) {
        if (BlockerVpnService.isRunning()) {
            BlockerVpnService.push(rules)
            return
        }
        // Not running, but something now needs enforcing. If the user has
        // already granted VPN consent we can start without an Activity;
        // otherwise the UI has to ask, and it will.
        if (rules.count > 0 && VpnService.prepare(ctx) == null) {
            BlockerVpnService.start(ctx)
        }
    }
}
