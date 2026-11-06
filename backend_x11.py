"""Linux/X11 backend: injects mouse and keyboard events via the XTEST extension.

Needs a running X session (DISPLAY, XAUTHORITY). No root, no uinput.
"""
import os

from Xlib import X, XK, display
from Xlib.ext import xtest

SCROLL_STEP_PX = 40  # pixel delta from the page that equals one wheel notch
MOD_KEYSYMS = {
    # Mac habits on Linux: ⌘ acts as Ctrl so ⌘C/⌘V/⌘W/⌘L do what you expect.
    "cmd": "Control_L", "ctrl": "Control_L", "alt": "Alt_L", "shift": "Shift_L", "super": "Super_L",
}
SPECIAL_KEYSYMS = {
    "return": "Return", "enter": "Return", "tab": "Tab", "space": "space", "backspace": "BackSpace",
    "esc": "Escape", "fwddel": "Delete", "home": "Home", "end": "End", "pageup": "Prior",
    "pagedown": "Next", "left": "Left", "right": "Right", "down": "Down", "up": "Up",
    **{f"f{i}": f"F{i}" for i in range(1, 13)},
}


def check_environment():
    if not os.environ.get("DISPLAY"):
        print("! DISPLAY ist nicht gesetzt – mremote in der X-Sitzung starten oder DISPLAY=:0 setzen.")
    d = display.Display()
    if not d.has_extension("XTEST"):
        raise SystemExit("X-Server hat keine XTEST-Erweiterung")
    print(f"✓ X-Display {d.get_display_name()} mit XTEST.")
    d.close()


class _X:
    d = None

    @classmethod
    def get(cls):
        if cls.d is None:
            cls.d = display.Display()
        return cls.d


class Mouse:
    def __init__(self):
        self.d = _X.get()
        self.root = self.d.screen().root
        self.left_down = False
        self.fx = self.fy = None  # float pointer position, keeps sub-pixel motion
        self.scroll_acc = [0.0, 0.0]

    def _btn(self, button, press):
        xtest.fake_input(self.d, X.ButtonPress if press else X.ButtonRelease, button)

    def move(self, dx, dy):
        p = self.root.query_pointer()
        if self.fx is None or round(self.fx) != p.root_x or round(self.fy) != p.root_y:
            self.fx, self.fy = float(p.root_x), float(p.root_y)  # moved by someone else
        g = self.root.get_geometry()
        self.fx = min(max(self.fx + dx, 0), g.width - 1)
        self.fy = min(max(self.fy + dy, 0), g.height - 1)
        xtest.fake_input(self.d, X.MotionNotify, x=round(self.fx), y=round(self.fy))
        self.d.flush()

    def click(self, button="l"):
        if button == "l":
            if self.left_down:
                self.up()
            b = 1
        else:
            b = 3
        self._btn(b, True)
        self._btn(b, False)
        self.d.flush()  # X clients detect double clicks themselves by timing

    def down(self):
        if self.left_down:
            return
        self.left_down = True
        self._btn(1, True)
        self.d.flush()

    def up(self):
        if not self.left_down:
            return
        self.left_down = False
        self._btn(1, False)
        self.d.flush()

    def scroll(self, dx, dy):
        # Same sign convention as macOS pixel scroll: positive dy = wheel up (button 4),
        # positive dx = wheel left (button 6).
        for axis, delta, pos_btn, neg_btn in ((1, dy, 4, 5), (0, dx, 6, 7)):
            self.scroll_acc[axis] += delta
            while abs(self.scroll_acc[axis]) >= SCROLL_STEP_PX:
                pos = self.scroll_acc[axis] > 0
                b = pos_btn if pos else neg_btn
                self._btn(b, True)
                self._btn(b, False)
                self.scroll_acc[axis] -= SCROLL_STEP_PX if pos else -SCROLL_STEP_PX
        self.d.flush()


