"""Keycast event translation, timed layout, input lifecycle and capture ownership."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import ctypes
import threading
import time

import pytest
from PyQt6.QtCore import QPoint, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter
from PyQt6.QtWidgets import QApplication
import keycast as kc
from display_geometry import ScreenTransform


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def key(char=None, name=None, vk=None):
    return SimpleNamespace(char=char, name=name, vk=vk)


@pytest.mark.parametrize(
    "char",
    ["a", "A", "s", "S", "@", "#", "!", "é", "É", "中", "🙂", "+", "[", "]", "\\"],
)
def test_character_case_and_symbols_are_never_canonicalized(char):
    assert kc.key_face(key(char)).text == char


@pytest.mark.parametrize(
    "name,kind",
    [
        ("ctrl_l", "ctrl"),
        ("ctrl_r", "ctrl"),
        ("shift_r", "shift"),
        ("cmd_l", "cmd"),
        ("alt_gr", "alt_gr"),
        ("caps_lock", "caps_lock"),
        ("tab", "tab"),
        ("space", "space"),
        ("enter", "enter"),
        ("backspace", "backspace"),
        ("delete", "delete"),
        ("left", "left"),
        ("media_volume_up", "media_volume_up"),
    ],
)
def test_special_faces_have_distinct_vector_or_readable_fallback(name, kind):
    face = kc.key_face(key(name=name))
    assert face.kind == kind
    assert face.kind in kc.GLYPH_KEYS or face.text


def test_unknown_dead_and_function_keys():
    assert kc.key_face(None) is None
    assert kc.key_face(key("\x01")).text == "a"
    assert kc.key_face(key("\u0301")).text == "◌́"
    assert kc.key_face(key(name="f24")).text == "F24"
    assert kc.key_face(key(vk=0xF0)).text == "VK F0"
    assert kc.key_face(key("a"), translated="A").text == "A"


class KeyboardAPI:
    """Fake foreground layout: asserts state supplied to Windows translation."""

    def __init__(self, shift, caps, ctrl=False, alt=False):
        self.shift = shift
        self.caps = caps
        self.ctrl = ctrl
        self.alt = alt

    def GetKeyboardState(self, state):
        return 1

    def GetAsyncKeyState(self, vk):
        return (
            0x8000
            if {0x10: self.shift, 0x11: self.ctrl, 0x12: self.alt}.get(vk, False)
            else 0
        )

    def GetKeyState(self, vk):
        return int(self.caps)

    def GetForegroundWindow(self):
        return 100

    def GetWindowThreadProcessId(self, hwnd, arg):
        assert hwnd == 100
        return 42

    def GetKeyboardLayout(self, tid):
        assert tid == 42
        return 73

    def MapVirtualKeyExW(self, vk, kind, layout):
        assert layout == 73
        return 30

    def ToUnicodeEx(self, vk, scan, state, out, size, flags, layout):
        assert flags == 4 and layout == 73
        assert not state[0x11] or self.alt  # Ctrl shortcuts use printable characters.
        if vk == ord("2"):
            char = "@" if state[0x10] else "2"
        else:
            char = "A" if bool(state[0x10]) ^ bool(state[0x14]) else "a"
        out.value = char
        return 1


@pytest.mark.parametrize(
    "shift,caps,expected",
    [(False, False, "a"), (True, False, "A"), (False, True, "A"), (True, True, "a")],
)
@pytest.mark.parametrize("ctrl", [False, True])
def test_windows_caps_shift_xor_and_ctrl_shortcut_case(shift, caps, expected, ctrl):
    translator = kc.WindowsKeyTranslator.__new__(kc.WindowsKeyTranslator)
    translator.api = KeyboardAPI(shift, caps, ctrl)
    assert translator.translate(key("x", vk=65)) == expected
    assert translator.translate(key("2", vk=50)) == ("@" if shift else "2")


def test_windows_altgr_keeps_ctrl_alt_for_layout_translation():
    translator = kc.WindowsKeyTranslator.__new__(kc.WindowsKeyTranslator)
    translator.api = KeyboardAPI(False, False, True, True)
    assert translator.translate(key(vk=65)) == "a"


def test_recent_sequence_chord_and_independent_expiry():
    history = kc.KeycastHistory()
    for n, ch in enumerate("aSdfG"):
        history.press(kc.KeyFace("text", ch), (), n * 0.1)
    assert [e.faces[-1].text for e in history.keys] == list("aSdfG")
    history.press(kc.KeyFace("ctrl", "Ctrl"), ("ctrl",), 1)
    history.press(kc.KeyFace("text", "c"), ("ctrl",), 1.1)
    assert [f.kind for f in history.keys[-1].faces] == ["ctrl", "text"]
    assert len(history.keys) == 6
    assert kc.opacity(0, 3.4, kc.KEY_HOLD, kc.KEY_FADE) == 1
    assert 0 < kc.opacity(0, 3.8, kc.KEY_HOLD, kc.KEY_FADE) < 1
    history.expire(4.2)
    assert history.keys[0].faces[-1].text == "S"
    history.expire(7)
    assert not history.keys


@pytest.mark.parametrize(
    "width,height", [(1920, 1080), (640, 360), (240, 120), (100, 70), (32, 32)]
)
def test_adaptive_keycaps_stay_inside_recorded_area(width, height):
    history = kc.KeycastHistory()
    for ch in "aSdfG@#":
        history.press(kc.KeyFace("text", ch), (), 1)
    history.press(kc.KeyFace("text", "é"), ("ctrl", "alt", "shift", "cmd"), 2)
    layout = kc.key_layout(list(history.keys), width, height)
    assert layout
    bounds = QRectF(0, 0, width, height)
    for _, _, rect in layout:
        assert bounds.contains(rect)
    assert layout[-1][1].text == "é"
    assert len({r.y() for _, _, r in layout}) <= 2


def test_five_keys_visible_as_individual_caps_in_normal_selection():
    h = kc.KeycastHistory()
    for c in "ASDFG":
        h.press(kc.KeyFace("text", c), (), 1)
    layout = kc.key_layout(list(h.keys), 320, 180)
    assert [face.text for _, face, _ in layout] == list("ASDFG")
    assert len({r.x() for _, _, r in layout}) == 5


def test_history_and_mouse_bursts_are_bounded_and_expire():
    h = kc.KeycastHistory()
    for n in range(1000):
        h.press(kc.KeyFace("text", "a"), (), n * 0.01)
    assert len(h.keys) == 40
    h.mouse("scroll_up", 30, 40, 11)
    h.mouse("scroll_up", 31, 40, 11.05)
    assert len(h.clicks) == 1
    for n in range(50):
        h.mouse("left", n * 20, 40, 12 + n * 0.02)
    assert len(h.clicks) == 12
    h.expire(20)
    assert not h.keys and not h.clicks


def test_negative_origin_mixed_dpi_native_mapping():
    screens = [
        ScreenTransform("left", -1280, 0, 1280, 720, -1920, 0, 1920, 1080),
        ScreenTransform("right", 0, 0, 1920, 1080, 0, 0, 1920, 1080),
    ]
    assert kc.native_to_logical(-960, 540, screens) == (-640, 360)
    assert kc.native_to_logical(100, 100, screens) == (100, 100)
    assert kc.native_to_logical(-2000, 100, screens) is None


class FakeSession:
    def __init__(self):
        self.events = []
        self.error = None
        self.stopped = False

    def drain(self):
        events = self.events
        self.events = []
        return events, self.error

    def stop(self):
        self.stopped = True


def test_controller_filters_outside_clicks_and_stops_on_failure(app):
    ctl = kc.KeycastController(session_factory=FakeSession)
    screen = ScreenTransform("s", -400, 0, 400, 300, -800, 0, 800, 600)
    ctl.start({"left": -350, "top": 20, "width": 200, "height": 150}, [screen])
    overlay = ctl.overlay
    session = ctl.session
    now = time.monotonic()
    session.events = [
        ("key", kc.KeyFace("text", "A"), (), now),
        ("mouse", "left", -600, 100, now),
        ("mouse", "right", -10, 20, now),
    ]
    ctl._tick()
    assert len(overlay.history.keys) == 1 and len(overlay.history.clicks) == 1
    assert (overlay.history.clicks[0].x, overlay.history.clicks[0].y) == (50, 30)
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    failures = []
    ctl.failed.connect(failures.append)
    session.error = "No hook"
    ctl._tick()
    assert failures and "Recording continues" in failures[0]
    assert session.stopped and ctl.overlay is None and not ctl.timer.isActive()
    assert not overlay.history.keys
    ctl.stop()


class FakeListener:
    def __init__(self):
        self.alive = False
        self.stops = 0

    def start(self):
        self.alive = True

    def is_alive(self):
        return self.alive

    def stop(self):
        self.stops += 1
        self.alive = False

    def join(self, timeout):
        assert 0 <= timeout <= 1


def await_condition(condition):
    deadline = time.monotonic() + 2
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert condition()


def test_threaded_mailbox_callbacks_stop_late_events_and_both_modifier_sides(
    monkeypatch,
):
    monkeypatch.setattr(kc.sys, "platform", "linux")
    hooks = {}
    listeners = [FakeListener(), FakeListener()]

    def factory(**callbacks):
        hooks.update(callbacks)
        return listeners

    session = kc.InputSession(factory)
    await_condition(lambda: session.ready)
    hooks["press"](key(name="ctrl_l"))
    hooks["press"](key(name="ctrl_r"))
    hooks["release"](key(name="ctrl_l"))
    hooks["press"](key("a"))
    hooks["click"](1, 2, key(name="middle"), True)
    hooks["click"](1, 2, key(name="left"), False)
    hooks["scroll"](1, 2, -1, 1)
    events, error = session.drain()
    assert error is None
    assert events[2][2] == ("ctrl",)
    assert [e[1] for e in events if e[0] == "mouse"] == [
        "middle",
        "scroll_up",
        "scroll_left",
    ]
    for _ in range(200):
        hooks["press"](key("z"))
    assert len(session.events) == 128
    session.stop()
    hooks["press"](key("Q"))
    assert session.drain()[0] == []
    await_condition(lambda: all(l.stops for l in listeners))


def test_stop_during_delayed_listener_creation_does_not_leave_hooks(monkeypatch):
    monkeypatch.setattr(kc.sys, "platform", "linux")
    gate = threading.Event()
    entered = threading.Event()
    listeners = [FakeListener(), FakeListener()]

    def factory(**_):
        entered.set()
        gate.wait(1)
        return listeners

    session = kc.InputSession(factory)
    assert entered.wait(1)
    session.stop()
    gate.set()
    await_condition(lambda: all(l.stops for l in listeners))
    assert not any(l.alive for l in listeners)


def test_listener_failure_is_reported_without_recorded_input(monkeypatch):
    monkeypatch.setattr(kc.sys, "platform", "linux")

    def fail(**_):
        raise RuntimeError("private input must not be logged")

    session = kc.InputSession(fail)
    await_condition(lambda: session.closed.is_set())
    events, error = session.drain()
    assert not events and "private" not in error
    session.stop()


def test_overlay_renders_special_keys_and_all_mouse_actions(app, tmp_path):
    overlay = kc.KeycastOverlay({"left": 0, "top": 0, "width": 800, "height": 260})
    overlay.clock = lambda: 10
    for n, name in enumerate(("ctrl", "shift", "caps_lock", "tab", "cmd", "enter")):
        overlay.history.press(kc.key_face(key(name=name)), (), 9 + n * 0.01)
    overlay.history.press(kc.KeyFace("text", "aA@#"), (), 9.2)
    for n, kind in enumerate(
        (
            "left",
            "right",
            "middle",
            "scroll_up",
            "scroll_down",
            "scroll_left",
            "scroll_right",
        )
    ):
        overlay.history.mouse(kind, 25 + n * 105, 30, 9.7)
    overlay.show()
    app.processEvents()
    image = overlay.grab().toImage()
    assert not image.isNull()
    image.save(str(tmp_path / "keycast.png"))
    assert any(
        image.pixelColor(x, round(230 * image.devicePixelRatio())).alpha() > 0
        for x in range(image.width())
    )
    overlay.close()


def test_keycast_pill_toggle_arms_then_starts_pauses_clears_and_stops(app):
    from ui_elements import PillWidget

    class Engine:
        paused = False

        def get_system_audio(self):
            return False

        def get_mic(self):
            return False

        def is_paused(self):
            return self.paused

        def pause(self):
            self.paused = True

        def resume(self):
            self.paused = False

    engine = Engine()
    pill = PillWidget(engine, {"keycast_warning_dismissed": True}, pre_record=True)
    pill._keycast.session_factory = FakeSession
    button = pill._btn_keycast
    assert button.width() == button.height() == 38 and not button.isChecked()
    assert not button.icon().isNull() and button.accessibleName() == "Keycast"
    button.click()
    assert pill._keycast.session is None
    pill.set_keycast_region({"left": 0, "top": 0, "width": 320, "height": 180})
    pill.set_preparing(True)
    assert not button.isEnabled()
    pill.set_recording_mode()
    assert pill._keycast.session is not None and button.isEnabled()
    previous = pill._keycast.session
    pill.toggle_pause()
    assert previous.stopped and pill._keycast.overlay is None and button.isChecked()
    pill.toggle_pause()
    assert pill._keycast.session is not previous
    pill._on_keycast_failed("Keycast failed. Recording continues.")
    assert not button.isChecked() and pill._keycast.session is None
    assert "Recording continues" in button.toolTip()
    pill._stopping = True
    pill.close()


def test_each_scroll_direction_has_its_own_vector_arrow(app):
    renders = []
    for direction in ("up", "down", "left", "right"):
        image = QImage(30, 30, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setPen(QColor("#FFFFFF"))
        kc.draw_glyph(painter, direction, QRectF(5, 5, 20, 20))
        painter.end()
        renders.append(image)
    assert all(renders[i] != renders[j] for i in range(4) for j in range(i + 1, 4))


def test_listener_partial_start_failure_stops_other_listener(monkeypatch):
    monkeypatch.setattr(kc.sys, "platform", "linux")
    first = FakeListener()

    class Broken(FakeListener):
        def start(self):
            raise RuntimeError("hook setup failure")

    second = Broken()
    session = kc.InputSession(lambda **_: (first, second))
    await_condition(lambda: first.stops > 0)
    assert not first.alive and session.drain()[1]
    session.stop()


def test_listener_runtime_death_and_start_timeout():
    session = kc.InputSession.__new__(kc.InputSession)
    session.lock = threading.Lock()
    session.events = kc.deque(maxlen=128)
    session.error = None
    session.ready = True
    session.listeners = [FakeListener()]
    session.started_at = time.monotonic()
    assert "stopped" in session.drain()[1]
    session.ready = False
    session.started_at = time.monotonic() - 6
    assert "did not start" in session.drain()[1]


def test_close_clears_active_keycast_even_when_pill_already_stopping(app):
    from ui_elements import PillWidget

    engine = SimpleNamespace(
        get_system_audio=lambda: False, get_mic=lambda: False, is_paused=lambda: False
    )
    pill = PillWidget(engine, {"keycast_warning_dismissed": True}, pre_record=False)
    pill._keycast.session_factory = FakeSession
    pill.set_keycast_region({"left": 0, "top": 0, "width": 320, "height": 180})
    pill._btn_keycast.click()
    session = pill._keycast.session
    pill._stopping = True
    pill.close()
    assert session.stopped and pill._keycast.overlay is None


def test_released_modifier_tap_remains_in_history():
    h = kc.KeycastHistory()
    h.press(kc.KeyFace("shift", "Shift"), ("shift",), 1)
    h.press(kc.KeyFace("text", "a"), (), 1.1)
    assert [e.faces[-1].text for e in h.keys] == ["Shift", "a"]


def test_controller_setup_failure_does_not_interrupt_recording(app):
    def broken():
        raise RuntimeError("thread unavailable")

    controller = kc.KeycastController(session_factory=broken)
    errors = []
    controller.failed.connect(errors.append)
    controller.start({"left": 0, "top": 0, "width": 320, "height": 180}, [])
    assert errors == ["Keycast could not start. Recording continues."]
    assert controller.overlay is None and not controller.timer.isActive()


@pytest.mark.parametrize(
    "dx,dy,direction",
    [
        (0, 1, "scroll_up"),
        (0, -1, "scroll_down"),
        (-1, 0, "scroll_left"),
        (1, 0, "scroll_right"),
    ],
)
def test_scroll_callback_reports_each_direction(monkeypatch, dx, dy, direction):
    monkeypatch.setattr(kc.sys, "platform", "linux")
    hooks = {}

    def factory(**callbacks):
        hooks.update(callbacks)
        return [FakeListener(), FakeListener()]

    session = kc.InputSession(factory)
    await_condition(lambda: session.ready)
    hooks["scroll"](10, 20, dx, dy)
    assert session.drain()[0][0][1] == direction
    session.stop()


def test_stop_button_clears_overlay_before_recording_finalization(app, monkeypatch):
    import ui_elements as ui

    engine = SimpleNamespace(
        get_system_audio=lambda: False, get_mic=lambda: False, is_paused=lambda: False
    )
    pill = ui.PillWidget(engine, {"keycast_warning_dismissed": True}, pre_record=False)
    pill._keycast.session_factory = FakeSession
    pill.set_keycast_region({"left": 0, "top": 0, "width": 320, "height": 180})
    pill._btn_keycast.click()
    session = pill._keycast.session
    started = []
    worker = SimpleNamespace(
        save_finished=SimpleNamespace(connect=lambda callback: None),
        start=lambda: started.append(True),
    )
    monkeypatch.setattr(ui, "_StopWorker", lambda engine: worker)
    pill._initiate_stop()
    assert session.stopped and pill._keycast.overlay is None and started
    pill.close()


def test_overlay_is_recorded_while_pill_is_excluded(app, monkeypatch):
    import ui_elements as ui

    excluded = []
    monkeypatch.setattr(ui, "_exclude_from_capture", lambda hwnd: excluded.append(hwnd))
    engine = SimpleNamespace(
        get_system_audio=lambda: False, get_mic=lambda: False, is_paused=lambda: False
    )
    pill = ui.PillWidget(engine, {"keycast_warning_dismissed": True}, pre_record=True)
    pill.show()
    app.processEvents()
    assert int(pill.winId()) in excluded
    excluded.clear()
    overlay = kc.KeycastOverlay({"left": 0, "top": 0, "width": 320, "height": 180})
    overlay.show()
    app.processEvents()
    assert int(overlay.winId()) not in excluded
    overlay.close()
    pill._stopping = True
    pill.close()


def test_cleanup_has_bounded_stop_and_join_even_if_backend_stalls():
    session = kc.InputSession.__new__(kc.InputSession)
    session.lock = threading.Lock()
    session.cleanup_error = None
    gate = threading.Event()

    class Stuck(FakeListener):
        def stop(self):
            gate.wait(2)

    listener = Stuck()
    listener.alive = True
    before = time.monotonic()
    session._cleanup([listener], timeout=0.03)
    assert time.monotonic() - before < 0.3
    assert "timed out" in session.cleanup_error
    gate.set()

@pytest.mark.parametrize('vk,name,label',[(0x5B,'cmd','Win'),(0x5C,'cmd','Win'),(0xAD,'media_volume_mute','Mute'),(0xAE,'media_volume_down','Vol−'),(0xAF,'media_volume_up','Vol+'),(0x70,'text','F1'),(0x7B,'text','F12'),(0x87,'text','F24')])
def test_raw_windows_system_key_faces(vk,name,label):
    face=kc.key_face(key(vk=vk))
    assert (face.kind,face.text)==(name,label)


def test_held_shift_chords_keep_case_and_no_redundant_modifier_labels():
    history=kc.KeycastHistory()
    history.press(kc.KeyFace('shift','Shift'),('shift',),0)
    for index,char in enumerate('SUMIT'):
        history.press(kc.KeyFace('text',char),('shift',),2+index)
    assert len(history.keys)==5
    for entry,char in zip(history.keys,'SUMIT'):
        assert entry.faces==(kc.KeyFace('shift',''),kc.KeyFace('text',char))
    history.press(kc.KeyFace('text','s'),(),8)
    assert history.keys[-1].faces[-1].text=='s'


def test_raw_keyboard_filter_captures_system_keys_once_without_suppression(monkeypatch):
    monkeypatch.setattr(kc.sys,'platform','linux')
    hooks={}
    def factory(**callbacks):
        hooks.update(callbacks)
        return [FakeListener(),FakeListener()]
    session=kc.InputSession(factory)
    try:
        await_condition(lambda:session.ready)
        for vk in (0x5B,0xAF,0x7B):
            assert hooks['keyboard_filter'](0x100,SimpleNamespace(vkCode=vk)) is False
            assert hooks['keyboard_filter'](0x101,SimpleNamespace(vkCode=vk)) is False
        assert hooks['keyboard_filter'](0x100,SimpleNamespace(vkCode=0x41)) is True
        events,error=session.drain()
        assert error is None
        assert [event[1].text for event in events]==['Win','Vol+','F12']
        assert not session.modifiers
    finally:session.stop()
