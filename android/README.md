# SocialBlocker for Android

The mobile sibling of the Linux desktop tool. Same modes, same focus sessions,
same locked sessions, same schedules, same stats — **the same `data/*.json`
lists**, read straight out of this repo at build time.

The desktop enforces blocks by owning a fenced region in `/etc/hosts`. A phone
has no writable hosts file, so Android's enforcement point is a **local
`VpnService` that answers DNS itself**. Blocked name → `0.0.0.0`; everything
else is forwarded to the real resolver untouched. No root, no Play Services, no
third-party library.

---

## Build

There is **no Gradle wrapper jar** committed (a binary blob in a zero-dependency
repo is exactly the supply-chain surface this project avoids). Generate one
once, or just use Android Studio.

```bash
# Option A — Android Studio: File > Open > select the android/ folder. Done.

# Option B — command line (needs a JDK 17 and a system Gradle 8.7+ once):
cd android
gradle wrapper --gradle-version 8.7     # writes gradlew + the wrapper jar, once
./gradlew test                          # JVM unit tests, no device needed
./gradlew assembleDebug                 # app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Requirements: JDK 17, Android SDK platform 34, build-tools 34. `minSdk 26`
(Android 8.0) — chosen so `java.time.LocalDate.toEpochDay()` is available
without desugaring; it is the exact analogue of the desktop's
`date.toordinal()` that the focus streak counts on.

**Dependencies: none at runtime.** No AndroidX, no Compose, no Material
library. The UI is built from `android.widget` views in Kotlin — no XML
layouts. JUnit and `org.json` are test-only.

---

## How enforcement works

```
app / browser
   │  DNS query to 10.111.222.2:53
   ▼
tun interface  ──►  BlockerVpnService.sinkholeLoop
                      │
                      ├── name matches a rule  ──►  synthesised answer: A 0.0.0.0
                      └── otherwise            ──►  forwarded to the system resolver
```

**Only DNS is routed into the tunnel.** The service advertises a fake resolver
at `10.111.222.2` and `addRoute`s that single `/32`. Everything else — every TCP
byte, every video stream — stays on the normal path at full speed and never
enters our process. The alternative (claim `0.0.0.0/0`) would mean writing a
userspace TCP/IP stack and forwarding the phone's entire traffic through
Kotlin. This is the same trade the desktop makes: intercept *name resolution*,
not packets.

**Matching is by domain suffix**, so one entry (`instagram.com`) covers
`www.instagram.com`, `i.instagram.com`, `graph.instagram.com` — which is why
the **app** is blocked, not only the website. Cost is O(labels in the query),
not O(rules), so the list can grow without slowing lookups. The desktop cannot
do this: a hosts file has no wildcards, so it enumerates `www.` and `m.`
variants instead.

**Blocked answer is `A 0.0.0.0` with a 60 s TTL, or an empty NOERROR** for
anything that is not an A record. Not NXDOMAIN — apps treat NXDOMAIN as a
network fault and retry in a tight loop, which burns battery and looks like a
bug rather than a block.

---

## Architecture

The desktop's dependency rule is preserved exactly. Imports point inward only:

```
ui/ · vpn/ · platform/   ──►   core/Control.kt   ──►   core/BlockEngine.kt   ──►   core/Config.kt
```

| Desktop                    | Android                                            |
| -------------------------- | -------------------------------------------------- |
| `config.py`                | `core/Config.kt` — entities, mode resolution, atomic state save |
| `hosts_engine.py`          | `core/BlockEngine.kt` — policy → `RuleSet`         |
| `control.py`               | `core/Control.kt` — use cases, the one lock check  |
| `control.LockedError`      | `core.LockedError`                                 |
| `daemon.py` 5 s loop       | `vpn/BlockerVpnService.policyLoop`                 |
| `cli.py` / `gui.py`        | `ui/MainActivity` + `ui/BlockerTileService` (quick-settings tile) |
| `autostart.py`             | `platform/Boot.kt`                                 |
| `SOCIALBLOCKER_HOME/HOSTS` | `ListSource` and `Enforcer` interfaces             |

`core/` contains **no Android imports at all** — that is what makes the whole
policy layer testable as plain JVM unit tests (`./gradlew test`, no emulator).
`Config.kt` imports nothing from this package, same as its Python counterpart.

The state file lives at `filesDir/state.json` and uses the **same JSON keys as
the desktop** (`ends_at`, `last_boot_id`, `focus_log`, …).

---

## Feature parity

| Feature                    | Desktop | Android |
| -------------------------- | ------- | ------- |
| off / blacklist / whitelist | ✅ | ✅ |
| Focus session with duration | ✅ | ✅ |
| **Locked** session (cannot stop, can extend) | ✅ | ✅ |
| Weekly schedule rules       | ✅ | ✅ |
| Arm a block at boot, once per boot | ✅ | ✅ |
| Focus log, minutes today, streak | ✅ | ✅ |
| Presets                     | ✅ | ✅ |
| Edit blocklist / whitelist  | ✅ | ✅ |
| Re-apply loop + tamper repair | daemon, 5 s | foreground service, 5 s |
| Second front-end            | CLI | quick-settings tile |

---

## Honest limitations

The desktop README's honesty section applies here too, plus what is specific to
a phone. This is a tool for a cooperative future-self, not a countermeasure
against someone with your unlock code.

- **DNS-over-HTTPS and Private DNS bypass it.** Chrome's Secure DNS and
  Android's Settings → Network → Private DNS send queries over HTTPS/TLS to a
  resolver of their own, which never reaches our sinkhole. Turn Private DNS to
  **Automatic/Off** and disable Secure DNS in the browser, or the block is
  advisory. Same class of hole as DoH on the desktop.
- **Hard-coded IPs bypass it.** Anything that skips name resolution is invisible
  to a DNS filter, on either platform.
- **"Allow only X" is still inexpressible.** Whitelist mode blocks
  `data/universe.json` minus your allow-list — a curated set of time-sinks, not
  the whole internet. Identical compromise to the desktop.
- **The user can revoke the VPN.** Settings → VPN → disconnect, or Force Stop,
  ends enforcement. `onRevoke()` retries once silently during a locked session
  and then raises a high-priority notification; it does not fight the OS.
  The system-enforced version is **Always-on VPN**, below.
- **A device reboot loses a running session's remainder** unless autostart is
  enabled — the boot token is derived per boot, deliberately, so a crash-restart
  cannot re-arm a block you already stopped.
- **One VPN slot per device.** Android allows exactly one active VPN, so this
  cannot run alongside a work VPN or a WireGuard tunnel.

## Making it stick: Always-on VPN

This is the only genuinely hard-to-undo setting, and it is the OS enforcing it,
not us:

1. Start protection once in the app so Android records the consent.
2. Settings → Network & internet → VPN → ⚙ next to **SocialBlocker**.
3. Enable **Always-on VPN**, then **Block connections without VPN**.

With both on, the phone has no network path at all when the service is not
running — turning the blocker off costs you the internet, which is the point.
Undoing it is three taps, so it works by raising friction, not by being
impossible. Setting it *while sober* is the whole trick.
