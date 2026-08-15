# SocialBlocker — Project Instructions

These instructions override default behavior. Follow them exactly.
SocialBlocker is a **Linux desktop focus blocker** (blacklist / whitelist /
locked focus sessions) written in **pure Python 3.9+ standard library**. It
enforces blocks by maintaining a fenced region in `/etc/hosts`, with a root
daemon that re-applies rules and repairs tampering during locked sessions.

---

## 1. Safety Rules (never violate)

### Never Read Secrets
Do **not** read `.env` or any secrets/credentials file — not even to
investigate. If a task needs an environment variable, or to check whether one
exists, **ask the user** instead of opening the file.

### This tool edits `/etc/hosts` as root — treat that as dangerous
- Never test against the real `/etc/hosts`. Always use the env overrides:
  `SOCIALBLOCKER_HOME` (state dir) and `SOCIALBLOCKER_HOSTS` (hosts file).
  Example: `export SOCIALBLOCKER_HOME=/tmp/sb SOCIALBLOCKER_HOSTS=/tmp/sb/hosts`.
- Only ever touch **inside the fenced region**. Never rewrite lines outside the
  begin/end markers — real system entries (localhost, other tools) live there.
- Writes to `/etc/hosts` and `state.json` must be **atomic** (write temp file,
  then `os.replace`) so a crash never leaves a half-written hosts file that
  could break DNS resolution for the whole machine.
- Least privilege: keep root-requiring code minimal and isolated; the daemon and
  hosts writes are the only things that need root.

---

## 2. Hard Constraints (do not break)

- **Zero pip dependencies.** Standard library only. Do **not** add any
  third-party package (no `requests`, `click`, `pydantic`, etc.). The GUI uses
  Tkinter, which is a *system* package, not pip. If you think a dependency is
  truly needed, **stop and ask** — this is a headline feature of the project.
- **Python 3.9+ compatible.** No syntax/APIs newer than 3.9 (e.g. no `match`
  statements, no `X | Y` type unions at runtime — use `typing.Optional` /
  `Union`; `str | None` in annotations is fine only with
  `from __future__ import annotations`).
- **Linux only.** `/etc/hosts` semantics, systemd, `sudo`. Don't add
  cross-platform abstractions that aren't asked for (YAGNI).
- **Honest limitations stay honest.** `/etc/hosts` can't express "allow only X",
  so whitelist mode blocks `data/universe.json` minus the allow-list. DNS-over-
  HTTPS bypasses `/etc/hosts`. Don't claim hardened security — this is a tool for
  a cooperative future-self, not an adversary with root.

---

## 3. Workflow: Plan Before Execute

For **every code change**, always explain the **What / Why / How**.
Non-negotiable. What differs is timing and whether you wait:

- **Logical / substantive tasks** — real design decisions, non-trivial logic,
  multiple files, behavior changes, or anything touching locked-mode enforcement,
  the hosts engine, or root/daemon code.
  → Present the What/Why/How **first** and **wait for approval** before editing.

- **Trivial / mechanical changes** — docs/README/CHANGELOG/comments, renames,
  formatting, typos, obvious single-file edits, or anything already described
  precisely.
  → **Do it directly**, but still give the What/Why/How.

When in doubt, lean toward doing it; only stop when there's a genuine decision
the user should weigh in on. Pure questions and read-only investigation are
always answered directly.

**The plan:** 1) **Check** existing code → 2) **Present** What (changes) / Why
(reason per change) / How (one clear approach; only if multiple valid ways,
show trade-offs and **recommend** the best for this task) → 3) **Wait for
approval** before changing anything substantive.

---

## 4. After Execution: Record the Changes

1. **CHANGELOG.md** — append an entry for every completed change:
   *date — what changed — why*. Newest first. The primary human-readable
   history (create the file if missing).
2. **Memory** — save only non-obvious decisions and the *why* that can't be read
   from the code, plus ongoing goals/constraints. Keep it clean.

Git commits are optional — commit only when the user asks.

---

## 5. Architecture (Clean Architecture — respect the layering)

Clean Architecture's **dependency rule is absolute: inner layers never import
from outer layers.** This project already satisfies it. It expresses the rule as
a **flat package of modules**, not as `core/application` + `core/services`
folders — five modules and ~1800 lines do not need a directory per circle, and
inventing one would violate the YAGNI rule in §2. The circles below are the
layers; the module names are the contract. **Do not rename them to generic
Clean-Architecture folder names.**

```
socialblocker/
  config.py        # INNER: paths, state model (dataclasses), mode resolution
                   #        (session > schedule > default). Imports nothing internal.
  hosts_engine.py  # INNER: translate the effective mode -> the /etc/hosts fenced region
  control.py       # INNER: use cases; THE ONE PLACE locked-mode is enforced
  autostart.py     # OUTER adapter: XDG .desktop entry in ~/.config/autostart
  daemon.py        # OUTER: re-apply loop (schedules, session expiry, tamper repair)
  cli.py           # OUTER: argparse CLI          -- delivery mechanism
  gui.py           # OUTER: Tkinter GUI + pkexec  -- delivery mechanism
systemd/, install.sh  # OUTER: deployment (this project's "iac")
data/
  blocklist.json          # default blacklist (categorised)
  whitelist.example.json  # example focus-session allow-list
  universe.json           # the distraction set whitelist mode blocks-except-allow
```

**The dependency rule, concretely.** Imports may only point *inward*:

```
cli.py / gui.py / daemon.py  ->  control.py  ->  hosts_engine.py  ->  config.py
```

