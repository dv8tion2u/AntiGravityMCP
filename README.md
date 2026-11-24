# AntiGravityMCP (`kde-wayland-mcp`)

A minimal, pure-Wayland desktop automation MCP server for **KDE Plasma**.  
Zero X11, zero XWayland hacks, zero heavy automation frameworks—just a single ~20 KB `server.py` wiring together the native primitives Linux and KDE already ship.

## Why This Exists

Most Linux desktop-automation tools rely on X11 (`xdotool`), break under fractional scaling, or drag in massive dependency trees. `kde-wayland-mcp` works straight at the compositor and kernel input layers:

- **Bare-Metal Input:** Injects mouse and keyboard events directly through `/dev/uinput` via `ydotoold`, locked down to `0600` on your user runtime socket (`$XDG_RUNTIME_DIR/.ydotool_socket`) with zero `sudo` at runtime.
- **1:1 Pointer Accuracy:** Pins `pointerAccelerationProfileFlat = true` specifically on `ydotoold virtual device` via KWin's D-Bus (`org.kde.KWin.InputDevice`), leaving your physical mouse acceleration untouched.
- **Fractional-Scaling Parity:** Pairs `kscreen-doctor -j` geometry with `spectacle --scaled` captures so screenshot pixels match logical pointer coordinates 1:1.
- **App-Agnostic:** Drives native Qt/GTK apps, browsers, terminals, and proprietary GUIs identically without fragile accessibility trees.
- **User-Controlled Permissions:** `server.py` stays a thin, auditable bridge while your MCP host prompts you per tool on first run (e.g., auto-approving read-only screenshots while gating clicks and keystrokes).

### Key KDE Plasma / Wayland Fixes Built In

1. **Flat acceleration scoped to the virtual pointer:** KWin defaults virtual pointers to Adaptive acceleration (~2× overshoot). `server.py` enforces `pointerAccelerationProfileFlat = true` on `ydotoold virtual device` via KWin D-Bus and tracks the socket inode/mtime so it self-heals across daemon restarts.
2. **Reliable absolute positioning on `ydotool 1.0.4`:** Single-shot `ydotool mousemove -a -x X -y Y` emits `(-2147483648, -2147483648)` and `(+X, +Y)` with 0 ms delay, which KWin frequently coalesces back to `(0, 0)`. `server.py` splits the reset (`mousemove -a -x 0 -y 0`), a tuned 15 ms settle window, and the relative offset (`mousemove -x X -y Y`) for exact logical positioning without triggering top-left hot corners.
3. **Cold-boot `uaccess` race protection:** `config/ydotool-override.conf` binds `ydotool.service` to `graphical-session.target` with `RestartSec=2` so `ydotoold` waits for `systemd-logind` to apply the active seat's `/dev/uinput` ACL instead of burning through restarts at login.

## What's Inside (~65 KB Total)

Yes, you really did clone the whole project—no missing binaries or hidden submodules:

```text
server.py                      # ~19 KB — entire pure-Wayland MCP server (7 tools)
config/ydotool-override.conf   # 0600 user socket + graphical-session.target systemd drop-in
config/mcp_config.snippet.json # Ready-to-merge MCP client config snippet
scripts/install.sh             # Multi-distro venv, systemd override, and /dev/uinput check
scripts/verify.py              # Tier 0 non-destructive smoke & MCP stdio handshake test
scripts/test_target.html       # Self-contained 13-point live visual verification arena (+ docs/TESTING.md)
```

## MCP Tools

| Tool | Description |
| :--- | :--- |
| `screen_info()` | Logical/physical monitor resolution, positions, refresh rate, and scaling via `kscreen-doctor -j`. |
| `screenshot(include_pointer=False, native_resolution=False)` | Silent PNG capture + JSON resolution metadata (`--scaled` by default for 1:1 logical coordinates). |
| `mouse_move(x, y)` | Move pointer to exact logical `(x, y)` coordinates. |
| `click(x=None, y=None, button="left", count=1)` | Click at `(x, y)` or current pointer (`left`, `right`, `middle`; `count=2` for double-click). |
| `scroll(dy, dx=0)` | Relative mouse wheel scroll (`dy > 0` up, `dy < 0` down). |
| `type_text(text, key_delay_ms=12)` | Type literal printable ASCII text safely via `ydotool type --file -` (dynamic timeout scaling for long strings). |
| `key(keys, key_delay_ms=12)` | Key names (`Return`, `Escape`, `F5`), chords (`Ctrl+c`, `Alt+Tab`, `Super+d`), or raw `keycode:1 keycode:0` sequences. |

