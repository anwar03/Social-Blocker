# SocialBlocker

A Linux desktop focus blocker built around one idea from the design discussion:
**the whitelist-vs-blacklist debate matters less than whether you can *stop*
your blocker on impulse.** So SocialBlocker gives you both modes *and* a locked
mode that can't be switched off mid-session.

## The philosophy (why it works this way)

| Mode | What it does | Good for | Weakness |
|------|--------------|----------|----------|
| **Blacklist** | Blocks ~5–10 core distractions (Facebook, YouTube, Instagram, Reddit…), rest of the internet stays open. | An all-day default. Low friction. | "Whack-a-mole" — your brain finds a *new* distraction (news, random blogs). |
| **Whitelist** | Blocks a curated universe of time-sinks *except* the work sites you allow. | 2–3h deep-work blocks. No route to distraction. | Friction — you may need to add a legit site mid-work. |
| **🔒 Locked** | A session that **cannot be stopped before its timer ends.** | People who impulsively uninstall/disable their blocker. | It really won't let you out. That's the point. |

**Recommended setup (the hybrid from the discussion):**
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
```

`--days` accepts `weekdays`, `weekend`, `all`, or a list like `mon,wed,fri`.

## GUI

```bash
sudo -E python3 -m socialblocker.gui
# on a desktop session you can also use pkexec:
#   pkexec env DISPLAY=$DISPLAY XAUTHORITY=$XAUTHORITY python3 -m socialblocker.gui
```

Pick the all-day mode, start a focus session (with a length, whitelist/blacklist,
and the Locked checkbox), and edit both lists live.

## Project layout

```
socialblocker/
  config.py        # paths, state model, mode resolution (session > schedule > default)
  hosts_engine.py  # translate effective mode -> /etc/hosts region
  control.py       # high-level ops + the one place locked-mode is enforced
  daemon.py        # re-apply loop (schedules, expiry, tamper repair)
  cli.py           # argparse CLI
  gui.py           # Tkinter GUI
data/
  blocklist.json         # default blacklist (categorised)
  whitelist.example.json # example focus-session allow-list
  universe.json          # the distraction set whitelist mode blocks-except-allow
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