`config.py` is the innermost circle and must keep importing **nothing** from
this package. No inner module may import `cli`, `gui`, or `daemon` — a use case
that needs to talk to the user returns a value or raises; it never prints.

**Where the Clean Architecture vocabulary lands here** (use these names, not the
generic ones):

| Clean Architecture term      | This project                                       |
| ---------------------------- | -------------------------------------------------- |
| Entities / shared DTOs       | `config.py` dataclasses (`State`, `Session`, `Autostart`) |
| Use-case services            | functions in `control.py`                          |
| Workflow-specific error      | `control.LockedError`                              |
| Interface adapter            | `hosts_engine.py` (policy -> hosts text), `autostart.py` |
| Frameworks & drivers         | `cli.py`, `gui.py`, `daemon.py`, Tkinter, systemd, pkexec |
| Dependency-inversion seam    | `SOCIALBLOCKER_HOME` / `SOCIALBLOCKER_HOSTS` env overrides |

That last row matters: the env overrides are how tests substitute the real
`/etc/hosts` without root. They are this codebase's port. **Do not bypass them
by hard-coding a path** — that is what "depend on abstractions" means here.

Rules that keep this clean:
- **`config.py` owns state and mode resolution.** Effective mode precedence is
  always **session > schedule > default** — never re-implement this elsewhere.
- **`hosts_engine.py` is the only module that formats `/etc/hosts` content.**
  `cli.py` and `gui.py` must not build hosts lines themselves.
- **`control.py` is the single choke point for locked-mode enforcement.** Any
  operation that could stop/shorten a session (`stop`, mode switch) checks the
  lock here — do not scatter that check into `cli.py`, `gui.py`, or `daemon.py`.
  `extend` is allowed while locked; `stop` is refused.
- **`cli.py` and `gui.py` are thin.** They parse input and call `control.py`;
  no business logic lives in them. Both front-ends must reach feature parity
  through the same `control.py` functions.
- **`daemon.py` only re-applies** — it reads state and calls the engine; it does
  not make policy decisions of its own.
- **Known violation — do not copy it.** `control.py` imports `autostart.py`,
  which is an outer adapter (it touches `pwd`, `chown`, `~/.config`). That is an
  inner circle reaching outward. If autostart grows, invert it: `control.py`
  takes the enable/disable callable as a parameter, and `cli.py` / `gui.py`
  supply `autostart`'s implementation.

**Adding a new use case:**
1. State/config changes (if any) go in `config.py` first.
2. The use-case function goes in `control.py` — it enforces the lock and calls
   `hosts_engine.py`; it never formats hosts lines or prints.
3. Wire it into **both** `cli.py` and `gui.py` (§5 requires feature parity), each
   a thin call-through.
4. If it needs new infrastructure (a file, a service, a desktop entry), put that
   in its own adapter module beside `autostart.py` and pass it inward — do not
   let `config.py` or `hosts_engine.py` import it.

---

## 6. Code Style

- Match the existing style: standard-library idioms, clear names, docstrings on
  modules and public functions (the codebase already does this).
- Functions small and single-purpose; prefer readable over clever.
- Use `pathlib.Path` for paths, `json` for state, `argparse` for the CLI,
  `typing` for annotations. Prefer `dataclasses` for structured state.
- **Errors:** raise clear, specific exceptions with actionable messages. A
  root/`/etc/hosts` permission failure should tell the user to run with `sudo`,
  not dump a raw traceback. Never fail silently on a hosts write.
- **Errors, cont.:** prefer purpose-specific exception classes (like the existing
  `control.LockedError`) over bare `ValueError` / `RuntimeError` for anything a
  front-end has to *react* to differently. Keep them in one place so `cli.py` and
  `gui.py` catch the same types; bare built-ins are fine for plain input
  validation that both front-ends just print.
- **Idempotency:** re-applying the same mode must produce the same hosts region
  (the daemon runs every few seconds — no duplicated lines, no drift).
- **Observability:** the daemon should log what it re-applies / repairs so a user
  can answer "why is this site blocked right now?".

### Clean Code limits

- Functions ≤ 25 lines (prefer ≤ 10); classes ≤ 250 lines (prefer ≤ 150) —
  but never at the cost of readability.
- Names must express intent; every code block should make its purpose obvious.
- Follow SOLID principles. Apply design patterns where they help, not where
  they hurt manageability — the layering in §5 is the main one that matters here.

---

## 7. Testing

- No test suite exists yet. When adding tests, use the standard-library
  **`unittest`** (or `pytest` only if the user approves it as a dev-only tool)
  in a `tests/` folder.
- Tests **must** use `SOCIALBLOCKER_HOME` / `SOCIALBLOCKER_HOSTS` to run without
  root and never touch the real `/etc/hosts`.
- Prioritise the risky logic: mode resolution (precedence), the hosts-engine
  fenced-region generation (idempotency, don't-touch-outside-fence), and
  locked-mode enforcement in `control.py`.

---

## 8. Commands (run from repo root)

```bash
# Run without installing (needs root for the real hosts file):
sudo ./socialblocker.py status
python3 -m socialblocker mode blacklist        # module form

# Safe local testing (no root, throwaway hosts file):
export SOCIALBLOCKER_HOME=/tmp/sb SOCIALBLOCKER_HOSTS=/tmp/sb/hosts
mkdir -p /tmp/sb && printf '127.0.0.1\tlocalhost\n' > /tmp/sb/hosts
python3 -m socialblocker mode blacklist && cat /tmp/sb/hosts

# Install (enables the always-on daemon):
sudo ./install.sh
sudo systemctl enable --now socialblocker
```