### Optional Environment Tuning

- `YDOTOOL_SOCKET` — Override socket path (defaults to `$XDG_RUNTIME_DIR/.ydotool_socket`).
- `KDE_MCP_MOVE_SETTLE_MS` — Settle delay in ms between absolute reset and relative offset (default: `15`).
- `KDE_MCP_CLICK_SETTLE_MS` — Settle delay in ms between move and click (default: `20`).

## Requirements

- **Desktop:** KDE Plasma on Wayland (built and daily-driven on CachyOS/Arch; compatible with Fedora KDE, openSUSE, and Debian/Kubuntu).
- **Python:** `3.12+` (`mcp>=2.0.0`, `pillow>=11.0.0`).
- **System tools:** `ydotool` (`1.0.4+` with `ydotoold`), `kscreen-doctor`, `spectacle`, `busctl`.
- **Kernel headers:** `/usr/include/linux/input-event-codes.h` for named key resolution:
  - Arch / CachyOS: `linux-api-headers` (preinstalled)
  - Fedora: `kernel-headers`
  - Debian / Ubuntu: `linux-libc-dev`
- **`/dev/uinput` write access:** On distros where your user cannot already write to `/dev/uinput` (e.g., via KDE Connect or Steam udev rules), add a seat-scoped `uaccess` rule (no `input` group required):
  ```bash
  echo 'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"' | sudo tee /etc/udev/rules.d/80-uinput.rules
  sudo udevadm control --reload-rules && sudo udevadm trigger /dev/uinput
  ```

## Quickstart

1. **Install the virtual environment and systemd user override:**
   ```bash
   ./scripts/install.sh
   ```
   This installs Python dependencies from `pyproject.toml`, applies the `0600` `graphical-session.target` override for `ydotool.service`, and verifies the runtime socket.

2. **Register with your MCP client:**  
   Merge `config/mcp_config.snippet.json` into your MCP client config (for Antigravity: `~/.gemini/config/mcp_config.json`), replacing `/path/to/kde-wayland-mcp` with your clone path. Update `1000` in `YDOTOOL_SOCKET` if your `id -u` differs (or omit `env` if your MCP host preserves `XDG_RUNTIME_DIR`).

3. **Verify your setup:**
   ```bash
   .venv/bin/python scripts/verify.py
   ```
   For full visual end-to-end proof (corner bullseyes, mouse buttons, scrolling, and keyboard chords), open `scripts/test_target.html` in a browser and follow the 4-tier protocol in [docs/TESTING.md](docs/TESTING.md).

## Security & Trust Model

> **Heads-up:** Giving an AI agent `/dev/uinput` access means any action it is allowed to execute can type into an open terminal or click arbitrary desktop UI—including if steered by prompt injection in an untrusted browser tab or document.

Mitigations built into this architecture:
- **Owner-only socket (`0600`)** inside `$XDG_RUNTIME_DIR` + seat-scoped `uaccess` (no `sudo` at runtime, no global `/dev/input/event*` read access).
- **MCP host per-tool gating** so you control which tools are auto-approved versus human-confirmed.
- **Full 5-minute auditability:** the entire server is one ~20 KB Python file with zero hidden daemons or network listeners.
- **Instant kill switch:** `systemctl --user stop ydotool.service` immediately revokes all input injection.

## Why `/dev/uinput` Instead of `xdg-desktop-portal` / `libei`?

Portals and `libei` are designed for interactive remote-desktop sessions, bringing heavy session-negotiation plumbing that fights a stateless, stdio-driven MCP bridge. Pairing a `0600` user-space `ydotoold` socket with MCP-host per-tool approval keeps the attack surface transparent, the codebase ~20 KB, and input latency near-zero across every app on screen.

## Known Scope & Limitations

- **Single-monitor tested:** Multi-monitor layouts with mixed fractional scaling or secondary displays placed at negative coordinates have not been stress-tested yet.
- **ASCII / US-QWERTY typing:** `ydotool type` injects raw US-QWERTY evdev scancodes; non-ASCII Unicode characters may be dropped or mangled.

## License

Licensed under the [GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)](LICENSE).

