"""Recording-only, transient input visualization. No input is persisted or logged."""

from collections import deque
from dataclasses import dataclass
from functools import lru_cache
import ctypes
import sys
import threading
import time
import unicodedata
from types import SimpleNamespace

from PyQt6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import QWidget

KEY_HOLD = 3.5
KEY_FADE = 0.65
CLICK_HOLD = 0.65
CLICK_FADE = 0.35
MODIFIERS = ("ctrl", "alt", "shift", "cmd")
SPECIAL_LABELS = {
    "ctrl": "Ctrl",
    "alt": "Alt",
    "alt_gr": "AltGr",
    "shift": "Shift",
    "cmd": "Win",
    "caps_lock": "Caps",
    "tab": "Tab",
    "enter": "Enter",
    "backspace": "Backspace",
    "space": "Space",
    "delete": "Del",
    "esc": "Esc",
    "home": "Home",
    "end": "End",
    "page_up": "PgUp",
    "page_down": "PgDn",
    "insert": "Ins",
    "num_lock": "Num",
    "scroll_lock": "ScrLk",
    "print_screen": "PrtSc",
    "pause": "Pause",
    "menu": "Menu",
    "up": "",
    "down": "",
    "left": "",
    "right": "",
    "media_play_pause": "Play",
    "media_stop": "Stop",
    "media_next": "Next",
    "media_previous": "Prev",
    "media_volume_up": "Vol+",
    "media_volume_down": "Vol−",
    "media_volume_mute": "Mute",
}


@dataclass(frozen=True)
class KeyFace:
    kind: str
    text: str


VK_NAMES = {
    0x5B: 'cmd', 0x5C: 'cmd', 0x10: 'shift', 0xA0: 'shift', 0xA1: 'shift',
    0x11: 'ctrl', 0xA2: 'ctrl', 0xA3: 'ctrl', 0x12: 'alt', 0xA4: 'alt', 0xA5: 'alt',
    0xAD: 'media_volume_mute', 0xAE: 'media_volume_down', 0xAF: 'media_volume_up',
    0xB0: 'media_next', 0xB1: 'media_previous', 0xB2: 'media_stop', 0xB3: 'media_play_pause',
    **{0x70+i: f'f{i+1}' for i in range(24)},
}

def normalized_key_name(key):
    return getattr(key, 'name', '') or VK_NAMES.get(getattr(key, 'vk', None), '')


def modifier_name(name):
    if name == "alt_gr":
        return "alt_gr"
    for modifier in MODIFIERS:
        if name == modifier or name in (modifier + "_l", modifier + "_r"):
            return modifier
    return None


def key_face(key, translated=None):
    """Keep actual Unicode case/symbols; never canonicalize as a hotkey."""
    if key is None:
        return None
    name = normalized_key_name(key)
    modifier = modifier_name(name)
    if modifier:
        return KeyFace(modifier, SPECIAL_LABELS[modifier])
    if name in SPECIAL_LABELS:
        return KeyFace(name, SPECIAL_LABELS[name])
    if name.startswith("f") and name[1:].isdigit():
        return KeyFace("text", name.upper())
    char = translated if translated is not None else getattr(key, "char", None)
    if char == " ":
        return KeyFace("space", "Space")
    if char and all(ch.isprintable() for ch in char):
        if unicodedata.combining(char[0]):
            char = "◌" + char
        return KeyFace("text", char[:8])
    # Ctrl+A..Z can arrive as ASCII control codes. No uppercasing shortcut labels.
    if char and len(char) == 1 and 1 <= ord(char) <= 26:
        return KeyFace("text", chr(ord(char) + 96))
    vk = getattr(key, "vk", None)
    if vk is not None:
        return KeyFace("text", f"VK {vk:02X}")
    return KeyFace("text", name.replace("_", " ").title()[:12]) if name else None


