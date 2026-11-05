"""Keep one QApplication alive across root regressions and Windows E2E.

Recreating Qt between module-scoped fixtures can invalidate native multimedia
and widget caches. The application lives for the process; individual tests
remain responsible for closing their windows and stopping their workers.
"""
import os
import sys
import pytest


@pytest.fixture(scope='session', autouse=True)
def _session_qt_owner():
    if sys.platform != 'win32':
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([])
    if sys.platform == 'win32' and os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        # The offscreen Windows backend may enumerate no system fonts, causing
        # every digit to paint as the same missing-glyph square. Use real OS font
        # files so visual assertions test labels, not placeholder glyphs.
        from pathlib import Path
        from PyQt6.QtGui import QFontDatabase, QFont, QRawFont
        fonts = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'
        loaded = []
        for name in ('segoeui.ttf', 'seguisb.ttf', 'segoeuib.ttf', 'seguisym.ttf'):
            path = fonts / name
            if path.is_file():
                loaded.append(QFontDatabase.addApplicationFont(str(path)))
        assert any(identifier >= 0 for identifier in loaded), 'Windows headless tests require Segoe UI font files'
        font = QFont('Segoe UI', 9)
        assert QRawFont.fromFont(font).supportsCharacter(ord('0')), 'Windows test font lacks numeric glyphs'
        application.setFont(font)
    yield application
    # Do not quit/delete QApplication while other session fixture teardown runs.


# These legacy modules import Windows-only APIs during collection. Never pretend
# their implementation tests ran on Linux; retain their full Windows coverage.
collect_ignore = [] if sys.platform == 'win32' else ['test_regressions.py', 'test_voice_player_ux.py']


def pytest_collection_modifyitems(config, items):
    for item in items:
        features = sorted({m.name for m in item.iter_markers() if m.name.startswith('feature_')})
        if features:
            item.user_properties.append(('features', ','.join(features)))
    if sys.platform == 'win32':
        return
    native_startup = {'test_user_disabled_startup_cannot_be_overridden',
        'test_startup_read_does_not_reenable_external_disable',
        'test_startup_reports_actual_state', 'test_startup_timeout_cancels_operation',
        'test_packaged_startup_never_writes_run_registry',
        'test_imported_settings_are_loaded_without_losing_preferences'}
    for item in items:
        if item.path.name == 'test_distribution.py' and item.originalname in native_startup:
            item.add_marker(pytest.mark.skip(reason='WINDOWS-ONLY: Windows COM/WinRT/registry integration'))


@pytest.fixture(autouse=True)
def _unattended_dialog_guard(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox, QFileDialog, QInputDialog
    def unexpected(*args, **kwargs):
        pytest.fail('Unexpected interactive dialog/input: test must provide its own explicit response')
    monkeypatch.setattr('builtins.input', unexpected)
    for name in ('question', 'warning', 'information', 'critical', 'exec'):
        monkeypatch.setattr(QMessageBox, name, unexpected)
    for name in ('getOpenFileName', 'getOpenFileNames', 'getSaveFileName', 'getExistingDirectory'):
        monkeypatch.setattr(QFileDialog, name, unexpected)
    for name in ('getText', 'getMultiLineText', 'getItem', 'getInt', 'getDouble'):
        monkeypatch.setattr(QInputDialog, name, unexpected)
