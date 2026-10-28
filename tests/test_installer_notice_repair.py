"""Packaging failures, requested control artwork, and safe notification lifecycle."""
import os,sys,ast,importlib.util
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from types import SimpleNamespace
import pytest
from PyQt6.QtCore import Qt,QRect,QPointF
from PyQt6.QtWidgets import QApplication,QWidget
from PyQt6.QtGui import QColor,QPixmap
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])

def payload_module():
    spec=importlib.util.spec_from_file_location('payload_validator',ROOT/'scripts/validate_payload.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

@pytest.mark.parametrize('missing',['modules','Qt6Core.dll','qwindows.dll','undo.png',None])
def test_payload_gate_rejects_incomplete_qt(tmp_path,monkeypatch,missing):
    mod=payload_module();(tmp_path/'WWRecorder.exe').write_bytes(b'executable')
    for name in list(mod.REQUIRED_NATIVE)+['undo.png','redo.png']:
        if name==missing:continue
        path=tmp_path/'icons/modern'/name if name.endswith('.png') else tmp_path/name
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
    import PyInstaller.archive.readers
    modules=mod.REQUIRED_QT if missing!='modules' else set()
    monkeypatch.setattr(mod,'ZlibArchiveReader',lambda path:SimpleNamespace(toc=dict.fromkeys(modules)))
    archive=lambda path:SimpleNamespace(toc={'PYZ.pyz':None},extract=lambda name:b'pyz')
    if missing:
        with pytest.raises(ValueError,match='Incomplete frozen payload'):mod.validate_payload(tmp_path,archive)
    else:assert mod.validate_payload(tmp_path,archive)['validated']

def test_build_gates_run_before_both_packagers():
    script=(ROOT/'scripts/build-distributions.ps1').read_text(encoding='utf-8')
    assert script.index('from PyQt6 import')<script.index('-m PyInstaller')
    assert script.index('scripts/validate_payload.py')<script.index("$Format -in @('Both','Msix')")
    assert '--distribution-smoke-test' in script and 'WaitForExit(15000)' in script


def test_record_camera_and_eraser_crosshair_keep_toolbar_icon(app):
    from icon_theme import asset_path
    from annotation_tool import get_tool_cursor,_AnnotationToolBtn
    from tool_cursors import tool_cursor
    assert Path(asset_path('record.png'))==ROOT/'app/icons/record.png'
    cursor=get_tool_cursor('eraser',QColor('red'))
    assert cursor.hotSpot()==tool_cursor('crosshair').hotSpot()
    assert cursor.pixmap().toImage()==tool_cursor('crosshair').pixmap().toImage()
    button=_AnnotationToolBtn('eraser.png','Eraser');assert not button.icon().isNull();button.close()


def success_class():
    # Load the real UI class without importing Windows capture dependencies.
    from PyQt6 import QtCore,QtGui,QtWidgets
    tree=ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='_SuccessNotification')
    env={}
    for module in (QtCore,QtGui,QtWidgets):env.update(vars(module))
    env.update({'Path':Path,'os':os,'_screen_for_anchor':lambda point:SimpleNamespace(availableGeometry=lambda:QRect(-800,0,800,600)), '_available_media_path':lambda path:path})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls],type_ignores=[])),'success-notice','exec'),env)
    return env['_SuccessNotification']


def test_saved_notification_visual_bounds_actions_and_dismiss_once(app,tmp_path):
    cls=success_class();notice=cls(str(tmp_path/'long-capture-file-name.png'),'Screenshot saved','long-capture-file-name.png',duration=30000)
    notice._play_sound=lambda:None
    opened=[];notice.open_clicked.connect(opened.append)
    notice.show_notification();app.processEvents()
    card=notice.findChild(QWidget,'notifContainer')
    assert '#151923' in card.styleSheet() and '#424B5D' in card.styleSheet()
    assert QRect(-800,0,800,600).contains(notice.geometry())
    notice._toggle_rename();assert notice._is_renaming and not notice._auto_timer.isActive()
    notice._toggle_rename();assert not notice._is_renaming
    notice._on_open();animation=notice._fade_out;notice._dismiss()
    assert notice._fade_out is animation and opened==[str(tmp_path/'long-capture-file-name.png')]
    notice._fade_out.stop();notice.close()

