"""macOS backend: injects mouse and keyboard events via Quartz (CGEventPost)."""
import time

import Quartz as Q

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


def check_environment():
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
