# kde-wayland-mcp

Minimal, pure-Wayland KDE Plasma desktop automation MCP server (zero X11 / zero `xdotool`).

## Architecture

- **Display geometry**: `kscreen-doctor -j` (logical screen size, monitor positions, fractional scaling)
- **Screenshots**: `spectacle -f -b -n --scaled -o <tmp.png>` (matches logical coordinates 1:1 by default)
- **Input injection**: `ydotool` + `ydotoold` over `/dev/uinput` with socket at `$XDG_RUNTIME_DIR/.ydotool_socket`

### Key KDE Plasma / Wayland Fixes Built In

1. **Flat pointer acceleration on `ydotoold virtual device`**: KWin defaults virtual pointers to Adaptive acceleration (~2x overshoot). `server.py` enforces `pointerAccelerationProfileFlat = true` via KWin D-Bus (`org.kde.KWin /org/kde/KWin/InputDevice/*`), which KWin persists in `~/.config/kcminputrc` only for `ydotoold virtual device`.
2. **Reliable absolute movement on `ydotool 1.0.4`**: Single-shot `ydotool mousemove -a -x X -y Y` emits `(-2147483648, -2147483648)` and `(+X, +Y)` with 0 ms delay, which KWin frequently drops back to `(0, 0)`. `server.py` splits reset (`mousemove -a -x 0 -y 0`), a 15 ms settle, and relative offset (`mousemove -x X -y Y`) for 1-pixel logical accuracy.

## MCP Tools

| Tool | Description |
| :--- | :--- |
| `screen_info()` | Logical/physical monitor resolution, positions, refresh rate, and scaling. |
| `screenshot(include_pointer=False, native_resolution=False)` | Silent PNG capture + JSON resolution metadata (`--scaled` by default for 1:1 coordinates). |
| `mouse_move(x, y)` | Move pointer to exact logical `(x, y)` coordinates. |
| `click(x=None, y=None, button="left", count=1)` | Click at `(x, y)` or current pointer (`left`, `right`, `middle`; `count=2` for double-click). |
| `scroll(dy, dx=0)` | Relative mouse wheel scroll (`dy > 0` up, `dy < 0` down). |
| `type_text(text, key_delay_ms=12)` | Type literal UTF-8/ASCII text safely via `ydotool type --file -`. |
| `key(keys, key_delay_ms=12)` | Key names (`Return`, `Escape`, `F5`), chords (`Ctrl+c`, `Alt+Tab`, `Super+d`), or raw `keycode:1 keycode:0` sequences. |

## Files on This Machine

- **Repository**: `~/projects/kde-wayland-mcp/`
- **Systemd user override**: `~/.config/systemd/user/ydotool.service.d/override.conf` (template in `config/ydotool-override.conf`)
- **KWin virtual mouse profile**: `~/.config/kcminputrc` (`[Libinput][9011][26214][ydotoold virtual device]`)
- **Antigravity MCP config**: `~/.gemini/config/mcp_config.json` (snippet in `config/mcp_config.snippet.json`)

## Setup & Verification

```bash
# Re-apply setup on a fresh machine:
./scripts/install.sh

# Check ydotoold daemon status:
systemctl --user status ydotool.service

# Run non-destructive end-to-end verification:
.venv/bin/python scripts/verify.py
```

## License

Licensed under the [GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)](LICENSE).

## Pushing to a Remote (Optional)

```bash
cd ~/projects/kde-wayland-mcp
git remote add origin <your-git-repo-url>
git push -u origin main
```
