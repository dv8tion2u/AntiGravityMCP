#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Minimal pure-Wayland KDE Plasma desktop automation MCP server.

Uses only Wayland-native and kernel-level tools (zero X11 / zero xdotool):
- `kscreen-doctor -j` for monitor geometry and fractional scaling
- `spectacle` for silent background screenshots
- `ydotool` + `ydotoold` (/dev/uinput) for pointer and keyboard input
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import TextContent
from PIL import Image as PILImage

mcp = MCPServer(
    name="kde-wayland-mcp",
    instructions=(
        "Pure-Wayland KDE Plasma desktop automation server. "
        "All coordinates for mouse_move and click are in KDE logical screen pixels "
        "(matching screen_info().screen and default screenshot() image dimensions 1:1)."
    ),
)

_INPUT_CODES_HEADER = Path("/usr/include/linux/input-event-codes.h")
_VERIFIED_SOCKET_KEY: tuple[int, int] | None = None
_LAST_SOCKET_KEY: tuple[int, int] | None = None
_FLAT_ACCEL_ATTEMPTS = 0
_MAX_FLAT_ACCEL_ATTEMPTS = 3

_BUTTON_CODES: dict[str, str] = {
    "left": "0xC0",
    "right": "0xC1",
    "middle": "0xC2",
}

_KEY_ALIASES: dict[str, str] = {
    "ctrl": "LEFTCTRL",
    "control": "LEFTCTRL",
    "lctrl": "LEFTCTRL",
    "rctrl": "RIGHTCTRL",
    "alt": "LEFTALT",
    "lalt": "LEFTALT",
    "ralt": "RIGHTALT",
    "altgr": "RIGHTALT",
    "shift": "LEFTSHIFT",
    "lshift": "LEFTSHIFT",
    "rshift": "RIGHTSHIFT",
    "super": "LEFTMETA",
    "meta": "LEFTMETA",
    "win": "LEFTMETA",
    "cmd": "LEFTMETA",
    "lsuper": "LEFTMETA",
    "rsuper": "RIGHTMETA",
    "return": "ENTER",
    "enter": "ENTER",
    "esc": "ESC",
    "escape": "ESC",
    "backspace": "BACKSPACE",
    "bs": "BACKSPACE",
    "del": "DELETE",
    "delete": "DELETE",
    "ins": "INSERT",
    "insert": "INSERT",
    "tab": "TAB",
    "space": "SPACE",
    "pgup": "PAGEUP",
    "page_up": "PAGEUP",
    "pageup": "PAGEUP",
    "pgdn": "PAGEDOWN",
    "pgdown": "PAGEDOWN",
    "page_down": "PAGEDOWN",
    "pagedown": "PAGEDOWN",
    "home": "HOME",
    "end": "END",
    "up": "UP",
    "down": "DOWN",
    "left": "LEFT",
    "right": "RIGHT",
    "capslock": "CAPSLOCK",
    "caps": "CAPSLOCK",
    "prtsc": "SYSRQ",
    "print": "SYSRQ",
    "menu": "COMPOSE",
    "minus": "MINUS",
    "-": "MINUS",
    "equal": "EQUAL",
    "equals": "EQUAL",
    "=": "EQUAL",
    "plus": "KPPLUS",
    "[": "LEFTBRACE",
    "]": "RIGHTBRACE",
    ";": "SEMICOLON",
    "'": "APOSTROPHE",
    "`": "GRAVE",
    "\\": "BACKSLASH",
    ",": "COMMA",
    ".": "DOT",
    "/": "SLASH",
}


def _load_keycodes() -> dict[str, int]:
    """Load Linux KEY_* constants from /usr/include/linux/input-event-codes.h."""
    codes: dict[str, int] = {}
    if _INPUT_CODES_HEADER.is_file():
        pattern = re.compile(r"^#define\s+KEY_([A-Z0-9_]+)\s+(0x[0-9a-fA-F]+|\d+)")
        for line in _INPUT_CODES_HEADER.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = pattern.match(line)
            if match:
                codes[match.group(1)] = int(match.group(2), 0)
    return codes