class Keyboard:
    def __init__(self):
        self.d = _X.get()
        self.min_kc, self.max_kc = self.d.display.info.min_keycode, self.d.display.info.max_keycode
        self._reload_mapping()

    def _reload_mapping(self):
        n = self.max_kc - self.min_kc + 1
        self.mapping = self.d.get_keyboard_mapping(self.min_kc, n)
        # Keycodes without any keysym are free for temporary Unicode mappings.
        self.spare = [self.min_kc + i for i, syms in enumerate(self.mapping) if not any(syms)]
        self.spare_next = 0
        self.spare_map = {}  # keysym -> spare keycode currently mapped to it

    def _lookup(self, keysym):
        """(keycode, needs_shift) if keysym is reachable without AltGr, else None."""
        for i, syms in enumerate(self.mapping):
            for level in (0, 1):
                if level < len(syms) and syms[level] == keysym:
                    return self.min_kc + i, level == 1
        return None

    def _spare_keycode(self, keysym):
        if keysym in self.spare_map:
            return self.spare_map[keysym]
        if not self.spare:
            return None
        # Round-robin over spare keycodes: a mapping is only overwritten many keystrokes later,
        # so clients have long processed the previous key with the right symbol.
        kc = self.spare[self.spare_next % len(self.spare)]
        self.spare_next += 1
        for k, v in list(self.spare_map.items()):
            if v == kc:
                del self.spare_map[k]
        self.d.change_keyboard_mapping(kc, [(keysym, keysym)])
        self.d.sync()
        self.spare_map[keysym] = kc
        return kc

    def _tap(self, keycode, mod_keycodes=()):
        for m in mod_keycodes:
            xtest.fake_input(self.d, X.KeyPress, m)
        xtest.fake_input(self.d, X.KeyPress, keycode)
        xtest.fake_input(self.d, X.KeyRelease, keycode)
        for m in reversed(mod_keycodes):
            xtest.fake_input(self.d, X.KeyRelease, m)

    def _mod_keycodes(self, mods):
        out = []
        for m in filter(None, mods.split("+")):
            name = MOD_KEYSYMS.get(m)
            kc = self.d.keysym_to_keycode(XK.string_to_keysym(name)) if name else 0
            if kc and kc not in out:
                out.append(kc)
        return out

    @staticmethod
    def _char_keysym(ch):
        cp = ord(ch)
        if ch == "\n":
            return XK.string_to_keysym("Return")
        if ch == "\t":
            return XK.string_to_keysym("Tab")
        if 0x20 <= cp <= 0x7E or 0xA0 <= cp <= 0xFF:
            return cp  # Latin-1 keysyms equal the code point
        return 0x01000000 | cp  # X11 Unicode keysym

    def _type_char(self, ch, extra_mods=()):
        keysym = self._char_keysym(ch)
        hit = self._lookup(keysym)
        if hit:
            kc, shift = hit
            mods = list(extra_mods)
            if shift:
                mods.append(self.d.keysym_to_keycode(XK.string_to_keysym("Shift_L")))
            self._tap(kc, mods)
        else:
            kc = self._spare_keycode(keysym)
            if kc:
                self._tap(kc, extra_mods)

    def type_text(self, text):
        for ch in text:
            self._type_char(ch)
        self.d.flush()

    def key(self, mods, key):
        mod_kcs = self._mod_keycodes(mods)
        if key in SPECIAL_KEYSYMS:
            kc = self.d.keysym_to_keycode(XK.string_to_keysym(SPECIAL_KEYSYMS[key]))
            if kc:
                self._tap(kc, mod_kcs)
        elif len(key) == 1:
            if mod_kcs and key.isascii() and key.isalpha():
                # Shortcuts use the base key (Ctrl+C, not Ctrl+Shift+c); shift comes from mods.
                hit = self._lookup(ord(key.lower()))
                if hit:
                    self._tap(hit[0], mod_kcs)
                    self.d.flush()
                    return
            self._type_char(key, mod_kcs)
        self.d.flush()
