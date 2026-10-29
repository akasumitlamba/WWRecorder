"""Compact notifications, panel identity, dock text states and bounded annotation geometry."""
import json
from pathlib import Path
import pytest
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QPushButton
from PyQt6.QtTest import QTest
from helpers.env import import_app
from helpers.action_matrix import FakeRecordingEngine

pytestmark = [pytest.mark.pure_logic, pytest.mark.feature_ui]


def test_saved_notice_has_one_small_dismiss_button_and_recent_files_hint(qapp,tmp_path):
    main=import_app('main')
    thumb=QPixmap(160,90);thumb.fill(QColor('#267DA4'))
    notice=main._SuccessNotification(str(tmp_path/'capture.mkv'),'Recording saved','capture.mkv',thumb)
    notice._play_sound=lambda:None
    notice.show_notification();QTest.qWait(30)
    dismiss=[b for b in notice.findChildren(QPushButton) if 'notification' in b.toolTip()]
    assert len(dismiss)==1 and dismiss[0].size().width()==20 and dismiss[0].iconSize().width()==12
    assert any('Recent Files' in x.text() for x in notice.findChildren(QLabel))
    assert notice.height()<=115 and not notice._thumb_lbl.pixmap().isNull()
    closed=[];notice.destroyed.connect(lambda:closed.append(True))
    dismiss[0].click();QTest.qWait(250);assert closed


@pytest.mark.parametrize('edge',['left','right','top','bottom'])
@pytest.mark.parametrize('settings',[False,True])
def test_headers_never_overlap_brand_with_section_names(qapp,tmp_path,edge,settings):
    dock=import_app('dock_widget')
    panel=dock.SettingsSidebar({},edge=edge) if settings else dock.RecentFilesSidebar(str(tmp_path),edge=edge)
    panel.show();qapp.processEvents()
    labels=panel._heading_container.findChildren(QLabel)
    assert not any(x.text()=='Gallery' for x in labels)
    titles=[x for x in labels if x.text() in ('Recent Files','Settings')]
    assert len(titles)==int(edge in ('top','bottom'))
    brand=next(x for x in labels if not x.pixmap().isNull())
    for title in titles:assert not title.geometry().intersects(brand.geometry())
    panel.close()


@pytest.mark.parametrize('edge',['left','right','top','bottom'])
def test_original_grabber_is_compact_and_recording_changes_only_dots(qapp,edge):
    dock=import_app('dock_widget').DockWidget(FakeRecordingEngine(),{'dock_edge':edge})
    dock._acknowledge_startup_indicator();dock.set_recording_state(True)
    dock._pulse_timer.stop();dock.show();qapp.processEvents()
    dock._pulse_visible=True;lit=dock.grab().toImage()
    dock._pulse_visible=False;dim=dock.grab().toImage()
    assert sorted([dock.width(),dock.height()])==[12,48]
    assert lit!=dim
    dock.close()


@pytest.mark.parametrize('width,height',[(800,600),(1920,1080),(3440,1440),(5120,1440),(7680,2160)])
@pytest.mark.parametrize('orientation',['horizontal','vertical'])
def test_annotation_strip_has_readable_bounded_dimensions(qapp,width,height,orientation):
    pill=import_app('annotation_tool').AnnotationPill()
    bounds=QRect(-width,0,width,height)
    pill._apply_orientation(orientation,bounds)
    size=pill.sizeHint()
    length=size.width() if orientation=='horizontal' else size.height()
    thickness=size.height() if orientation=='horizontal' else size.width()
    assert length<=min(720 if orientation=='horizontal' else 840,(width if orientation=='horizontal' else height)-16)
    assert 28<=thickness<=44
    assert all(button.width()>=20 for button in pill._sized_buttons)
    pill.close()


def test_processing_mentions_compression_without_duplicate_dismiss_controls(qapp):
    popup=import_app('processing_notice').ProcessingNotice()
    popup.show_saving();qapp.processEvents()
    assert 'Compressing video and audio'==popup._sub_lbl.text()
    assert 'Recent Files' in popup._message.text()
    assert len(popup.findChildren(QPushButton))==1
    assert popup.height()<100
    popup._btn_close.click();assert not popup.isVisible() and not popup._activity._timer.isActive()


def test_store_staging_uses_production_identity_and_store_version(tmp_path):
    import subprocess,sys,xml.etree.ElementTree as ET
    root=Path(__file__).resolve().parents[3]
    payload=tmp_path/'payload';payload.mkdir();(payload/'WWRecorder.exe').write_bytes(b'fixture payload')
    stage=tmp_path/'store-stage'
    result=subprocess.run([sys.executable,str(root/'packaging/msix/stage_msix.py'),
        '--payload',str(payload),'--stage',str(stage),'--identity',str(root/'packaging/msix/store-identity.json'),
        '--version','1.7.1.0'],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    manifest=ET.parse(stage/'AppxManifest.xml')
    ns={'m':'http://schemas.microsoft.com/appx/manifest/foundation/windows10'}
    identity=manifest.find('m:Identity',ns).attrib
    assert identity['Name']=='akasumitlamba.WWRecorder' and identity['Version']=='1.7.1.0'
    assert identity['Publisher']=='CN=64C690B8-C074-47EB-958F-BE7C2648E60E'
    config=json.loads((stage/'distribution.json').read_text())
    assert config['channel']=='store' and config['store_product_id']=='9PBS5VDWFXND'
    assert not list(stage.rglob('*.cer')) and not list(stage.rglob('*.pfx'))
