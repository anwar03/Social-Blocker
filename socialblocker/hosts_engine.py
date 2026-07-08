"""Enforcement engine: translates the effective mode into /etc/hosts entries.

We keep a fenced region in /etc/hosts (between MARK_BEGIN/MARK_END) that we own
completely. Applying a mode rewrites only that region, so the rest of the file
is never touched.

    off        -> region empty
    blacklist  -> block state.blocklist
    whitelist  -> block (universe - state.whitelist)

/etc/hosts genuinely cannot express "allow only X", so whitelist mode blocks a
curated universe of common time-sinks minus your allow-list. See README.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from . import config
from .config import BLACKLIST, WHITELIST, OFF, HOSTS_FILE, MARK_BEGIN, MARK_END

SINK_IP = "127.0.0.1"
SINK_IP6 = "::1"


def _variants(domain: str) -> list[str]:
    """Base domain plus the common subdomains people actually hit."""
    domain = domain.strip().lower().lstrip(".")
    if not domain:
        return []
    out = {domain, f"www.{domain}"}
    # only add m.<domain> for a bare registrable domain (one dot)
    if domain.count(".") == 1:
        out.add(f"m.{domain}")
    return sorted(out)


def domains_for_mode(state: config.State, mode: str) -> list[str]:
    """The base domains to block for a given mode."""
    if mode == BLACKLIST:
        return sorted(set(state.blocklist))
    if mode == WHITELIST:
        allow = {d.strip().lower().lstrip(".") for d in state.whitelist}
        return sorted(d for d in config.universe() if d not in allow)
    return []  # OFF


def _render_block(domains: list[str], mode: str, locked: bool) -> str:
    lines = [MARK_BEGIN,
             f"# managed by SocialBlocker — mode={mode} locked={locked}",
             "# do not edit between these markers; use `socialblocker` instead"]
    for base in domains:
        for host in _variants(base):
            lines.append(f"{SINK_IP}\t{host}")
            lines.append(f"{SINK_IP6}\t{host}")
    lines.append(MARK_END)
    return "\n".join(lines) + "\n"


def _strip_existing(text: str) -> str:
    """Remove any existing SocialBlocker region from hosts text."""
    if MARK_BEGIN not in text:
        return text
    before, _, rest = text.partition(MARK_BEGIN)
    _, _, after = rest.partition(MARK_END)
    # tidy up stray blank lines at the seam
    return (before.rstrip("\n") + "\n" + after.lstrip("\n")).lstrip("\n")


def apply(state: config.State) -> tuple[str, bool, int]:
    """Write the effective mode into /etc/hosts. Returns (mode, locked, count)."""
    mode, locked = state.effective()
    domains = domains_for_mode(state, mode)

    original = HOSTS_FILE.read_text(encoding="utf-8") if HOSTS_FILE.exists() else ""
    base = _strip_existing(original)
    if not base.endswith("\n"):
        base += "\n"

    if mode == OFF:
        new_text = base  # nothing to add
    else:
        new_text = base + _render_block(domains, mode, locked)

    _atomic_write(HOSTS_FILE, new_text)
    _flush_dns_cache()
    return mode, locked, len(domains)


def clear() -> None:
    """Remove the SocialBlocker region entirely (used when turning off)."""
    if not HOSTS_FILE.exists():
        return
    text = HOSTS_FILE.read_text(encoding="utf-8")
    _atomic_write(HOSTS_FILE, _strip_existing(text))
    _flush_dns_cache()


def current_block() -> str | None:
    """Return the raw managed region, or None if not present."""
    if not HOSTS_FILE.exists():
        return None
    text = HOSTS_FILE.read_text(encoding="utf-8")
    if MARK_BEGIN not in text:
        return None
    _, _, rest = text.partition(MARK_BEGIN)
    body, _, _ = rest.partition(MARK_END)
    return (MARK_BEGIN + body + MARK_END).strip()


def _atomic_write(path: Path, text: str) -> None:
    """Write preserving ownership/permissions; atomic replace."""
    directory = path.parent
    fd, tmp = tempfile.mkstemp(dir=str(directory), prefix=".sb-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        if path.exists():
            st = path.stat()
            os.chmod(tmp, st.st_mode)
            try:
                os.chown(tmp, st.st_uid, st.st_gid)
            except PermissionError:
                pass
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _flush_dns_cache() -> None:
    """Best-effort DNS cache flush so changes take effect immediately."""
    for cmd in (
        ["resolvectl", "flush-caches"],
        ["systemd-resolve", "--flush-caches"],
    ):
        try:
            import subprocess
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
            return
        except (FileNotFoundError, OSError):
            continue
