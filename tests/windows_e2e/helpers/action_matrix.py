"""Shared catalogues and fakes for brute-force / combinatorial E2E matrices.

Purpose
-------
Keep “toggle every control × save/cancel/Escape × busy-state” suites DRY.
Each catalogue entry documents the widget/action id, config key (if any), and
what pass means for persistence.

How to extend
-------------
1. Add a frozen dataclass / tuple row here with ``action_id``.
2. Add the id to ``ACTION_INVENTORY.md``.
3. Parametrize a suite with ``@pytest.mark.parametrize`` over the catalogue.
4. Prefer ``assert_invariant(..., widget=..., state=...)`` so failures name the
   control and pre-action state.

Windows-only notes
------------------
Widget construction may use offscreen Qt (safe on Linux cloud agents). Real
capture / tray / global hotkey / mic hotplug still belongs under
``windows_gui`` / ``windows_native``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SettingsToggle:
    """One SettingsSidebar draft toggle."""

    action_id: str
    attr: str  # widget attribute on SettingsSidebar
    config_key: str
    default: bool
    label: str


# Defaults match app/main.py DEFAULT_CONFIG (verified by test_03).
SETTINGS_TOGGLES: tuple[SettingsToggle, ...] = (
    SettingsToggle("settings.clipboard", "_chk_clip", "copy_to_clipboard", True, "Auto-copy captures to clipboard"),
    SettingsToggle("settings.sys_audio", "_chk_sys", "default_system_audio", False, "Record system sound by default"),
    SettingsToggle("settings.mic", "_chk_mic", "default_mic", False, "Record mic audio by default"),
    SettingsToggle("settings.autoclose", "_chk_autoclose", "close_on_focus_loss", True, "Auto-close panel on focus loss"),
    SettingsToggle("settings.hide_drag", "_chk_hide_drag", "hide_panel_on_drag", False, "Hide panel when dragging files"),
    SettingsToggle("settings.boot", "_chk_boot", "start_on_boot", False, "Start WWRecorder with Windows"),
    SettingsToggle("settings.dev_mode", "_chk_developer_mode", "developer_mode", False, "Developer mode"),
)


@dataclass(frozen=True)
class SettingsCombo:
    action_id: str
    attr: str
    config_key: str
    values: tuple[str, ...]
    default: str


SETTINGS_COMBOS: tuple[SettingsCombo, ...] = (
    SettingsCombo(
        "settings.dock_edge",
        "_cmb_dock_position",
        "dock_edge",
        ("left", "right", "top", "bottom"),
        "right",
    ),
)


@dataclass(frozen=True)
class DockAction:
    action_id: str
    button_attr: str
    signal_attr: str
    label: str


DOCK_ACTIONS: tuple[DockAction, ...] = (
    DockAction("dock.screenshot", "_btn_screenshot", "screenshot_requested", "Screenshot"),
    DockAction("dock.record", "_btn_record", "record_requested", "Record"),
    DockAction("dock.annotate", "_btn_annotate", "annotate_requested", "Annotate"),
    DockAction("dock.files", "_btn_files", "files_requested", "Recent Files"),
    DockAction("dock.settings", "_btn_settings", "settings_requested", "Settings"),
)


PILL_TOGGLE_ATTRS: tuple[tuple[str, str], ...] = (
    ("pill.sys_audio", "_btn_sys"),
    ("pill.mic", "_btn_mic"),
    ("pill.keycast", "_btn_keycast"),
    ("pill.annotate", "_btn_annotate"),
)


# Photo AnnotateWindow toolbar tool ids (see annotation_tool.AnnotateWindow._build_ui).
ANNOTATION_TOOLS: tuple[str, ...] = (
    "pencil",
    "highlighter",
    "eraser",
    "text",
    "circle",
    "rect",
    "arrow",
)

# Live overlay adds laser; selection is an interaction mode, not a toolbar tool id.
LIVE_ANNOTATION_TOOLS: tuple[str, ...] = ANNOTATION_TOOLS + ("laser",)


# Exit paths for draft panels. ``save`` persists; others must discard draft.
EXIT_PATHS: tuple[str, ...] = (
    "escape",
    "close_without_save",
    "close_panel",
    "save",
)


BUSY_STATES: tuple[str, ...] = (
    "idle",
    "preparing",
    "recording",
    "paused",
    "finalizing",
)


# (region dict, expect_accepted) for _normalized_capture_plan / build_capture_plan.
CAPTURE_PLAN_CASES: tuple[tuple[dict, bool], ...] = (
    ({"left": 0, "top": 0, "width": 160, "height": 120}, True),
    ({"left": -900, "top": -50, "width": 200, "height": 100}, True),
    ({"left": 0, "top": 0, "width": 1, "height": 100}, False),
    ({"left": 0, "top": 0, "width": 100, "height": 1}, False),
    ({"left": 0, "top": 0, "width": 31, "height": 31}, False),  # below 32px after even clamp
    ({"left": 0, "top": 0, "width": 33, "height": 33}, True),  # becomes 32x32
    ({"left": 10, "top": 10, "width": 101, "height": 99}, True),  # even dims
)


class FakeRecordingEngine:
    """Minimal engine stub for PillWidget / dock construction and toggle spam."""

    def __init__(self):
        self._sys = False
        self._mic = False
        self._paused = False
        self._recording = False
        self._prewarming = False
        self._microphone_id = ""
        self._microphone_name = "Same as Windows"
        self._mic_fallback = False
        self._microphone_failed = False
        self.discard_calls = 0
        self.pause_calls = 0
        self.resume_calls = 0
        self.stop_capture_calls = 0
        self.mux_calls = 0
        self._last_error = ""
        self._runtime_events: list[tuple[str, str]] = []

    def get_system_audio(self):
        return self._sys

    def get_mic(self):
        return self._mic

    def set_system_audio(self, value: bool):
        self._sys = bool(value)

    def set_mic(self, value: bool):
        self._mic = bool(value)

    def set_microphone(self, device_id, name):
        self._microphone_id = device_id
        self._microphone_name = name

    def list_microphones(self):
        return []

    def is_paused(self):
        return self._paused

    def is_recording(self):
        return self._recording

    def is_prewarming(self):
        return self._prewarming

    def pause(self):
        self.pause_calls += 1
        self._paused = True

    def resume(self):
        self.resume_calls += 1
        self._paused = False

    def discard(self):
        self.discard_calls += 1
        self._recording = False
        self._paused = False
        self._prewarming = False

    def stop_capture(self):
        self.stop_capture_calls += 1
        self._recording = False

    def mux_and_save(self):
        self.mux_calls += 1
        return ""

    def drain_runtime_events(self):
        events = list(self._runtime_events)
        self._runtime_events.clear()
        return events


def base_settings_config(**overrides) -> dict:
    """Config dict suitable for SettingsSidebar (includes current_version)."""
    from helpers.env import import_app

    main_mod = import_app("main")
    cfg = dict(main_mod.DEFAULT_CONFIG)
    cfg["current_version"] = main_mod.APP_VERSION
    cfg.update(overrides)
    return cfg


def make_settings_sidebar(qapp, **overrides):
    """Build SettingsSidebar + mutable persisted mirror updated only on Save.

    Returns ``(sidebar, persisted_cfg, saved_payloads)``.
    ``persisted_cfg`` starts as the constructor config and is updated only when
    ``settings_saved`` fires — models “disk” for draft-until-Save tests.
    """
    from helpers.env import import_app

    dock_widget = import_app("dock_widget")
    main_mod = import_app("main")
    cfg = base_settings_config(**overrides)
    persisted = dict(cfg)
    saved_payloads: list[dict] = []
    sidebar = dock_widget.SettingsSidebar(cfg, default_config=main_mod.DEFAULT_CONFIG)

    def _on_saved(payload: dict):
        saved_payloads.append(dict(payload))
        persisted.clear()
        persisted.update(payload)

    sidebar.settings_saved.connect(_on_saved)
    qapp.processEvents()
    # Ensure Save starts disabled (clean draft).
    sidebar._check_dirty()
    return sidebar, persisted, saved_payloads


def reopen_settings(qapp, persisted: dict):
    """Open a new SettingsSidebar from the last-persisted config (cancel path)."""
    from helpers.env import import_app

    dock_widget = import_app("dock_widget")
    main_mod = import_app("main")
    sidebar = dock_widget.SettingsSidebar(dict(persisted), default_config=main_mod.DEFAULT_CONFIG)
    qapp.processEvents()
    sidebar._check_dirty()
    return sidebar


def make_pill(qapp, *, pre_record: bool = True, **config_overrides):
    from helpers.env import import_app

    ui = import_app("ui_elements")
    main_mod = import_app("main")
    engine = FakeRecordingEngine()
    cfg = dict(main_mod.DEFAULT_CONFIG)
    # Consent UI has its own explicit accept/cancel tests; this matrix tests armed controls.
    cfg["keycast_warning_dismissed"] = True
    cfg.update(config_overrides)
    pill = ui.PillWidget(engine, cfg, pre_record=pre_record)
    qapp.processEvents()
    return pill, engine


def make_dock(qapp, **config_overrides):
    from helpers.env import import_app

    dock_widget = import_app("dock_widget")
    main_mod = import_app("main")
    engine = FakeRecordingEngine()
    cfg = dict(main_mod.DEFAULT_CONFIG)
    cfg.update(config_overrides)
    dock = dock_widget.DockWidget(engine, cfg)
    qapp.processEvents()
    return dock, engine


def read_toggle(sidebar, attr: str) -> bool:
    return bool(getattr(sidebar, attr).isChecked())


def set_toggle(sidebar, attr: str, value: bool) -> None:
    widget = getattr(sidebar, attr)
    widget.setChecked(bool(value))
    # toggled signal should call _check_dirty; force for safety.
    sidebar._check_dirty()


def is_settings_dirty(sidebar) -> bool:
    return bool(sidebar._btn_save.isEnabled())


def apply_settings_exit(sidebar, exit_id: str) -> None:
    """Apply an exit path against an open SettingsSidebar draft.

    ``escape`` / ``close_panel`` / ``close_without_save`` must NOT call ``_save``.
    ``save`` persists via ``_save``.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QApplication

    if exit_id == "save":
        sidebar._save()
    elif exit_id == "escape":
        event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        sidebar.keyPressEvent(event)
    elif exit_id in ("close_without_save", "close_panel"):
        if hasattr(sidebar, "close_panel"):
            sidebar.close_panel(animate=False)
        else:
            sidebar.close()
    else:
        raise ValueError(f"unknown exit_id={exit_id!r}")
    QApplication.processEvents()


def spam_clicks(widget, times: int = 5) -> None:
    """Fire clicked rapidly; caller asserts no crash / idempotent guards."""
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    for _ in range(times):
        if hasattr(widget, "click"):
            widget.click()
        else:
            QTest.mouseClick(
                widget,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                QPoint(max(1, widget.width() // 2), max(1, widget.height() // 2)),
            )
        QApplication.processEvents()


def assert_invariant(condition: bool, message: str, *, widget: str = "", state: str = "") -> None:
    """Fail with actionable context: widget id + state before/during action."""
    if condition:
        return
    parts = [message]
    if widget:
        parts.append(f"widget={widget}")
    if state:
        parts.append(f"state={state}")
    raise AssertionError(" | ".join(parts))
