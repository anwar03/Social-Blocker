#!/usr/bin/env bash
# Install SocialBlocker to /opt/socialblocker, a `socialblocker` command, and
# (optionally) the enforcement daemon as a systemd service.
set -euo pipefail

PREFIX=/opt/socialblocker
BIN=/usr/local/bin/socialblocker
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Please run with sudo: sudo ./install.sh" >&2
  exit 1
fi

# --- Dependencies: Python 3 + Tkinter (for the GUI) ------------------------
ensure_deps() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "==> python3 not found — installing it too"
  fi
  if python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "==> Tkinter already present — GUI ready"
    return
  fi

  echo "==> Tkinter missing — installing it via your package manager"
  if   command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y python3 python3-tk
  elif command -v dnf     >/dev/null 2>&1; then
    dnf install -y python3 python3-tkinter
  elif command -v yum     >/dev/null 2>&1; then
    yum install -y python3 python3-tkinter
  elif command -v pacman  >/dev/null 2>&1; then
    pacman -Sy --noconfirm python tk
  elif command -v zypper  >/dev/null 2>&1; then
    zypper install -y python3 python3-tk
  elif command -v apk     >/dev/null 2>&1; then
    apk add python3 python3-tkinter
  else
    echo "!! Could not detect a package manager. Install Tkinter manually:" >&2
    echo "     Debian/Ubuntu: python3-tk   Fedora: python3-tkinter   Arch: tk" >&2
  fi

  if python3 -c "import tkinter" >/dev/null 2>&1; then
    echo "==> Tkinter installed — GUI ready"
  else
    echo "!! Tkinter still not importable; the CLI works, GUI won't until fixed." >&2
  fi
}

echo "==> Checking dependencies"
ensure_deps

echo "==> Installing to $PREFIX"
mkdir -p "$PREFIX"
cp -r "$SRC_DIR/socialblocker" "$SRC_DIR/data" "$PREFIX/"

echo "==> Creating $BIN"
cat > "$BIN" <<'EOF'
#!/usr/bin/env bash
exec /usr/bin/python3 -m socialblocker "$@"
EOF
chmod +x "$BIN"
# make the package importable from the launcher
sed -i "s#exec /usr/bin/python3 -m socialblocker#exec env PYTHONPATH=$PREFIX /usr/bin/python3 -m socialblocker#" "$BIN"

echo "==> Installing systemd service"
sed "s#/opt/socialblocker#$PREFIX#g" "$SRC_DIR/systemd/socialblocker.service" \
  > /etc/systemd/system/socialblocker.service
# ensure the daemon can import the package
sed -i "s#ExecStart=/usr/bin/python3#ExecStart=/usr/bin/env PYTHONPATH=$PREFIX /usr/bin/python3#" \
  /etc/systemd/system/socialblocker.service
systemctl daemon-reload

echo
echo "Installed. Quick start:"
echo "  socialblocker status"
echo "  socialblocker mode blacklist          # block distractions all day"
echo "  socialblocker focus 90 --locked       # 90-min locked whitelist focus"
echo
echo "Enable the always-on daemon (needed for schedules + locked-mode repair):"
echo "  sudo systemctl enable --now socialblocker"
