#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Checking required system binaries"
for bin in ydotool ydotoold spectacle kscreen-doctor python3; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "Missing required command: $bin"
    echo "On CachyOS / Arch, install with: sudo pacman -S ydotool spectacle libkscreen"
    exit 1
  fi
done

echo "==> Creating Python virtual environment and installing dependencies"
python3 -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install --upgrade mcp pillow

echo "==> Installing systemd user override for ydotoold"
mkdir -p "$HOME/.config/systemd/user/ydotool.service.d"
cp "$REPO_DIR/config/ydotool-override.conf" \
   "$HOME/.config/systemd/user/ydotool.service.d/override.conf"
systemctl --user daemon-reload
systemctl --user enable --now ydotool.service

echo "==> Verifying ydotoold socket"
ls -la "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/.ydotool_socket"

echo ""
echo "Setup complete! To register in Antigravity, merge config/mcp_config.snippet.json"
echo "into ~/.gemini/config/mcp_config.json and run:"
echo "  $REPO_DIR/.venv/bin/python $REPO_DIR/scripts/verify.py"
