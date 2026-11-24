#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOCK_PATH="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/.ydotool_socket"

echo "==> Checking required system binaries"
for bin in ydotool ydotoold spectacle kscreen-doctor busctl python3; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "ERROR: Missing required command: $bin"
    if [[ "$bin" == "ydotoold" ]]; then
      echo "Please install ydotool 1.0.4+ (older 0.1.x distro packages do not include ydotoold)."
    fi
    echo "  Arch / CachyOS:  sudo pacman -S ydotool spectacle libkscreen"
    echo "  Fedora KDE:      sudo dnf install ydotool spectacle kscreen"
    echo "  Debian / Ubuntu: install ydotool 1.0.4+, spectacle, and kscreen"
    exit 1
  fi
done

if [[ ! -f /usr/include/linux/input-event-codes.h ]]; then
  echo "WARNING: /usr/include/linux/input-event-codes.h not found."
  echo "Named keys (e.g. 'Return', 'Ctrl+c') require Linux kernel headers:"
  echo "  Arch / CachyOS:  sudo pacman -S linux-api-headers"
  echo "  Fedora:          sudo dnf install kernel-headers"
  echo "  Debian / Ubuntu: sudo apt install linux-libc-dev"
fi

if [[ ! -w /dev/uinput ]]; then
  echo "WARNING: Current user cannot write to /dev/uinput."
  echo "Recommended (scoped to your active local seat via uaccess, no 'input' group needed):"
  echo "  echo 'KERNEL==\"uinput\", SUBSYSTEM==\"misc\", TAG+=\"uaccess\", OPTIONS+=\"static_node=uinput\"' | sudo tee /etc/udev/rules.d/80-uinput.rules"
  echo "  sudo udevadm control --reload-rules && sudo udevadm trigger /dev/uinput"
fi

echo "==> Creating Python virtual environment and installing dependencies"
python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install --upgrade -e "$REPO_DIR"

echo "==> Installing systemd user override for ydotoold"
mkdir -p "$HOME/.config/systemd/user/ydotool.service.d"
cp "$REPO_DIR/config/ydotool-override.conf" \
   "$HOME/.config/systemd/user/ydotool.service.d/override.conf"
systemctl --user daemon-reload
systemctl --user reenable ydotool.service
systemctl --user reset-failed ydotool.service 2>/dev/null || true
systemctl --user restart ydotool.service

echo "==> Verifying ydotoold socket"
for _ in $(seq 1 30); do
  [[ -S "$SOCK_PATH" ]] && break
  sleep 0.1
done
if [[ ! -S "$SOCK_PATH" ]]; then
  echo "ERROR: ydotoold socket did not appear at $SOCK_PATH"
  echo "Check service logs with: journalctl --user -u ydotool.service -n 20 --no-pager"
  exit 1
fi
ls -la "$SOCK_PATH"

echo ""
echo "Setup complete! To register in Antigravity, merge config/mcp_config.snippet.json"
echo "into ~/.gemini/config/mcp_config.json (updating paths and UID if needed) and run:"
echo "  $REPO_DIR/.venv/bin/python $REPO_DIR/scripts/verify.py"