@pytest.mark.parametrize('scale',[.5,1,2,4])
def test_photo_eraser_radius_uses_image_local_stroke_width(app,tmp_path,scale):
    from annotation_tool import _DrawingArea
    path=tmp_path/'sample.png';pix=QPixmap(200,150);pix.fill(QColor('white'));pix.save(str(path))
    canvas=_DrawingArea(str(path));canvas._scale=scale
    item={'type':'highlighter','points':[(20,50),(120,50)],'width':40,'color':'#FFFF00'}
    assert canvas._hit_test(QPointF(70,65),item)
    canvas.close()


def test_live_pill_close_requests_save_instead_of_discard():
    tree=ast.parse((ROOT/'app/ui_elements.py').read_text(encoding='utf-8'));cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='PillWidget');method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='closeEvent')
    # Live close returns before QWidget's base event handler.
    env={};exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),'pill-close','exec'),env)
    calls=[];owner=SimpleNamespace(_preparing=False,_stopping=False,_pre_record=False,_engine=SimpleNamespace(is_recording=lambda:True),_initiate_stop=lambda:calls.append('save'),_initiate_discard=lambda **kw:calls.append('discard'))
    event=SimpleNamespace(ignore=lambda:calls.append('ignored'))
    env['closeEvent'](owner,event);assert calls==['ignored','save']

@pytest.mark.parametrize('url',['https://github.com.evil.example/a.exe','https://evil.example/github.com/a.exe','https://github.com/someone/other/releases/download/v2/a.exe'])
def test_update_downloader_rejects_unofficial_origins(monkeypatch,url):
    import updater
    monkeypatch.setattr(updater,'is_packaged',lambda:False)
    monkeypatch.setattr(updater.urllib.request,'urlopen',lambda *a,**kw:pytest.fail('Unexpected network request'))
    worker=updater.InstallerDownloader(url);failed=[];worker.download_failed.connect(failed.append);worker.run();assert failed


def test_installer_dpi_and_style_keep_checkbox_space():
    script=(ROOT/'packaging/exe/installer_config.iss').read_text(encoding='utf-8')
    assert 'WizardStyle=modern dark windows11' in script
    assert 'TasksList.MinItemHeight := ScaleY(26)' in script
    assert 'ComponentsList.MinItemHeight := ScaleY(26)' in script
    assert 'TasksList.Offset := ScaleX(8)' in script


def test_saved_notice_shows_real_thumbnail_and_late_preview(app,tmp_path):
    cls=success_class();image=QPixmap(160,90);image.fill(QColor('#267DA4'))
    notice=cls(str(tmp_path/'capture.png'),'Screenshot saved','capture.png',image)
    assert not notice._thumb_lbl.pixmap().isNull()
    assert notice._thumb_lbl.pixmap().width()==80
    assert notice._thumb_lbl.pixmap().toImage().pixelColor(20,20)==QColor('#267DA4')
    late=QPixmap(160,90);late.fill(QColor('#DE6472'));notice.set_thumbnail(late)
    assert notice._thumb_lbl.pixmap().toImage().pixelColor(20,20)==QColor('#DE6472')
    notice.close()


def test_confirmation_check_is_geometric_and_not_font_dependent(app):
    from icon_theme import asset_path
    from PyQt6.QtGui import QImage
    image=QImage(asset_path('apply.png'))
    assert image.size().width()==64 and image.pixelColor(0,0).alpha()==0
    assert image.pixelColor(26,43).alpha()>200
    svg=(ROOT/'app/icons/modern/apply.svg').read_text(encoding='utf-8')
    assert 'M14 33 L26 45 L50 21' in svg and '<text' not in svg


def test_installer_artwork_and_copy_are_wired_into_native_wizard():
    script=(ROOT/'packaging/exe/installer_config.iss').read_text(encoding='utf-8')
    assert 'WizardImageFile={#RepoRoot}packaging\\exe\\assets\\welcome.png' in script
    assert 'WizardImageStretch=yes' in script
    assert 'WizardSelectTasks=Additional options' in script
    assert 'SelectTasksDesc=Choose how WWRecorder starts and where shortcuts appear.' in script
    from PIL import Image
    image=Image.open(ROOT/'packaging/exe/assets/welcome.png')
    assert image.width < image.height
    assert image.width >= 164 and image.height >= 314
