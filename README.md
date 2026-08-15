# SocialBlocker

> A Linux desktop focus blocker with blacklist, whitelist, and locked focus
> sessions you can't quit on impulse.

![platform](https://img.shields.io/badge/platform-Linux-blue)
![python](https://img.shields.io/badge/python-3.9%2B-green)
![deps](https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

SocialBlocker is built on one insight: **the whitelist-vs-blacklist debate
matters less than whether you can *stop* your blocker on impulse.** So it gives
you both modes *and* a locked mode that can't be switched off mid-session.

## Features

- 🚫 **Blacklist** — block a handful of core distractions all day, rest of the web open.
- 🎯 **Whitelist** — during focus sessions, allow only your work sites; block everything else.
- 🔒 **Locked sessions** — timed focus blocks that can't be stopped early; a root daemon even repairs the block if you delete it.
- ⏰ **Schedules** — auto-switch modes by time of day and weekday.
- 🔌 **Starts with your computer** — boot straight into a block (300 min by default), switchable off from the UI.
- 🖥️ **CLI + GUI** — argparse command line and a Tkinter desktop app.
- 🐍 **Zero pip dependencies** — pure Python standard library; `sudo ./install.sh` sets up everything (including Tkinter).

## The philosophy (why it works this way)

| Mode | What it does | Good for | Weakness |
|------|--------------|----------|----------|
| **Blacklist** | Blocks ~5–10 core distractions (Facebook, YouTube, Instagram, Reddit…), rest of the internet stays open. | An all-day default. Low friction. | "Whack-a-mole" — your brain finds a *new* distraction (news, random blogs). |
| **Whitelist** | Blocks a curated universe of time-sinks *except* the work sites you allow. | 2–3h deep-work blocks. No route to distraction. | Friction — you may need to add a legit site mid-work. |
| **🔒 Locked** | A session that **cannot be stopped before its timer ends.** | People who impulsively uninstall/disable their blocker. | It really won't let you out. That's the point. |

**Recommended setup (the hybrid approach):**
- Blacklist as the all-day default — social media always off.
- Whitelist during focus sessions — only your work sites reachable.
- Turn on **Locked** for the sessions that matter.

## How enforcement works

SocialBlocker maintains a fenced region in `/etc/hosts`, mapping blocked domains
to `127.0.0.1` / `::1`. A small root daemon re-applies the correct rules every
few seconds, so:

- schedules and session expiry take effect automatically, and
- if you delete the block during a **locked** session, it comes straight back.

> **Honest limitations.** `/etc/hosts` cannot express "allow only X", so
> whitelist mode blocks a bundled *universe* of common distractions
> (`data/universe.json`) minus your allow-list — extend that file to taste. Also,
> a browser using **DNS-over-HTTPS** bypasses `/etc/hosts` entirely; disable DoH
> in your browser for reliable blocking. This is a focus tool for a cooperative
> future-you, not hardened security against a determined attacker with root.

## Requirements

- Linux, Python 3.9+ (standard library only — Tkinter for the GUI).
- `sudo`/root to edit `/etc/hosts`.

`./install.sh` **auto-installs Python 3 + Tkinter** for you (apt / dnf / yum /
pacman / zypper / apk), so a single `sudo ./install.sh` sets up everything —
you don't need to install `python3-tk` by hand.

## Quick start (no install)

```bash
sudo ./socialblocker.py status
sudo ./socialblocker.py mode blacklist          # block distractions all day
sudo ./socialblocker.py focus 90 --whitelist --locked   # 90-min locked deep work
sudo ./socialblocker.py gui                      # desktop GUI
```

## Install (recommended — enables the always-on daemon)

```bash
sudo ./install.sh
socialblocker status
sudo systemctl enable --now socialblocker        # schedules + locked-mode repair
```

### Upgrading

`install.sh` copies the code to `/opt/socialblocker`, and the daemon runs *that*
copy — editing or pulling into your checkout changes nothing until you reinstall
and restart:

```bash
sudo ./install.sh && sudo systemctl restart socialblocker
socialblocker status                             # confirm the new build is live
```

## CLI reference

```bash
socialblocker status                     # what's enforced right now
socialblocker mode blacklist|whitelist|off   # the all-day default

socialblocker focus <minutes> [--whitelist|--blacklist] [--locked]
socialblocker extend <minutes>           # allowed even while locked
socialblocker stop                       # refused while a locked session runs

socialblocker block  add|remove <domain>...   # edit the blacklist
socialblocker allow  add|remove <domain>...   # edit the whitelist
socialblocker list   block|allow

socialblocker schedule --start 09:00 --end 12:00 \
    --days weekdays --whitelist --locked  # recurring auto-switch
socialblocker refresh                    # re-apply (the daemon does this for you)

socialblocker autostart                  # status of all three switches below
socialblocker gui                        # open the desktop app
```

`--days` accepts `weekdays`, `weekend`, `all`, or a list like `mon,wed,fri`.

## Start with the computer

Three independent switches — the first does nothing without the second:

```bash
sudo socialblocker autostart --session on --minutes 300 --blacklist
sudo socialblocker autostart --service on    # run the daemon at boot (systemd)
socialblocker autostart --gui on             # open the app at login (no sudo)
sudo socialblocker autostart --session off   # stop blocking at boot
```

| Switch | Mechanism | Job |
|--------|-----------|-----|
| `--session` | flag in `state.json` | arm a block on every boot |
| `--service` | systemd unit | run the daemon that arms it, before login |
| `--gui` | `~/.config/autostart/*.desktop` | open the window at login so you can switch it off |

`--gui` writes a normal XDG entry, so it shows up in GNOME's **Startup
Applications** list and you can untick or remove it there.

The block is armed **once per boot**, keyed on the kernel's boot id: stop it in
the UI and it stays stopped, even if the daemon restarts. It comes back at the
next real reboot. It is unlocked by default — add `--locked` and you genuinely
cannot stop it until the timer runs out. A boot block is not counted as focus
time, so it never inflates your streak.

> **Switching it on takes effect from your next boot, not immediately.** Turning
> it on marks the current boot as already handled — otherwise any daemon restart
> later today would spring a 5-hour block you never asked for.

> Stopping the boot block returns you to your **all-day default mode**, which
> ships as `blacklist`. Press **Off** if you want everything unblocked.

## GUI

```bash
socialblocker gui        # as your normal user — no sudo
```

Pick the all-day mode, start a focus session (with a length, whitelist/blacklist,
and the Locked checkbox), configure the boot block, and edit both lists live.

The window runs unprivileged: it reads state directly, and each change elevates
a single `socialblocker` CLI command through **pkexec**, so you get one password
prompt per change and no long-running root GUI. `sudo -E socialblocker gui`
still works and skips pkexec entirely.

## Project layout

```
socialblocker/
  config.py        # paths, state model, mode resolution (session > schedule > default)
  hosts_engine.py  # translate effective mode -> /etc/hosts region
  control.py       # high-level ops + the one place locked-mode is enforced
  daemon.py        # re-apply loop (schedules, expiry, tamper repair, boot arming)
  autostart.py     # the ~/.config/autostart .desktop entry (login, user-level)
  cli.py           # argparse CLI
  gui.py           # Tkinter GUI
data/
  blocklist.json         # default blacklist (categorised)
  whitelist.example.json # example focus-session allow-list
  universe.json          # the distraction set whitelist mode blocks-except-allow
  presets.json           # quick-start focus presets
systemd/socialblocker.service
install.sh
```

## Configuration & state

Live state (current mode, session, lists, schedules) is stored as JSON at
`/etc/socialblocker/state.json`. Override the location with `SOCIALBLOCKER_HOME`
and the hosts path with `SOCIALBLOCKER_HOSTS` — handy for testing without root:

```bash
export SOCIALBLOCKER_HOME=/tmp/sb SOCIALBLOCKER_HOSTS=/tmp/sb/hosts
mkdir -p /tmp/sb && printf '127.0.0.1\tlocalhost\n' > /tmp/sb/hosts
python3 -m socialblocker mode blacklist && cat /tmp/sb/hosts
```
