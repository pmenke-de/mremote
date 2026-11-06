#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "aiohttp>=3.9",
#   "pyobjc-framework-Quartz>=10; sys_platform == 'darwin'",
#   "pyobjc-framework-ApplicationServices>=10; sys_platform == 'darwin'",
#   "python-xlib>=0.33; sys_platform == 'linux'",
# ]
# ///
"""mremote – iPhone als Trackpad für den Mac oder einen Linux-Rechner (X11).

Start:   uv run mremote.py [--port 8765] [--token abc]
Dann den ausgegebenen Link auf dem iPhone in Safari öffnen.
"""
import argparse
import os
import pathlib
import secrets
import socket
import subprocess
import sys

from aiohttp import web

if sys.platform == "darwin":
    from backend_macos import Keyboard, Mouse, check_environment
elif sys.platform.startswith("linux"):
    from backend_x11 import Keyboard, Mouse, check_environment
else:
    sys.exit(f"Plattform {sys.platform} wird nicht unterstützt")

HERE = pathlib.Path(__file__).resolve().parent
INDEX = HERE / "static" / "index.html"


def local_ipv4():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # kein Traffic, nur Routing-Lookup
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        pass
    for dev in ("en0", "en1", "en2"):
        try:
            ip = subprocess.run(["ipconfig", "getifaddr", dev], capture_output=True, text=True, timeout=2).stdout.strip()
            if ip:
                return ip
        except (OSError, subprocess.SubprocessError):
            pass
    print("! Lokale IP nicht ermittelbar, nutze 127.0.0.1 – bitte IP von Hand einsetzen.")
    return "127.0.0.1"


# --------------------------------------------------------------------------- HTTP / WS
def make_app(token: str, mouse: Mouse, keyboard: Keyboard) -> web.Application:
    def authed(req):
        return secrets.compare_digest(req.query.get("t", ""), token)

    async def index(req):
        if not authed(req):
            raise web.HTTPForbidden(text="bad token")
        return web.FileResponse(INDEX, headers={"Cache-Control": "no-store"})

    async def ws_handler(req):
        if not authed(req):
            raise web.HTTPForbidden(text="bad token")
        ws = web.WebSocketResponse(heartbeat=20, autoping=True)
        await ws.prepare(req)
        peer = req.remote
        print(f"+ verbunden: {peer}")
        try:
            async for msg in ws:
                if msg.type != web.WSMsgType.TEXT:
                    continue
                # Nachrichten: "m,dx,dy" | "s,dx,dy" | "c,l" | "c,r" | "d,1" (down) | "d,0" (up)
                #              "t,<text>" | "k,<mods>,<key>"   z.B. "k,cmd,c"  "k,,return"
                parts = msg.data.split(",", 2)
                try:
                    kind = parts[0]
                    if kind == "m":
                        mouse.move(float(parts[1]), float(parts[2]))
                    elif kind == "s":
                        mouse.scroll(float(parts[1]), float(parts[2]))
                    elif kind == "c":
                        mouse.click(parts[1])
                    elif kind == "d":
                        mouse.down() if parts[1] == "1" else mouse.up()
                    elif kind == "t":
                        keyboard.type_text(msg.data[2:])
                    elif kind == "k":
                        keyboard.key(parts[1], parts[2])
                except (IndexError, ValueError) as e:
                    print(f"? ungültige Nachricht {msg.data!r}: {e}")
        finally:
            mouse.up()  # Taste nie gedrückt lassen
            print(f"- getrennt: {peer}")
        return ws

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    return app


def main():
    ap = argparse.ArgumentParser(description="iPhone als Trackpad für Mac/Linux")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--token", default=os.environ.get("MREMOTE_TOKEN"),
                    help="festes Token statt Zufallstoken (alternativ Umgebungsvariable MREMOTE_TOKEN)")
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    if not INDEX.exists():
        sys.exit(f"static/index.html fehlt ({INDEX})")

    check_environment()
    token = args.token or secrets.token_urlsafe(6)
    url = f"http://{local_ipv4()}:{args.port}/?t={token}"
    print()
    print("Auf dem iPhone öffnen (Safari, dann optional „Zum Home-Bildschirm“):")
    print(f"\n    {url}\n")

    web.run_app(make_app(token, Mouse(), Keyboard()), host=args.host, port=args.port, print=None, access_log=None)


if __name__ == "__main__":
    main()
