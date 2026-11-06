# mremote

Use your iPhone as a trackpad and keyboard for your Mac or Linux box (X11). No account, no
cloud, no app store.

A small Python server runs on the computer and serves a single web page. Open it in Safari on the
iPhone and the screen becomes a trackpad; a WebSocket carries the touch deltas to the computer,
where they are turned into native mouse and keyboard events (Quartz on macOS, XTEST on X11).

Built for the "Mac on the TV, iPhone on the couch" case. Works over LAN or a VPN tunnel.

## Requirements

- macOS (uses the Quartz / CoreGraphics event APIs), or Linux with an X11 session
  (uses the XTEST extension; Wayland is not supported)
- [uv](https://docs.astral.sh/uv/) – dependencies are declared inline in the script (PEP 723),
  so `uv run` installs them on first start
- iPhone with Safari on the same network (or reachable via VPN)

## Usage

```
uv run mremote.py
uv run mremote.py --port 9000 --token mytoken   # fixed port/token, e.g. for a Home Screen bookmark
```

On first start, macOS asks for the Accessibility permission for your terminal app
(System Settings → Privacy & Security → Accessibility). Grant it and restart mremote.

The server prints a link like `http://192.168.1.23:8765/?t=abc123`. Open it in Safari on the
iPhone (Universal Clipboard makes this easy). Optionally use *Share → Add to Home Screen* to get a
full-screen app-like experience.

## Linux (X11)

Runs as the logged-in user, no root and no uinput needed. To run it as a systemd user service
with a fixed token (so the Home Screen link stays valid):

```
git clone https://github.com/pmenke-de/mremote.git ~/mremote
cp ~/mremote/contrib/mremote.service ~/.config/systemd/user/
(umask 077; echo "MREMOTE_TOKEN=$(openssl rand -hex 12)" > ~/.config/mremote.env)
systemctl --user daemon-reload && systemctl --user enable --now mremote
```

The unit assumes `DISPLAY=:0` and `~/.Xauthority`; adjust it if your session differs. Notes:

- The ⌘ key on the page acts as Ctrl, so ⌘C/⌘V/⌘L/⌘W behave like on the Mac. ⌃ is Ctrl too.
- Scrolling is sent as wheel notches (one per `SCROLL_STEP_PX` in `backend_x11.py`).
- Characters missing from the keyboard layout (ä, €, …) are typed by temporarily mapping them to
  an unused keycode.
- A locked screen grabs the keyboard; input then goes to the unlock dialog.

## Gestures

| Gesture                              | Action                                   |
|--------------------------------------|------------------------------------------|
| 1 finger swipe                       | Move pointer (with acceleration)         |
| 1 finger tap                         | Left click (two quick taps = double click) |
| Tap, then tap-and-hold + drag        | Drag / select text                       |
| 2 finger tap                         | Right click                              |
| 2 finger swipe                       | Scroll                                   |
| ⌨ button (bottom right)              | Toggle the iPhone keyboard               |

With the keyboard open, a key bar appears at the top with `esc`, `tab`, `⌘ ⌥ ⌃ ⇧`, forward
delete, backspace and arrow keys. Modifiers apply to the next key: tap ⌘, then type `c` to send ⌘C.
The trackpad keeps working while the keyboard is open.

## Tuning

Pointer gain, acceleration, scroll speed and scroll direction are constants at the top of the
`<script>` block in `static/index.html`. If scrolling feels inverted, set `INVERT_SCROLL = true`.

## Security

This is a home-network tool, not a hardened service:

- Access is protected only by a random token in the URL; anyone who has the link can control
  your Mac. Treat it like a password.
- Traffic is plain HTTP/WebSocket, unencrypted. Use it on a trusted network or through a VPN.
- The server binds to all interfaces by default. Use `--host 127.0.0.1` together with an SSH or
  VPN tunnel if you want to avoid exposing it on the LAN at all.

## How it works

- `mremote.py` – aiohttp server. Serves the page, validates the token, and dispatches WebSocket
  messages (`m,dx,dy`, `s,dx,dy`, `c,l|r`, `d,0|1`, `t,<text>`, `k,<mods>,<key>`) to the platform
  backend.
- `backend_macos.py` – `CGEventPost` calls; requests the Accessibility permission on start.
- `backend_x11.py` – XTEST fake input via python-xlib.
- `contrib/mremote.service` – systemd user unit for Linux.
- `static/index.html` – the trackpad page. Touch gesture recognition, auto-reconnect, and a
  hidden text field whose content is diffed on every change so that autocorrect and backspace
  arrive on the Mac as the right sequence of keystrokes.

## License

MIT, see [LICENSE](LICENSE).
