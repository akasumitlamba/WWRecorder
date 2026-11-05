"""Delete must remain reachable above a topmost sidebar without a nested loop."""
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox
from dock_widget import RecentFilesSidebar


@pytest.fixture
def sidebar(tmp_path, monkeypatch):
    monkeypatch.setattr(RecentFilesSidebar, '_load_files', lambda self: None)
    panel = RecentFilesSidebar(str(tmp_path), close_on_focus_loss=True)
    panel.show()
    QApplication.processEvents()
    yield panel
    box = getattr(panel, '_file_dialog', None)
    if box is not None:
        box.reject()
    panel.close()
    panel.deleteLater()
    QApplication.processEvents()


@pytest.mark.parametrize('edge', ['left', 'right', 'top', 'bottom'])
def test_confirmation_is_owned_topmost_nonblocking_and_cancel_keeps_file(sidebar, tmp_path, edge):
    sidebar._edge = edge
    media = tmp_path / 'capture.png'
    media.write_bytes(b'keep this capture')
    box = sidebar._delete_file(str(media))
    QApplication.processEvents()
    assert box.isVisible()
    assert box.parentWidget() is sidebar
    assert box.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert box.windowModality() == Qt.WindowModality.WindowModal
    assert QApplication.activeModalWidget() is box
    assert sidebar.isVisible()
    assert box.defaultButton() is box.button(QMessageBox.StandardButton.No)
    assert sidebar._delete_file(str(media)) is box
    box.button(QMessageBox.StandardButton.No).click()
    QApplication.processEvents()
    assert sidebar._file_dialog is None
    assert media.read_bytes() == b'keep this capture'


@pytest.mark.parametrize('dismiss', ['escape', 'close', 'no'])
def test_dismissal_preserves_file_and_allows_another_confirmation(sidebar, tmp_path, dismiss):
    media = tmp_path / 'capture.mkv'
    media.write_bytes(b'media')
    box = sidebar._delete_file(str(media))
    if dismiss == 'escape':
        QTest.keyClick(box, Qt.Key.Key_Escape)
    elif dismiss == 'close':
        box.close()
    else:
        box.button(QMessageBox.StandardButton.No).click()
    QApplication.processEvents()
    assert media.exists()
    assert sidebar._file_dialog is None
    next_box = sidebar._delete_file(str(media))
    assert next_box is not box
    next_box.reject()


def test_explicit_yes_deletes_once_and_refreshes(sidebar, tmp_path, monkeypatch):
    media = tmp_path / 'capture.png'
    media.write_bytes(b'media')
    refreshed = []
    monkeypatch.setattr(sidebar, '_load_files', lambda: refreshed.append(True))
    box = sidebar._delete_file(str(media))
    box.button(QMessageBox.StandardButton.Yes).click()
    QApplication.processEvents()
    assert not media.exists()
    assert refreshed == [True]
    assert sidebar._file_dialog is None


def test_delete_failure_remains_visible_and_acknowledging_unlocks_sidebar(sidebar, tmp_path, monkeypatch):
    media = tmp_path / 'capture.png'
    media.write_bytes(b'media')
    def locked(*args):
        raise PermissionError('file is in use')
    monkeypatch.setattr('dock_widget.os.remove', locked)
    box = sidebar._delete_file(str(media))
    box.button(QMessageBox.StandardButton.Yes).click()
    QApplication.processEvents()
    error = sidebar._file_dialog
    assert error is not box
    assert error.isVisible()
    assert error.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert error.parentWidget() is sidebar
    assert media.exists()
    error.button(QMessageBox.StandardButton.Ok).click()
    QApplication.processEvents()
    assert sidebar._file_dialog is None


def test_real_file_menu_closes_before_delete_confirmation(sidebar, tmp_path):
    from dock_widget import _FileRow
    media = tmp_path / 'capture.png'
    media.write_bytes(b'media')
    row = _FileRow(str(media), parent=sidebar, defer_load=True)
    row.delete_requested.connect(sidebar._delete_file)
    row.show()
    row._show_actions_menu()
    QApplication.processEvents()
    menu = row._actions_menu
    action = next(action for action in menu.actions() if action.text() == 'Delete')
    action.trigger()
    QApplication.processEvents()
    assert getattr(sidebar, '_active_file_menu', None) is None
    box = sidebar._file_dialog
    assert box.isVisible()
    assert QApplication.activePopupWidget() is None
    assert QApplication.activeModalWidget() is box
    box.reject()
    row.deleteLater()