class WindowsKeyTranslator:
    """Translate using the foreground layout, Shift and real Caps Lock state.

    ToUnicodeEx flag 4 avoids altering the application's dead-key buffer (Win10+).
    This runs on the listener thread, never from a Qt paint or a low-level hook.
    """

    def __init__(self):
        from ctypes import wintypes

        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.GetForegroundWindow.restype = wintypes.HWND
        self.api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
        self.api.GetKeyboardLayout.argtypes = [wintypes.DWORD]
        self.api.GetKeyboardLayout.restype = wintypes.HKL
        self.api.MapVirtualKeyExW.argtypes = [
            wintypes.UINT,
            wintypes.UINT,
            wintypes.HKL,
        ]
        self.api.ToUnicodeEx.argtypes = [
            wintypes.UINT,
            wintypes.UINT,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.HKL,
        ]

    def modifiers(self):
        return tuple(
            name
            for name, vk in zip(MODIFIERS, (0x11, 0x12, 0x10, 0x5B))
            if self.api.GetAsyncKeyState(vk) & 0x8000
        ) + (
            ("cmd",)
            if self.api.GetAsyncKeyState(0x5C) & 0x8000
            and not self.api.GetAsyncKeyState(0x5B) & 0x8000
            else ()
        )

    def translate(self, key):
        vk = getattr(key, "vk", None)
        if vk is None or getattr(key, "name", None):
            return None
        state = (ctypes.c_ubyte * 256)()
        self.api.GetKeyboardState(state)
        for code in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5):
            state[code] = 0x80 if self.api.GetAsyncKeyState(code) & 0x8000 else 0
        state[0x14] = self.api.GetKeyState(0x14) & 1
        # Ctrl shortcuts need the printable key; retain Ctrl+Alt for AltGr layouts.
        if state[0x11] and not state[0x12]:
            for code in (0x11, 0xA2, 0xA3):
                state[code] = 0
        thread = self.api.GetWindowThreadProcessId(self.api.GetForegroundWindow(), None)
        layout = self.api.GetKeyboardLayout(thread)
        scan = self.api.MapVirtualKeyExW(vk, 0, layout)
        out = ctypes.create_unicode_buffer(16)
        count = self.api.ToUnicodeEx(vk, scan, state, out, len(out), 4, layout)
        return out[: abs(count)] if count else None


@dataclass
class KeyEntry:
    faces: tuple
    at: float
    modifier_only: bool = False


@dataclass
class MouseEntry:
    kind: str
    x: float
    y: float
    at: float


def opacity(at, now, hold, fade):
    return max(0.0, min(1.0, (hold + fade - (now - at)) / fade))


class KeycastHistory:
    def __init__(self):
        self.keys = deque(maxlen=40)
        self.clicks = deque(maxlen=12)

    def clear(self):
        self.keys.clear()
        self.clicks.clear()

    def press(self, face, modifiers, now):
        if face is None:
            return
        modifier_only = face.kind in (*MODIFIERS, "alt_gr")
        mods = tuple(
            KeyFace(m, "")
            for m in (*MODIFIERS, "alt_gr")
            if m in modifiers and m != face.kind
        )
        faces = mods + (face,)
        if (
            self.keys
            and self.keys[-1].modifier_only
            and all(previous.kind in modifiers for previous in self.keys[-1].faces)
        ):
            self.keys.pop()
        self.keys.append(KeyEntry(faces, now, modifier_only))

    def mouse(self, kind, x, y, now):
        # Wheel bursts/held-button pulses share one marker per action/location.
        if (
            self.clicks
            and self.clicks[-1].kind == kind
            and now - self.clicks[-1].at < 0.12
        ):
            last = self.clicks[-1]
            if abs(x - last.x) + abs(y - last.y) < 12:
                last.at = now
                return
        self.clicks.append(MouseEntry(kind, x, y, now))

    def expire(self, now):
        while self.keys and now - self.keys[0].at >= KEY_HOLD + KEY_FADE:
            self.keys.popleft()
        while self.clicks and now - self.clicks[0].at >= CLICK_HOLD + CLICK_FADE:
            self.clicks.popleft()


