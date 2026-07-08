# Contributing to SocialBlocker

Thanks for your interest in improving SocialBlocker! This is a small, dependency-free
Python project, so getting started is quick.

## Ground rules

- **Standard library only.** No pip/runtime dependencies — the GUI uses Tkinter,
  everything else is stdlib. Please keep it that way.
- **Cross-distro.** Anything touching packages or system paths should work on the
  common families (apt / dnf / pacman / zypper / apk).
- **Be honest about limits.** SocialBlocker is a focus tool for a cooperative
  future-you, not hardened security. Don't oversell enforcement (e.g. DoH bypass
  and root-user edits are real limits — keep them documented).

## Dev setup

You do **not** need root — point the app at a fake hosts file and config dir:

```bash
git clone https://github.com/<you>/SocialBlocker
cd SocialBlocker

export SOCIALBLOCKER_HOME=/tmp/sb
export SOCIALBLOCKER_HOSTS=/tmp/sb/hosts
mkdir -p /tmp/sb && printf '127.0.0.1\tlocalhost\n' > /tmp/sb/hosts

python3 -m socialblocker status
python3 -m socialblocker mode blacklist && cat /tmp/sb/hosts
```

For the GUI you need Tkinter (`sudo apt install python3-tk` or run `./install.sh`).

## Before you open a PR

- `python3 -m py_compile socialblocker/*.py` — must pass.
- `bash -n install.sh` — must pass if you touched the installer.
- Exercise the paths you changed against the fake hosts file above (see the
  test flows in the README's "Configuration & state" section).
- Match the surrounding style: standard library, clear names, comments only
  where intent isn't obvious.

## Good first contributions

- Expand `data/blocklist.json` / `data/universe.json` with more common time-sinks.
- Additional package managers or edge cases in `install.sh`.
- A password/PIN lock, usage stats, or a Pomodoro cycle mode.
- A `.desktop` launcher and app icon for the GUI.

## Reporting bugs

Open an issue with your distro, Python version, whether the daemon is running,
and the relevant `socialblocker status` output. Never paste real credentials.

## License

By contributing, you agree your work is licensed under the project's
[MIT License](LICENSE).
