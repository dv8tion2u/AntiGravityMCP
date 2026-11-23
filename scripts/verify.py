#!/usr/bin/env python3
"""Non-destructive end-to-end verification for kde-wayland-mcp."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))

import server  # noqa: E402
from mcp import ClientSession, StdioServerParameters, stdio_client  # noqa: E402


async def run_mcp_checks() -> None:
    socket_path = os.environ.get(
        "YDOTOOL_SOCKET",
        f"{os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')}/.ydotool_socket",
    )
    params = StdioServerParameters(
        command=str(REPO_DIR / ".venv" / "bin" / "python"),
        args=[str(REPO_DIR / "server.py")],
        env={**os.environ, "YDOTOOL_SOCKET": socket_path},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.server_info.name == "kde-wayland-mcp"
            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            expected = [
                "screen_info",
                "screenshot",
                "mouse_move",
                "click",
                "scroll",
                "type_text",
                "key",
            ]
            assert names == expected, f"Unexpected tool list: {names}"

            res_info = await session.call_tool("screen_info", {})
            assert not res_info.is_error
            res_shot = await session.call_tool("screenshot", {})
            assert not res_shot.is_error
            assert [c.type for c in res_shot.content] == ["text", "image"]
            res_err = await session.call_tool("click", {"x": 100})
            assert res_err.is_error
            print(f"MCP stdio checks passed ({len(names)} tools verified)")


def main() -> None:
    assert server._parse_key_spec("Return") == ["28:1", "28:0"]
    assert server._parse_key_spec("Ctrl+c") == ["29:1", "46:1", "46:0", "29:0"]
    assert server._parse_key_spec("Ctrl+Shift+t") == [
        "29:1",
        "42:1",
        "20:1",
        "20:0",
        "42:0",
        "29:0",
    ]
    assert server._parse_key_spec("Alt+Tab") == ["56:1", "15:1", "15:0", "56:0"]

    info = server.screen_info()
    w, h = info["screen"]["width"], info["screen"]["height"]
    assert w > 0 and h > 0, info
    print(f"screen_info: {w}x{h} logical")

    shot = server.screenshot()
    meta = json.loads(shot[0].text)
    assert meta["image_size"] == {"width": w, "height": h}
    assert shot[1].data.startswith(b"\x89PNG\r\n\x1a\n")
    print(f"screenshot: {meta['image_size']} ({len(shot[1].data)} bytes)")

    assert server.scroll(0)["ok"]
    assert server.key("Shift")["ok"]
    assert server.type_text("")["ok"]
    server._run(["ydotool", "click", "0x00"])
    print("Direct primitive checks passed")

    asyncio.run(run_mcp_checks())
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
