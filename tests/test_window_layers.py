"""All transient kinds must share the same native promotion and timer protection."""
from types import SimpleNamespace
import pytest
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QMenu, QComboBox, QWidget, QToolTip, QFileDialog, QInputDialog
import window_layers


@pytest.fixture
def layers(monkeypatch):
    app = QApplication.instance()
    calls = []
    monkeypatch.setattr(window_layers, '_set_topmost', calls.append)
    policy = window_layers.install_window_layers(app)
    assert window_layers.install_window_layers(app) is policy
    yield calls
    QToolTip.hideText()
    for w in QApplication.topLevelWidgets():
        if window_layers.is_transient(w):
            w.close()
    app.processEvents()


@pytest.mark.parametrize('factory', [QDialog, QMessageBox, QMenu, QFileDialog, QInputDialog])
def test_dialog_menu_and_file_input_windows_are_promoted(layers, factory):
    box = factory()
    if isinstance(box, QFileDialog):
        box.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    box.show()
    QApplication.processEvents()
    assert int(box.winId()) in layers
    assert window_layers.transient_is_visible()
    box.close()
    box.deleteLater()


def test_combo_dropdown_uses_shared_policy(layers):
    combo = QComboBox()
    combo.addItems(['first', 'second'])
    combo.show()
    combo.showPopup()
    QApplication.processEvents()
    popup = combo.view().window()
    assert popup.isVisible()
    assert int(popup.winId()) in layers
    assert window_layers.transient_is_visible()
    combo.hidePopup()
    combo.close()
    combo.deleteLater()


def test_tooltip_is_promoted_and_all_floating_timers_yield(layers):
    import ui_elements, annotation_tool, dock_widget
    owner = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
    owner.show()
    QToolTip.showText(owner.mapToGlobal(QPoint(10, 10)), 'Visible above floating controls', owner)
    tooltip = next(w for w in QApplication.topLevelWidgets()
                   if w.isVisible() and w.windowType() == Qt.WindowType.ToolTip)
    assert int(tooltip.winId()) in layers
    assert window_layers.transient_is_visible()
    # No widget method may be reached: the shared guard must return first.
    sentinel = SimpleNamespace()
    dock_widget.DockWidget._enforce_topmost(sentinel)
    for name in ('PillWidget', 'CaptureBorderWidget'):
        cls = getattr(ui_elements, name, None)
        if cls is not None:
            cls._enforce_topmost(sentinel)
    annotation_tool.AnnotationPill._enforce_topmost(sentinel)
    QToolTip.hideText()
    owner.close()
    owner.deleteLater()


@pytest.mark.parametrize("modality", [Qt.WindowModality.WindowModal, Qt.WindowModality.ApplicationModal])
def test_prepare_dialog_applies_modality_before_topmost(modality):
    owner = QWidget(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
    box = QMessageBox(owner)
    window_layers.prepare_dialog(box, modality)
    box.show()
    assert box.windowModality() == modality
    assert box.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    box.reject()
    box.deleteLater()
    owner.deleteLater()
