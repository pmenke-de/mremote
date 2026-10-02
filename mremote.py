#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "aiohttp>=3.9",
#   "pyobjc-framework-Quartz>=10",
#   "pyobjc-framework-ApplicationServices>=10",
# ]
# ///
"""mremote – iPhone als Trackpad für den Mac.

Start:   uv run mremote.py [--port 8765] [--token abc]
Dann den ausgegebenen Link auf dem iPhone in Safari öffnen.
"""
import argparse
import pathlib
import secrets
import socket
import subprocess
import sys
import time

from aiohttp import web
import Quartz as Q

HERE = pathlib.Path(__file__).resolve().parent
INDEX = HERE / "static" / "index.html"

DOUBLE_CLICK_S = 0.35  # zwei Taps innerhalb dieser Zeit = Doppelklick


# --------------------------------------------------------------------------- Maus
class Mouse:
    def __init__(self):
        self.last_click_t = 0.0
        self.click_count = 0
        self.left_down = False

    @staticmethod
    def pos():
        p = Q.CGEventGetLocation(Q.CGEventCreate(None))
        return p.x, p.y

    @staticmethod
    def bounds():
        err, ids, n = Q.CGGetActiveDisplayList(16, None, None)
        rects = [Q.CGDisplayBounds(d) for d in ids[:n]] or [Q.CGDisplayBounds(Q.CGMainDisplayID())]
        x0 = min(r.origin.x for r in rects)
        y0 = min(r.origin.y for r in rects)
        x1 = max(r.origin.x + r.size.width for r in rects) - 1
        y1 = max(r.origin.y + r.size.height for r in rects) - 1
        return x0, y0, x1, y1

    def move(self, dx, dy):
        x, y = self.pos()
        x0, y0, x1, y1 = self.bounds()
        nx = min(max(x + dx, x0), x1)
        ny = min(max(y + dy, y0), y1)
        kind = Q.kCGEventLeftMouseDragged if self.left_down else Q.kCGEventMouseMoved
        ev = Q.CGEventCreateMouseEvent(None, kind, (nx, ny), Q.kCGMouseButtonLeft)
        Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventDeltaX, int(round(dx)))
        Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventDeltaY, int(round(dy)))
        Q.CGEventPost(Q.kCGHIDEventTap, ev)

    def _count_click(self):
        now = time.monotonic()
        self.click_count = self.click_count + 1 if now - self.last_click_t < DOUBLE_CLICK_S else 1
        self.last_click_t = now
        return self.click_count

    @staticmethod
    def _post(kind, btn, cnt):
        ev = Q.CGEventCreateMouseEvent(None, kind, Mouse.pos(), btn)
        Q.CGEventSetIntegerValueField(ev, Q.kCGMouseEventClickState, cnt)
        Q.CGEventPost(Q.kCGHIDEventTap, ev)

    def click(self, button="l"):
        if button == "l":
            if self.left_down:
                self.up()
            cnt = self._count_click()
            self._post(Q.kCGEventLeftMouseDown, Q.kCGMouseButtonLeft, cnt)
            self._post(Q.kCGEventLeftMouseUp, Q.kCGMouseButtonLeft, cnt)
        else:
            self._post(Q.kCGEventRightMouseDown, Q.kCGMouseButtonRight, 1)
            self._post(Q.kCGEventRightMouseUp, Q.kCGMouseButtonRight, 1)

    def down(self):
        """Linke Taste gedrückt halten (Drag). Zählt bewusst nicht als Doppelklick."""
        if self.left_down:
            return
        self.left_down = True
        self.click_count = 1
        self.last_click_t = 0.0
        self._post(Q.kCGEventLeftMouseDown, Q.kCGMouseButtonLeft, 1)

    def up(self):
        if not self.left_down:
            return
        self.left_down = False
        self._post(Q.kCGEventLeftMouseUp, Q.kCGMouseButtonLeft, 1)

    @staticmethod
    def scroll(dx, dy):
        ev = Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitPixel, 2, int(round(dy)), int(round(dx)))
        Q.CGEventPost(Q.kCGHIDEventTap, ev)


# --------------------------------------------------------------------------- Tastatur
SPECIAL_KEYS = {
    "return": 36, "enter": 36, "tab": 48, "space": 49, "backspace": 51, "esc": 53,
    "fwddel": 117, "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}
# US-Keycodes für ASCII, damit Shortcuts (⌘C etc.) in allen Apps ankommen
ASCII_KEYCODES = {c: k for k, c in enumerate(
    "asdfhgzxcv\x00bqweryt123465=97-80]ou[ip\x00lj'k;\\,/nm.") if c != "\x00"}
MOD_FLAGS = {
    "cmd": Q.kCGEventFlagMaskCommand, "shift": Q.kCGEventFlagMaskShift,
    "alt": Q.kCGEventFlagMaskAlternate, "ctrl": Q.kCGEventFlagMaskControl,
}


class Keyboard:
    @staticmethod
    def _post_key(keycode, text=None, flags=0):
        for down in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(None, keycode, down)
            if text:
                Q.CGEventKeyboardSetUnicodeString(ev, len(text.encode("utf-16-le")) // 2, text)
            if flags:
                Q.CGEventSetFlags(ev, flags)
            Q.CGEventPost(Q.kCGHIDEventTap, ev)

    def type_text(self, text):
        for ch in text:
            self._post_key(ASCII_KEYCODES.get(ch.lower(), 0), ch)

    def key(self, mods, key):
        flags = 0
        for m in filter(None, mods.split("+")):
            flags |= MOD_FLAGS.get(m, 0)
        if key in SPECIAL_KEYS:
            self._post_key(SPECIAL_KEYS[key], None, flags)
        elif len(key) == 1:
            self._post_key(ASCII_KEYCODES.get(key.lower(), 0), key, flags)


# --------------------------------------------------------------------------- Berechtigung
def ensure_accessibility():
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    except ImportError:
        print("! ApplicationServices nicht verfügbar, Berechtigung kann nicht geprüft werden.")
        return
    if AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True}):
        print("✓ Bedienungshilfen-Berechtigung vorhanden.")
    else:
        print("! Bedienungshilfen-Berechtigung fehlt. Bitte im Dialog freigeben")
        print("  (Systemeinstellungen → Datenschutz & Sicherheit → Bedienungshilfen → Terminal/iTerm)")
        print("  und danach mremote neu starten.")


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
    ap = argparse.ArgumentParser(description="iPhone als Trackpad für den Mac")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--token", default=None, help="festes Token statt Zufallstoken")
    args = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    if not INDEX.exists():
        sys.exit(f"static/index.html fehlt ({INDEX})")

    ensure_accessibility()
    token = args.token or secrets.token_urlsafe(6)
    url = f"http://{local_ipv4()}:{args.port}/?t={token}"
    print()
    print("Auf dem iPhone öffnen (Safari, dann optional „Zum Home-Bildschirm“):")
    print(f"\n    {url}\n")

    web.run_app(make_app(token, Mouse(), Keyboard()), host=args.host, port=args.port, print=None, access_log=None)


if __name__ == "__main__":
    main()
