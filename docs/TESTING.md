# Testing Protocol

`kde-wayland-mcp` is verified using a 4-tier testing protocol covering unit/MCP protocol smoke checks, isolated visual target verification, native KDE Qt6/Wayland application interaction, and daemon resilience / edge-case checks.

> **Execution model:** Tier 0 is automated via `scripts/verify.py`. Tiers 1–3 are live runbooks executed by an MCP client/agent (or human) against an active KDE Plasma Wayland desktop.

---

## Tier 0 — Non-Destructive Smoke (`scripts/verify.py`)

Verifies local prerequisites and the MCP stdio server without disturbing open windows:

- `server._parse_key_spec(...)` key names, chords (`Ctrl+c`, `Ctrl+Shift+t`, `Alt+Tab`), and raw evdev tokens
- `screen_info()` (`kscreen-doctor -j` logical resolution & scaling)
- `screenshot()` (`spectacle -f -b -n --scaled` 1:1 PNG dimensions)
- Harmless `scroll(0)`, `key("Shift")`, `type_text("")`, and `ydotool click 0x00` daemon connectivity
- End-to-end MCP `stdio_client` handshake (`initialize`, `list_tools`, `call_tool`, `ToolError` handling)

Run:

```bash
.venv/bin/python scripts/verify.py
```

---

## Tier 1 — Isolated Visual Test Target (`scripts/test_target.html`)

Exercises all 7 MCP tools across **13 visual checks** in a dedicated native Wayland browser window (`firefox --new-window file://.../scripts/test_target.html`):

1. **4 Corner Bullseyes**: `click(x, y, button="left")` on `TOP-LEFT`, `TOP-RIGHT`, `BOTTOM-LEFT`, and `BOTTOM-RIGHT` to validate 1:1 logical coordinate accuracy across the entire monitor.
2. **Mouse Buttons**: `left`, `right`, `middle`, and double-click (`count=2`) on the Click Pad.
3. **Scroll Wheel**: `mouse_move` + `scroll(dy=-4)` (down) and `scroll(dy=2)` (up) on the scrollable list.
4. **Keyboard & Chords**: `click` to focus `<textarea>`, `type_text("Hello Wayland 123! @#$%")`, `key("Ctrl+a")`, `key("BackSpace")`, `type_text("Tier 1 OK")`, `key("Return")`.
5. **Visual Confirmation & Cleanup**: Capture `screenshot()` to confirm `13 / 13 ALL PASSED`, then close with `key("Ctrl+w")`.

---

## Tier 2 — Native KDE Qt6 / Wayland Application (`kwrite`)

Validates real-world interaction against a native Qt6 / KDE Frameworks 6 Wayland app (`/usr/bin/kwrite`):

1. Launch `kwrite` and click **New File** on the Welcome screen.
2. Focus the editor canvas and type multi-line text plus the full shifted ASCII symbol set (`!@#$%^&*()_+-=[]{}|;:',.<>?/`).
3. Test native KDE Undo (`key("Ctrl+z")`) and Redo (`key("Ctrl+Shift+z")`), confirming each step via `screenshot()`.
4. Send `key("Ctrl+q")`, detect KWrite's native `Close Document` modal via `screenshot()`, and click **Discard** so no temporary files are saved.

---

## Tier 3 — Resilience, Hot-Corner Safety & Error Handling

1. **Daemon Restart & KWin Profile Persistence**:
   ```bash
   systemctl --user restart ydotool.service
   ```
   Confirm `$XDG_RUNTIME_DIR/.ydotool_socket` recreates cleanly, `ydotoold virtual device` retains `pointerAccelerationProfileFlat = true` in KWin/libinput, and `mouse_move` hits exact coordinates immediately without restarting the MCP server.
2. **Rapid Moves vs. Active Top-Left Hot Corner**:
   Send back-to-back `mouse_move` calls across all screen quadrants and center (for example, on a ~1920×1200 logical display: `(300,300)` → `(1500,300)` → `(1500,900)` → `(300,900)` → `(948,592)`; scale to your `screen_info()` bounds) and confirm via `screenshot(include_pointer=True)` that the pointer lands accurately and KDE Overview does not accidentally trigger.
3. **Invalid-Input MCP Error Handling**:
   Verify negative coordinates (`mouse_move(-10, 100)`), partial click coordinates (`click(x=100)`), out-of-range click counts (`click(100, 100, count=99)`), and unknown key names (`key("NOT_A_REAL_KEY_XYZ")`) return clean `ToolError` messages and leave `screen_info()` responsive.