_KEYCODES: dict[str, int] = _load_keycodes()


def _runtime_dir() -> str:
    return os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"


def _ydotool_socket() -> str:
    return os.environ.get("YDOTOOL_SOCKET") or os.path.join(_runtime_dir(), ".ydotool_socket")


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", _runtime_dir())
    env["YDOTOOL_SOCKET"] = _ydotool_socket()
    env.setdefault("QT_QPA_PLATFORM", "wayland")
    return env


def _env_delay_s(name: str, default_ms: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default_ms / 1000.0
    try:
        ms = float(raw)
    except ValueError:
        return default_ms / 1000.0
    return max(0.0, min(ms, 1000.0)) / 1000.0


_MOVE_SETTLE_S = _env_delay_s("KDE_MCP_MOVE_SETTLE_MS", 15.0)
_CLICK_SETTLE_S = _env_delay_s("KDE_MCP_CLICK_SETTLE_MS", 20.0)


def _run(
    cmd: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: float = 15.0,
) -> subprocess.CompletedProcess[bytes]:
    try:
        proc = subprocess.run(
            cmd,
            input=input_bytes,
            capture_output=True,
            env=_base_env(),
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"Required binary not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"Command timed out after {timeout}s: {' '.join(cmd)}") from exc

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        detail = stderr or stdout or f"exit code {proc.returncode}"
        raise ToolError(f"Command failed ({' '.join(cmd)}): {detail}")
    return proc


def _ensure_ydotool_ready() -> None:
    """Verify ydotoold socket exists and KWin uses flat acceleration for ydotoold."""
    global _VERIFIED_SOCKET_KEY, _LAST_SOCKET_KEY, _FLAT_ACCEL_ATTEMPTS
    sock = _ydotool_socket()
    try:
        st = os.stat(sock)
    except FileNotFoundError as exc:
        raise ToolError(
            f"ydotoold socket not found at {sock}. "
            "Start it with: systemctl --user start ydotool.service"
        ) from exc

    sock_key = (st.st_ino, st.st_mtime_ns)
    if sock_key == _VERIFIED_SOCKET_KEY:
        return
    if sock_key != _LAST_SOCKET_KEY:
        _LAST_SOCKET_KEY = sock_key
        _FLAT_ACCEL_ATTEMPTS = 0
    if _FLAT_ACCEL_ATTEMPTS >= _MAX_FLAT_ACCEL_ATTEMPTS:
        return
    _FLAT_ACCEL_ATTEMPTS += 1

    try:
        # Ensure KWin's libinput profile for ydotoold virtual device is Flat
        # so relative pixel deltas map 1:1 to logical screen coordinates.
        out = subprocess.check_output(
            [
                "busctl",
                "--user",
                "get-property",
                "org.kde.KWin",
                "/org/kde/KWin/InputDevice",
                "org.kde.KWin.InputDeviceManager",
                "devicesSysNames",
            ],
            env=_base_env(),
            text=True,
            timeout=3.0,
        )
        for sys_name in re.findall(r'"(event\d+)"', out):
            name_out = subprocess.check_output(
                [
                    "busctl",
                    "--user",
                    "get-property",
                    "org.kde.KWin",
                    f"/org/kde/KWin/InputDevice/{sys_name}",
                    "org.kde.KWin.InputDevice",
                    "name",
                ],
                env=_base_env(),
                text=True,
                timeout=2.0,
            )
            if "ydotoold virtual device" in name_out:
                res = subprocess.run(
                    [
                        "busctl",
                        "--user",
                        "set-property",
                        "org.kde.KWin",
                        f"/org/kde/KWin/InputDevice/{sys_name}",
                        "org.kde.KWin.InputDevice",
                        "pointerAccelerationProfileFlat",
                        "b",
                        "true",
                    ],
                    env=_base_env(),
                    check=False,
                    timeout=2.0,
                )
                if res.returncode == 0:
                    _VERIFIED_SOCKET_KEY = sock_key
                break
    except Exception:
        # Non-fatal if KWin D-Bus isn't reachable; kcminputrc persists the setting.
        pass


def _get_screen_info() -> dict[str, Any]:
    proc = _run(["kscreen-doctor", "-j"])
    try:
        raw = json.loads(proc.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError(f"Failed to parse kscreen-doctor JSON: {exc}") from exc

    screen_size = raw.get("screen", {}).get("currentSize", {})
    outputs: list[dict[str, Any]] = []
    for out in raw.get("outputs", []):
        scale = float(out.get("scale", 1.0))
        phys_w = int(out.get("size", {}).get("width", 0))
        phys_h = int(out.get("size", {}).get("height", 0))
        current_mode_id = out.get("currentModeId")
        refresh_rate = None
        for mode in out.get("modes", []):
            if mode.get("id") == current_mode_id:
                refresh_rate = mode.get("refreshRate")
                break
        outputs.append(
            {
                "name": out.get("name"),
                "enabled": bool(out.get("enabled", False)),
                "connected": bool(out.get("connected", False)),
                "primary": out.get("priority") == 1,
                "position": out.get("pos", {"x": 0, "y": 0}),
                "scale": scale,
                "physical_size": {"width": phys_w, "height": phys_h},
                "logical_size": {
                    "width": round(phys_w / scale) if scale else phys_w,
                    "height": round(phys_h / scale) if scale else phys_h,
                },
                "refresh_rate": refresh_rate,
                "rotation": out.get("rotation"),
            }
        )

    return {
        "coordinate_space": "logical",
        "screen": {
            "width": int(screen_size.get("width", 0)),
            "height": int(screen_size.get("height", 0)),
        },
        "outputs": outputs,
    }


def _resolve_keycode(token: str) -> int:
    """Resolve a human key name, KEY_* name, or numeric keycode to an evdev keycode."""
    cleaned = token.strip()
    if not cleaned:
        raise ToolError("Empty key token")
    if cleaned.isdigit():
        return int(cleaned)
    if not _KEYCODES:
        raise ToolError(
            f"Linux keycode header not found at {_INPUT_CODES_HEADER}. "
            "Install kernel headers (Arch: linux-api-headers, Fedora: kernel-headers, "
            "Debian/Ubuntu: linux-libc-dev), or pass numeric evdev keycodes."
        )
    lower = cleaned.lower()
    if lower in _KEY_ALIASES:
        name = _KEY_ALIASES[lower]
    else:
        name = cleaned.upper()
        if name.startswith("KEY_"):
            name = name[4:]
    if name in _KEYCODES:
        return _KEYCODES[name]
    raise ToolError(
        f"Unknown key {token!r}. Use names like 'Return', 'Ctrl+c', 'Alt+Tab', 'F5', "
        "a Linux KEY_* name, or a numeric evdev keycode."
    )


def _parse_key_spec(keys: str) -> list[str]:
    """Convert a key expression into ydotool `<keycode>:<1|0>` arguments.

    Supports:
    - Raw ydotool tokens: `"28:1 28:0"`
    - Single keys: `"Return"`, `"Escape"`, `"a"`, `"F5"`, `"28"`
    - Chords: `"Ctrl+c"`, `"Ctrl+Shift+t"`, `"Alt+Tab"`, `"Super+d"`
    - Space-separated sequences: `"Ctrl+l BackSpace Return"`
    """
    tokens = keys.strip().split()
    if not tokens:
        raise ToolError("keys must not be empty")

    # Pass raw `<int>:<0|1>` tokens straight through.
    if all(re.fullmatch(r"\d+:[01]", tok) for tok in tokens):
        return tokens

    ydo_events: list[str] = []
    for tok in tokens:
        if re.fullmatch(r"\d+:[01]", tok):
            ydo_events.append(tok)
            continue
        # Handle literal "+" key vs chord separator
        if tok == "+":
            parts = ["plus"]
        else:
            parts = [p for p in tok.split("+") if p]
            if tok.endswith("++"):
                parts.append("plus")
        codes = [_resolve_keycode(part) for part in parts]
        for code in codes:
            ydo_events.append(f"{code}:1")
        for code in reversed(codes):
            ydo_events.append(f"{code}:0")
    return ydo_events


def _move_pointer_abs(x: int, y: int) -> None:
    """Move pointer to exact logical coordinates (x, y) via ydotoold.

    ydotool 1.0.4's single-shot `mousemove -a -x X -y Y` emits INT32_MIN reset
    and (+X, +Y) back-to-back with 0ms delay, which KWin/libinput frequently
    coalesces back to (0, 0). Separating reset and offset by 15ms with flat
    pointer acceleration yields exact 1:1 logical pixel positioning.
    """
    _ensure_ydotool_ready()
    _run(["ydotool", "mousemove", "-a", "-x", "0", "-y", "0"])
    if x != 0 or y != 0:
        if _MOVE_SETTLE_S > 0:
            time.sleep(_MOVE_SETTLE_S)
        _run(["ydotool", "mousemove", "-x", str(x), "-y", str(y)])


@mcp.tool()
def screen_info() -> dict[str, Any]:
    """Return KDE Wayland monitor geometry, resolution, and scaling via kscreen-doctor.

    The returned `screen.width` x `screen.height` defines the logical coordinate
    space used by `mouse_move`, `click`, and default `screenshot()` images.
    """
    return _get_screen_info()


@mcp.tool()
def screenshot(
    include_pointer: bool = False,
    native_resolution: bool = False,
) -> list[TextContent | Image]:
    """Capture the KDE Wayland desktop silently via Spectacle.

    Args:
        include_pointer: Include the mouse cursor in the screenshot.
        native_resolution: If False (default), captures with `--scaled` so image
            pixels match logical screen coordinates (`mouse_move`/`click`) 1:1.
            If True, captures at full physical panel resolution.

    Returns:
        Text metadata with image & screen dimensions, followed by the PNG image.
    """
    info = _get_screen_info()
    fd, tmp_path = tempfile.mkstemp(prefix="kde_wayland_mcp_", suffix=".png")
    os.close(fd)
    try:
        cmd = ["spectacle", "-f", "-b", "-n"]
        if not native_resolution:
            cmd.append("--scaled")
        if include_pointer:
            cmd.append("-p")
        cmd.extend(["-o", tmp_path])
        _run(cmd, timeout=20.0)

        with PILImage.open(tmp_path) as img:
            img_w, img_h = img.size
        png_bytes = Path(tmp_path).read_bytes()
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    meta = {
        "image_size": {"width": img_w, "height": img_h},
        "logical_screen": info["screen"],
        "coordinate_space": "physical" if native_resolution else "logical (1:1 with mouse_move/click)",
        "outputs": [
            {
                "name": o["name"],
                "scale": o["scale"],
                "physical_size": o["physical_size"],
                "logical_size": o["logical_size"],
            }
            for o in info["outputs"]
            if o["enabled"]
        ],
    }
    return [
        TextContent(type="text", text=json.dumps(meta, indent=2)),
        Image(data=png_bytes, format="png"),
    ]


@mcp.tool()
def mouse_move(x: int, y: int) -> dict[str, Any]:
    """Move the mouse cursor to absolute logical screen coordinates (x, y).

    Coordinates are in logical pixels matching `screen_info().screen` and
    default `screenshot()` images (0, 0 is top-left).
    """
    if x < 0 or y < 0:
        raise ToolError(f"Coordinates must be non-negative, got ({x}, {y})")
    _move_pointer_abs(x, y)
    return {"ok": True, "x": x, "y": y}


@mcp.tool()
def click(
    x: int | None = None,
    y: int | None = None,
    button: Literal["left", "right", "middle"] = "left",
    count: int = 1,
) -> dict[str, Any]:
    """Click a mouse button, optionally moving to logical coordinates (x, y) first.

    Args:
        x: Optional logical X coordinate to move to before clicking.
        y: Optional logical Y coordinate to move to before clicking.
        button: Mouse button (`left`, `right`, or `middle`).
        count: Number of clicks (e.g. `2` for double-click).
    """
    if (x is None) != (y is None):
        raise ToolError("Provide both x and y, or omit both to click at the current pointer position.")
    if button not in _BUTTON_CODES:
        raise ToolError(f"Invalid button {button!r}; expected one of: {', '.join(_BUTTON_CODES)}")
    if count < 1 or count > 10:
        raise ToolError(f"count must be between 1 and 10, got {count}")

    _ensure_ydotool_ready()
    if x is not None and y is not None:
        if x < 0 or y < 0:
            raise ToolError(f"Coordinates must be non-negative, got ({x}, {y})")
        _move_pointer_abs(x, y)
        if _CLICK_SETTLE_S > 0:
            time.sleep(_CLICK_SETTLE_S)

    cmd = ["ydotool", "click"]
    if count > 1:
        cmd.extend(["-r", str(count)])
    cmd.append(_BUTTON_CODES[button])
    _run(cmd)
    return {"ok": True, "x": x, "y": y, "button": button, "count": count}


@mcp.tool()
def scroll(dy: int, dx: int = 0) -> dict[str, Any]:
    """Scroll the mouse wheel relatively via ydotool.

    Args:
        dy: Vertical scroll notches (positive = scroll up, negative = scroll down).
        dx: Optional horizontal scroll notches (positive = right, negative = left).
    """
    _ensure_ydotool_ready()
    _run(["ydotool", "mousemove", "-w", "-x", str(dx), "-y", str(dy)])
    return {"ok": True, "dy": dy, "dx": dx}


@mcp.tool()
def type_text(text: str, key_delay_ms: int = 12) -> dict[str, Any]:
    """Type literal ASCII text via ydotool (passed over stdin so escaping/flags are safe).

    Note: `ydotool type` emits US-QWERTY evdev scancodes (printable ASCII);
    non-ASCII Unicode characters may be skipped or mangled.

    Args:
        text: The text string to type.
        key_delay_ms: Delay in milliseconds between key events (default 12).
    """
    if key_delay_ms < 0 or key_delay_ms > 500:
        raise ToolError(f"key_delay_ms must be between 0 and 500, got {key_delay_ms}")
    _ensure_ydotool_ready()
    timeout = max(15.0, (len(text) * max(key_delay_ms, 1) * 4 / 1000.0) + 10.0)
    _run(
        ["ydotool", "type", "--key-delay", str(key_delay_ms), "--file", "-"],
        input_bytes=text.encode("utf-8"),
        timeout=timeout,
    )
    return {"ok": True, "length": len(text)}


@mcp.tool()
def key(keys: str, key_delay_ms: int = 12) -> dict[str, Any]:
    """Send key presses or chord combinations via ydotool.

    Args:
        keys: Key name, chord, sequence, or raw ydotool keycode events.
            Examples: `"Return"`, `"Escape"`, `"Ctrl+c"`, `"Alt+Tab"`,
            `"Ctrl+Shift+t"`, `"Super+d"`, `"Up Down Return"`, or `"28:1 28:0"`.
        key_delay_ms: Delay in milliseconds between key events (default 12).
    """
    if key_delay_ms < 0 or key_delay_ms > 500:
        raise ToolError(f"key_delay_ms must be between 0 and 500, got {key_delay_ms}")
    _ensure_ydotool_ready()
    events = _parse_key_spec(keys)
    timeout = max(15.0, (len(events) * max(key_delay_ms, 1) / 1000.0) + 10.0)
    _run(["ydotool", "key", "-d", str(key_delay_ms), *events], timeout=timeout)
    return {"ok": True, "keys": keys, "events": events}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
