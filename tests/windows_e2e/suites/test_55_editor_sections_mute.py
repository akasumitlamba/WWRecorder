"""Editor sections and selective audio functional regressions.

Purpose: exercise actual Qt buttons, fields, preview audio and timeline painting.
Preconditions: session QApplication; generated media only, no user's captures.
Pass means: edits survive tab changes; mute boundaries, removal and dirty guards
work; compact layouts keep the section controls reachable. Rendering here is
portable offscreen; native Windows animation fidelity remains separate QA.
"""
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton
from helpers.env import import_app

pytestmark = [pytest.mark.feature_editor, pytest.mark.pure_logic, pytest.mark.brute_force]

@pytest.fixture
def editor(qapp, monkeypatch):
    module = import_app('video_editor')
    window = module.VideoPlayerWindow('')
    window._thumbnails_loaded = True
    monkeypatch.setattr(window._player, 'duration', lambda: 10000)
    monkeypatch.setattr(window._player, 'position', lambda: 2000)
    window._toggle_edit_mode()
    yield window
    window._force_exit_edit_mode()
    window.close()
    QApplication.processEvents()


def test_sections_preserve_mute_edits_and_selection(editor):
    editor._editor_tabs[3].click()  # Audio
    button = next(b for b in editor.findChildren(QPushButton) if b.text() == 'Add mute section')
    button.click()
    row = editor._mute_regions_container.itemAt(0).widget()
    row._spn_start.setValue(3)
    row._spn_end.setValue(5)
    for index in (0, 3, 1, 2, 0, 2):
        editor._editor_tabs[index].click()
        assert editor._editor_pages.currentIndex() == index
        assert sum(b.isChecked() for b in editor._editor_tabs) == 1
        assert [(r.start_ms, r.end_ms) for r in editor._mute_regions] == [(3000, 5000)]
    assert editor._has_unsaved_edits()
    assert editor._timeline._mute_regions == editor._mute_regions
    editor._timeline.grab()  # Exercise the yellow-band + icon paint path.
    editor._remove_mute_region(row)
    assert not editor._has_unsaved_edits()
    assert not editor._timeline._mute_regions


@pytest.mark.parametrize('position,muted', [(1999, False), (2000, True), (3999, True), (4000, False)])
def test_preview_mute_boundaries(editor, position, muted):
    editor._add_mute_region()
    editor._on_position_changed(position)
    assert editor._audio_output.isMuted() == muted


def test_manual_preview_mute_survives_section_boundary(editor):
    editor._add_mute_region()
    editor._toggle_mute()
    editor._on_position_changed(6000)
    assert editor._audio_output.isMuted()
    editor._toggle_mute()
    editor._on_position_changed(6000)
    assert not editor._audio_output.isMuted()
    QTest.mouseClick(editor._toggle_audio, Qt.MouseButton.LeftButton)
    editor._on_position_changed(6000)
    assert not editor._audio_output.isMuted()  # Export inclusion is independent.


@pytest.mark.parametrize('width', [720, 960, 1440])
def test_editor_section_rail_is_reachable_on_resize(editor, width):
    editor.setWindowState(Qt.WindowState.WindowNoState)
    editor.resize(width, 640)
    editor.show()
    QApplication.processEvents()
    for button in editor._editor_tabs:
        assert button.isVisible()
        assert button.width() >= 44 and button.height() >= 44
    assert editor._btn_save.isVisible()
    assert editor._btn_save_as.isVisible()


def test_muted_only_edits_block_navigation_until_discard(editor, monkeypatch, tmp_path):
    module = import_app('video_editor')
    editor._add_mute_region()
    monkeypatch.setattr(module.QMessageBox, 'question', lambda *a, **k: module.QMessageBox.StandardButton.No)
    assert not editor._confirm_video_switch(str(tmp_path / 'other.mkv'))
    editor._toggle_edit_mode()
    assert editor._edit_mode and editor._mute_regions
    monkeypatch.setattr(module.QMessageBox, 'question', lambda *a, **k: module.QMessageBox.StandardButton.Yes)
    editor._toggle_edit_mode()
    assert not editor._edit_mode
    assert not editor._mute_regions and not editor._timeline._mute_regions
    assert editor._mute_regions_container.count() == 0


def test_trim_fields_and_reset_update_actual_timeline(editor):
    editor._on_duration_changed(10000)
    editor._trim_fields[0].setValue(2)
    editor._trim_fields[1].setValue(8)
    assert editor._chk_trim.isChecked()
    assert editor._timeline.get_trim() == (2000, 8000)
    assert '00:06' in editor._trim_duration_label.text()
    editor._reset_trim_range()
    assert editor._timeline.get_trim() == (0, 10000)
    assert [field.value() for field in editor._trim_fields] == [0, 10]


@pytest.mark.parametrize('field,value', [('start', 10), ('end', 0), ('start', 9.99), ('end', .05)])
def test_mute_time_fields_never_leave_source_bounds(editor, field, value):
    editor._add_mute_region()
    row = editor._mute_regions_container.itemAt(0).widget()
    getattr(row, '_spn_' + field).setValue(value)
    assert 0 <= row.item.start_ms < row.item.end_ms <= 10000
    assert abs(row._spn_start.value() * 1000 - row.item.start_ms) < 1
    assert abs(row._spn_end.value() * 1000 - row.item.end_ms) < 1


def test_mute_preview_timer_tracks_playback_and_stops_on_pause(editor):
    module = import_app('video_editor')
    editor._on_state_changed(module.QMediaPlayer.PlaybackState.PlayingState)
    assert editor._audio_mute_timer.isActive()
    assert editor._audio_mute_timer.interval() <= 25
    editor._on_state_changed(module.QMediaPlayer.PlaybackState.PausedState)
    assert not editor._audio_mute_timer.isActive()


def test_section_order_and_tab_mouse_interaction(editor):
    assert [button.text() for button in editor._editor_tabs] == ['Trim', 'Delete', 'Text', 'Audio']
    editor.show()
    QApplication.processEvents()
    for index in (3, 1, 2, 0):
        QTest.mouseClick(editor._editor_tabs[index], Qt.MouseButton.LeftButton)
        QApplication.processEvents()
        assert editor._editor_pages.currentIndex() == index
        assert editor._editor_tabs[index].isChecked()
        assert all(button.isVisible() for button in editor._editor_tabs)


def test_add_button_supports_multiple_independent_mute_sections(editor, monkeypatch):
    editor._editor_tabs[3].click()
    add = next(b for b in editor.findChildren(QPushButton) if b.text() == 'Add mute section')
    add.click()
    monkeypatch.setattr(editor._player, 'position', lambda: 6000)
    add.click()
    assert [(r.start_ms, r.end_ms) for r in editor._mute_regions] == [(2000, 4000), (6000, 8000)]
    first = editor._mute_regions_container.itemAt(0).widget()
    first._spn_end.setValue(3)
    assert [(r.start_ms, r.end_ms) for r in editor._mute_regions] == [(2000, 3000), (6000, 8000)]
    editor._remove_mute_region(first)
    assert [(r.start_ms, r.end_ms) for r in editor._mute_regions] == [(6000, 8000)]
    assert editor._mute_regions_container.count() == 1
    assert add.isEnabled()