def draw_glyph(p, kind, rect):
    """Vector special-key artwork, independent of symbol-font availability."""
    p.save()
    p.translate(rect.x(), rect.y())
    p.scale(rect.width() / 20, rect.height() / 20)
    pen = QPen(
        p.pen().color(),
        1.5,
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    if kind in ("shift", "caps_lock"):
        path = QPainterPath(QPointF(3, 10))
        for x, y in ((10, 3), (17, 10), (13, 10), (13, 16), (7, 16), (7, 10), (3, 10)):
            path.lineTo(x, y)
        p.drawPath(path)
        if kind == "caps_lock":
            line(7, 19, 13, 19)
    elif kind == "cmd":
        for x, y in ((3, 3), (11, 3), (3, 11), (11, 11)):
            p.drawRect(QRectF(x, y, 6, 6))
    elif kind == "ctrl":
        line(4, 13, 10, 7)
        line(10, 7, 16, 13)
    elif kind in ("alt", "alt_gr"):
        line(3, 5, 8, 5)
        line(8, 5, 13, 15)
        line(13, 15, 18, 15)
        line(11, 5, 17, 5)
    elif kind in ("tab", "enter", "space"):
        if kind == "tab":
            line(3, 10, 16, 10)
            line(12, 6, 16, 10)
            line(12, 14, 16, 10)
            line(18, 5, 18, 15)
        elif kind == "enter":
            line(17, 4, 17, 12)
            line(17, 12, 4, 12)
            line(8, 8, 4, 12)
            line(8, 16, 4, 12)
        else:
            line(3, 8, 3, 14)
            line(3, 14, 17, 14)
            line(17, 14, 17, 8)
    elif kind in ("backspace", "delete"):
        path = QPainterPath(QPointF(2, 10))
        for x, y in ((7, 4), (18, 4), (18, 16), (7, 16), (2, 10)):
            path.lineTo(x, y)
        p.drawPath(path)
        line(10, 7, 15, 13)
        line(10, 13, 15, 7)
    elif kind in ("left", "right", "up", "down"):
        angle = {"right": 0, "down": 90, "left": 180, "up": 270}[kind]
        p.translate(10, 10)
        p.rotate(angle)
        p.translate(-10, -10)
        line(3, 10, 17, 10)
        line(12, 5, 17, 10)
        line(12, 15, 17, 10)
    p.restore()


GLYPH_KEYS = {
    "shift",
    "caps_lock",
    "cmd",
    "ctrl",
    "alt",
    "alt_gr",
    "tab",
    "enter",
    "space",
    "backspace",
    "delete",
    "left",
    "right",
    "up",
    "down",
}


def keycast_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#F7F7FA"), 3))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(4, 18, 39, 29), 5, 5)
    p.setBrush(QColor("#F7F7FA"))
    p.setPen(Qt.PenStyle.NoPen)
    for y in (25, 33):
        for x in (11, 19, 27, 35):
            p.drawRoundedRect(QRectF(x, y, 4, 4), 1, 1)
    p.drawRoundedRect(QRectF(15, 41, 19, 3), 1, 1)
    p.setPen(QPen(QColor("#F7F7FA"), 3))
    p.setBrush(QColor("#181D27"))
    p.drawRoundedRect(QRectF(43, 14, 17, 36), 8, 8)
    p.drawLine(QPointF(51.5, 16), QPointF(51.5, 29))
    p.drawLine(QPointF(44, 30), QPointF(59, 30))
    p.end()
    return QIcon(pixmap)


@lru_cache(maxsize=32)
def key_metrics(height):
    # Cache font metrics only, never typed characters beyond the transient history.
    font = QFont("Segoe UI")
    font.setPixelSize(max(9, round(height * 0.40)))
    font.setWeight(QFont.Weight.DemiBold)
    return QFontMetricsF(font)


def face_width(face, height):
    if face.kind in (*MODIFIERS, "alt_gr") and not face.text:
        return height * 0.75
    text = key_metrics(height).horizontalAdvance(face.text)
    glyph = height * 0.50 if face.kind in GLYPH_KEYS else 0
    return max(
        height,
        min(height * 4, text + glyph + (height * 0.55 if glyph else height * 0.50)),
    )


def key_layout(entries, width, height):
    """At most two compact rows, newest events retained, all boxes inside capture."""
    if not entries or width < 16 or height < 16:
        return []
    margin = min(12, max(2, width * 0.03), max(2, height * 0.03))
    available = max(1, width - 2 * margin)
    cap = min(32, max(18, width / 14), max(12, (height - 2 * margin - 4) / 2))
    # A chord must fit as one unit. Shrink it before dropping older events.
    latest = entries[-1]

    def group_width(entry, h):
        return sum(face_width(f, h) for f in entry.faces) + 3 * (len(entry.faces) - 1)

    while group_width(latest, cap) > available and cap > 12:
        cap -= 1
    rows = [[]]
    used = 0
    for entry in reversed(entries):
        w = group_width(entry, cap)
        if w > available:
            # Tiny selections retain the actual last key, rather than clipped modifiers.
            faces = (entry.faces[-1],)
            w = min(available, face_width(faces[0], cap))
        else:
            faces = entry.faces
        if rows[-1] and used + w > available:
            if len(rows) == 2 or height < 2 * cap + 2 * margin + 4:
                break
            rows.append([])
            used = 0
        rows[-1].append((entry, faces, w))
        used += w + 6
    result = []
    rows = list(reversed(rows))
    for index, row in enumerate(rows):
        row = list(reversed(row))
        total = sum(item[2] for item in row) + 6 * (len(row) - 1)
        x = (width - total) / 2
        y = height - margin - (len(rows) - index) * cap - (len(rows) - 1 - index) * 4
        for entry, faces, w in row:
            for face in faces:
                fw = min(w, face_width(face, cap))
                result.append((entry, face, QRectF(x, y, fw, cap)))
                x += fw + 3
            x += 3
    return result


class KeycastOverlay(QWidget):
    def __init__(self, region):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(
            region["left"], region["top"], region["width"], region["height"]
        )
        self.history = KeycastHistory()
        self.clock = time.monotonic
        self.setWindowTitle("Keycast")
        # Deliberately no capture exclusion: these indicators belong in the video.

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        now = self.clock()
        layout = key_layout(list(self.history.keys), self.width(), self.height())
        painted = set()
        for entry, face, rect in layout:
            p.save()
            p.setOpacity(opacity(entry.at, now, KEY_HOLD, KEY_FADE))
            p.setPen(QPen(QColor("#667084"), 1))
            p.setBrush(QColor(20, 25, 35, 235))
            if id(entry) not in painted:
                group = QRectF(rect)
                for other, _, other_rect in layout:
                    if other is entry:
                        group = group.united(other_rect)
                p.drawRoundedRect(group, 5, 5)
                painted.add(id(entry))
            p.setClipRect(rect)
            p.setPen(QColor("#F7F7FA"))
            font = QFont("Segoe UI")
            font.setPixelSize(max(9, round(rect.height() * 0.40)))
            font.setWeight(QFont.Weight.DemiBold)
            p.setFont(font)
            text_rect = rect.adjusted(5, 0, -5, 0)
            if face.kind in GLYPH_KEYS:
                size = rect.height() * 0.5
                glyph = QRectF(rect.x() + 5, rect.center().y() - size / 2, size, size)
                draw_glyph(p, face.kind, glyph)
                text_rect.setLeft(glyph.right() + 3)
            # Narrow areas elide labels; vector icons remain recognizable.
            text = QFontMetricsF(font).elidedText(
                face.text, Qt.TextElideMode.ElideRight, max(0, text_rect.width())
            )
            p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)
            p.restore()
        for click in self.history.clicks:
            p.setOpacity(opacity(click.at, now, CLICK_HOLD, CLICK_FADE))
            self._paint_click(p, click)
        p.end()

    def _paint_click(self, p, click):
        labels = {
            "left": "Left",
            "right": "Right",
            "middle": "Middle",
            "x1": "Back",
            "x2": "Forward",
            "scroll_up": "Scroll",
            "scroll_down": "Scroll",
            "scroll_left": "Scroll",
            "scroll_right": "Scroll",
        }
        label = labels.get(click.kind, click.kind)
        color = QColor(
            "#FF7182"
            if click.kind == "left"
            else "#8CBFFF" if click.kind == "right" else "#C6A1FF"
        )
        # Thin ring at the click position plus a compact mouse silhouette/label.
        p.setPen(QPen(color, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        radius = 8 + min(5, max(0, self.clock() - click.at) * 10)
        p.drawEllipse(QPointF(click.x, click.y), radius, radius)
        w = min(102, max(24, self.width() - 4))
        h = min(30, max(16, self.height() - 4))
        x = max(2, min(click.x + 15, self.width() - w - 2))
        y = max(2, min(click.y + 15, self.height() - h - 2))
        box = QRectF(x, y, w, h)
        p.setPen(QPen(QColor("#667084"), 1))
        p.setBrush(QColor(20, 25, 35, 240))
        p.drawRoundedRect(box, 6, 6)
        if w >= 60:
            mouse = QRectF(x + 7, y + 5, 13, h - 10)
            p.setPen(QPen(color, 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(mouse, 5, 5)
            p.setBrush(color)
            if click.kind in ("left", "right"):
                p.drawRoundedRect(
                    QRectF(
                        mouse.x() + (1 if click.kind == "left" else 7),
                        mouse.y() + 2,
                        5,
                        7,
                    ),
                    1,
                    1,
                )
            else:
                p.drawRoundedRect(
                    QRectF(mouse.center().x() - 1.5, mouse.y() + 3, 3, 7), 1, 1
                )
            if click.kind.startswith("scroll_"):
                p.setPen(QPen(color, 1.5))
                draw_glyph(
                    p,
                    click.kind.removeprefix("scroll_"),
                    QRectF(x + 23, y + (h - 14) / 2, 14, 14),
                )
        font = QFont("Segoe UI")
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor("#F7F7FA"))
        r = box.adjusted(
            (40 if click.kind.startswith("scroll_") else 25) if w >= 60 else 2, 0, -3, 0
        )
        p.drawText(
            r,
            Qt.AlignmentFlag.AlignCenter,
            QFontMetricsF(font).elidedText(
                label, Qt.TextElideMode.ElideRight, r.width()
            ),
        )


def raw_wheel_direction(message, mouse_data):
    """Preserve sub-detent precision-touchpad deltas before pynput floors /120."""
    if message not in (0x020A, 0x020E):
        return None
    delta = ctypes.c_short((mouse_data >> 16) & 0xFFFF).value
    if not delta:
        return None
    return (
        ("scroll_up" if delta > 0 else "scroll_down")
        if message == 0x020A
        else ("scroll_right" if delta > 0 else "scroll_left")
    )


class InputSession:
    """Bounded cross-thread mailbox. Hooks never call Qt or retain a text log."""

    def __init__(self, factory=None):
        self.lock = threading.Lock()
        self.events = deque(maxlen=128)
        self.closed = threading.Event()
        self.listeners = []
        self.error = None
        self.ready = False
        self.modifiers = {}
        self.factory = factory
        self.cleanup_error = None
        self.started_at = time.monotonic()
        threading.Thread(target=self._start, name="Keycast start", daemon=True).start()

    def _put(self, event):
        with self.lock:
            if not self.closed.is_set():
                self.events.append(event)

    def _start(self):
        listeners = []
        try:
            translator = WindowsKeyTranslator() if sys.platform == "win32" else None
            if self.factory is None:
                from pynput import keyboard, mouse

                factory = lambda **kw: (
                    keyboard.Listener(on_press=kw["press"], on_release=kw["release"],
                                      win32_event_filter=kw["keyboard_filter"]),
                    mouse.Listener(
                        on_click=kw["click"],
                        on_scroll=kw["scroll"],
                        win32_event_filter=kw["wheel_filter"],
                    ),
                )
            else:
                factory = self.factory

            def press(key, *_):
                if self.closed.is_set():
                    return
                name = normalized_key_name(key)
                mod = modifier_name(name)
                if mod:
                    self.modifiers[name] = mod
                mods = (
                    translator.modifiers()
                    if translator
                    else tuple(set(self.modifiers.values()))
                )
                # Async state can lag the modifier's own key-down event.
                if mod and mod not in mods:
                    mods = mods + (mod,)
                face = key_face(key, translator.translate(key) if translator else None)
                self._put(("key", face, mods, time.monotonic()))

            def release(key, *_):
                self.modifiers.pop(normalized_key_name(key), None)

            def click(x, y, button, pressed, *_):
                if pressed:
                    self._put(
                        (
                            "mouse",
                            getattr(button, "name", str(button)),
                            x,
                            y,
                            time.monotonic(),
                        )
                    )

            def scroll(x, y, dx, dy, *_):
                if dy:
                    self._put(
                        (
                            "mouse",
                            "scroll_up" if dy > 0 else "scroll_down",
                            x,
                            y,
                            time.monotonic(),
                        )
                    )
                if dx:
                    self._put(
                        (
                            "mouse",
                            "scroll_right" if dx > 0 else "scroll_left",
                            x,
                            y,
                            time.monotonic(),
                        )
                    )

            def keyboard_filter(message, data):
                # Handle named system/media/F keys directly from the Windows hook.
                # Returning False skips pynput conversion, never suppresses OS input.
                if data.vkCode in VK_NAMES and message in (0x100, 0x101, 0x104, 0x105):
                    key = SimpleNamespace(vk=data.vkCode, name=VK_NAMES[data.vkCode])
                    if message in (0x100, 0x104):
                        press(key)
                    else:
                        release(key)
                    return False
                return True

            def wheel_filter(message, data):
                if message in (0x020A, 0x020E):
                    kind = raw_wheel_direction(message, data.mouseData)
                    if kind:
                        self._put(
                            ("mouse", kind, data.pt.x, data.pt.y, time.monotonic())
                        )
                    # Skip only pynput's integer conversion, never suppress OS input.
                    return False
                return True

            listeners = list(
                factory(
                    press=press,
                    release=release,
                    click=click,
                    scroll=scroll,
                    wheel_filter=wheel_filter,
                    keyboard_filter=keyboard_filter,
                )
            )
            for listener in listeners:
                if self.closed.is_set():
                    break
                listener.start()
            with self.lock:
                self.listeners = listeners
                self.ready = True
        except Exception:
            # Never log the key or raw callback exception (it could include input).
            with self.lock:
                self.error = "Keycast could not monitor keyboard and mouse input."
            self.closed.set()
        if self.closed.is_set():
            self._cleanup(listeners)

    def _cleanup(self, listeners, timeout=1):
        # stop() itself may wait for pynput's message loop. Bound that wait as
        # well as join(); closed callbacks can never enqueue more input.
        errors = []

        def request_stop(listener):
            try:
                listener.stop()
            except Exception:
                errors.append("Keycast could not detach an input listener.")

        requests = []
        for listener in listeners:
            request = threading.Thread(
                target=request_stop, args=(listener,), daemon=True
            )
            request.start()
            requests.append(request)
        deadline = time.monotonic() + timeout
        for request in requests:
            request.join(timeout=max(0, deadline - time.monotonic()))
        for listener in listeners:
            try:
                listener.join(timeout=max(0, deadline - time.monotonic()))
            except RuntimeError:
                # A cancellation before start leaves a never-started listener.
                pass
            except Exception:
                errors.append("Keycast could not finish input listener cleanup.")
        if any(request.is_alive() for request in requests) or any(
            listener.is_alive() for listener in listeners
        ):
            errors.append("Keycast input cleanup timed out; input display is disabled.")
        if errors:
            with self.lock:
                self.cleanup_error = errors[-1]

    def drain(self):
        with self.lock:
            events = list(self.events)
            self.events.clear()
            error = self.error
            ready = self.ready
            listeners = list(self.listeners)
        if not error and ready and any(not item.is_alive() for item in listeners):
            error = "Keycast input monitoring stopped. Toggle Keycast to retry."
        if not ready and time.monotonic() - self.started_at > 5:
            error = "Keycast input monitoring did not start. Toggle Keycast to retry."
        return events, error

    def stop(self):
        self.closed.set()
        with self.lock:
            self.events.clear()
            listeners = list(self.listeners)
        # pynput stop can wait for its message loop: keep even stop off the GUI.
        threading.Thread(
            target=self._cleanup, args=(listeners,), name="Keycast stop", daemon=True
        ).start()


def native_to_logical(x, y, screens):
    for s in screens:
        if (
            s.native_left <= x < s.native_left + s.native_width
            and s.native_top <= y < s.native_top + s.native_height
        ):
            return (
                s.logical_left + (x - s.native_left) * s.logical_width / s.native_width,
                s.logical_top + (y - s.native_top) * s.logical_height / s.native_height,
            )
    return None


class KeycastController(QObject):
    failed = pyqtSignal(str)

    def __init__(self, parent=None, session_factory=InputSession):
        super().__init__(parent)
        self.overlay = None
        self.session = None
        self.region = None
        self.screens = []
        self.session_factory = session_factory
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)

    def start(self, region, screens):
        self.stop()
        self.region = dict(region)
        self.screens = list(screens)
        try:
            self.overlay = KeycastOverlay(region)
            self.session = self.session_factory()
            self.overlay.show()
            self.timer.start()
        except Exception:
            self.stop()
            self.failed.emit("Keycast could not start. Recording continues.")

    def stop(self):
        self.timer.stop()
        if self.session:
            self.session.stop()
            self.session = None
        if self.overlay:
            self.overlay.history.clear()
            self.overlay.close()
            self.overlay.deleteLater()
            self.overlay = None

    def _tick(self):
        if not self.session or not self.overlay:
            return
        events, error = self.session.drain()
        if error:
            self.stop()
            self.failed.emit(error + " Recording continues.")
            return
        history = self.overlay.history
        had_content = bool(history.keys or history.clicks)
        for event in events:
            if event[0] == "key":
                history.press(event[1], event[2], event[3])
            else:
                _, kind, x, y, at = event
                point = native_to_logical(x, y, self.screens)
                if point:
                    x = point[0] - self.region["left"]
                    y = point[1] - self.region["top"]
                    if 0 <= x < self.region["width"] and 0 <= y < self.region["height"]:
                        history.mouse(kind, x, y, at)
        history.expire(time.monotonic())
        if had_content or history.keys or history.clicks:
            self.overlay.update()
