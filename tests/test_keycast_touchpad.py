"""Real gesture/descriptor/mailbox paths; native registration is tested on Windows."""
import ctypes as C
import sys
import time
from types import SimpleNamespace
import pytest
from keycast_touchpad import Contact,ContactFrames,ScrollGesture,HidDecoder,HidCaps,ValueCaps,RawHeader,RawDevice,SUCCESS


def pair(x=.3,y=.3):return [Contact(0,x,y),Contact(1,x+.2,y)]


@pytest.mark.parametrize('dx,dy,expected',[(.02,0,'scroll_left'),(-.02,0,'scroll_right'),(0,.02,'scroll_up'),(0,-.02,'scroll_down')])
def test_touchpad_four_directions_without_any_mouse_wheel(dx,dy,expected):
    gesture=ScrollGesture()
    assert gesture.feed(pair(),1)==[]
    assert gesture.feed(pair(.3+dx,.3+dy),1.02)==[expected]


def test_natural_direction_and_small_accumulated_motion():
    gesture=ScrollGesture(natural=False)
    gesture.feed(pair(),1)
    assert not gesture.feed(pair(.3005,.3),1.01)
    assert not gesture.feed(pair(.301,.3),1.02)
    assert gesture.feed(pair(.3021,.3),1.03)==['scroll_right']
    assert gesture.feed(pair(.3021,.28),1.04)==['scroll_up']


def test_no_scroll_from_single_finger_taps_pinch_new_ids_or_time_gaps():
    gesture=ScrollGesture();gesture.feed(pair(),1)
    assert not gesture.feed([Contact(0,.28,.3),Contact(1,.52,.3)],1.01)
    assert not gesture.feed([Contact(0,.2,.3)],1.02)
    assert not gesture.feed(pair(.2,.3),1.03)
    assert not gesture.feed([Contact(4,.3,.3),Contact(5,.5,.3)],1.04)
    assert not gesture.feed([Contact(4,.4,.3),Contact(5,.6,.3)],2)
    assert not gesture.feed([],2.01)


def test_hybrid_reports_wait_for_full_frame_and_drop_incomplete_frame():
    frames=ContactFrames()
    assert frames.append(1,2,[Contact(0,.2,.3)]) is None
    complete=frames.append(1,0,[Contact(1,.4,.3)])
    assert [p.identity for p in complete]==[0,1]
    assert frames.append(1,0,[Contact(1,.5,.3)]) is None
    assert frames.append(2,2,[Contact(0,.2,.3)]) is None
    assert frames.append(3,0,[])==[]
    assert frames.append(4,99,[]) is None


class HidFixture:
    """Descriptor with report ID 7, three variable slots, arbitrary logical range."""
    def __init__(self):self.scan=1;self.count=2;self.points=pair();self.buttons=False
    def HidP_GetCaps(self,preparsed,out):
        caps=C.cast(out,C.POINTER(HidCaps)).contents
        caps.UsagePage=13;caps.Usage=5;caps.NumberInputValueCaps=11
        return SUCCESS
    def HidP_GetValueCaps(self,kind,values,count,preparsed):
        specs=[(0,13,0x56),(0,13,0x54)]+[(link,page,usage) for link in [1,2,3] for page,usage in [(13,0x51),(1,0x30),(1,0x31)]]
        for cap,(link,page,usage) in zip(values,specs):
            cap.ReportID=7;cap.LinkCollection=link;cap.UsagePage=page;cap.UsageInfo[0]=usage
            cap.LogicalMin=0;cap.LogicalMax=10000
        return SUCCESS
    def HidP_GetUsageValue(self,kind,page,link,usage,out,*args):
        if link==0:value=self.scan if usage==0x56 else self.count
        elif link<=len(self.points):
            point=self.points[link-1];value=point.identity if usage==0x51 else int((point.x if usage==0x30 else point.y)*10000)
        else:value=0
        C.cast(out,C.POINTER(C.c_uint32))[0]=value;return SUCCESS
    def HidP_GetUsages(self,kind,page,link,values,count,*args):
        active=([1] if self.buttons else []) if page==9 else ([0x42,0x47] if link<=len(self.points) and self.points[link-1].active else [])
        for i,value in enumerate(active):values[i]=value
        C.cast(count,C.POINTER(C.c_uint32))[0]=len(active);return SUCCESS


def test_real_decoder_uses_descriptor_and_ignores_empty_contact_slots():
    hid=HidFixture();decoder=HidDecoder(hid,b'fixture')
    assert not decoder.decode(b'\x07\x00',1)
    hid.scan+=1;hid.points=pair(.3,.32)
    assert decoder.decode(b'\x07\x00',1.02)==['scroll_up']
    hid.scan+=1;hid.points=pair(.32,.32)
    assert decoder.decode(b'\x07\x00',1.04)==['scroll_left']
    hid.buttons=True;hid.scan+=1;hid.points=pair(.34,.32)
    assert not decoder.decode(b'\x07\x00',1.06)
    assert not decoder.decode(b'\x09\x00',1.08)


def test_touchpad_callback_flows_through_actual_session_mailbox(monkeypatch):
    import keycast
    monkeypatch.setattr(keycast.sys,'platform','linux');callbacks={}
    class Listener:
        def start(self):pass
        def stop(self):pass
        def join(self,timeout=None):pass
        def is_alive(self):return True
    def factory(**kwargs):callbacks.update(kwargs);return [Listener()]
    session=keycast.InputSession(factory)
    deadline=time.monotonic()+2
    while not session.ready and time.monotonic()<deadline:time.sleep(.005)
    assert session.ready
    for direction in ['scroll_up','scroll_down','scroll_left','scroll_right']:
        callbacks['touchpad_scroll'](direction,-300,50,1)
    events,error=session.drain()
    assert not error and [e[1] for e in events]==['scroll_up','scroll_down','scroll_left','scroll_right']
    session.stop();callbacks['touchpad_scroll']('scroll_up',0,0,2)
    assert session.drain()[0]==[]


@pytest.mark.skipif(sys.platform!='win32',reason='Windows raw-input registration requires user32/HID')
def test_native_touchpad_registration_stop_and_restart_without_device():
    from keycast_touchpad import WindowsTouchpadListener
    user=C.WinDLL('user32',use_last_error=True)
    user.GetRegisteredRawInputDevices.argtypes=[C.POINTER(RawDevice),C.POINTER(C.c_uint32),C.c_uint32]
    user.GetRegisteredRawInputDevices.restype=C.c_uint32
    assert C.sizeof(HidCaps)==64 and C.sizeof(ValueCaps)==72
    assert C.sizeof(RawHeader)==24 and C.sizeof(RawDevice)==16
    def registrations():
        count=C.c_uint32()
        result=user.GetRegisteredRawInputDevices(None,C.byref(count),C.sizeof(RawDevice))
        assert result!=0xFFFFFFFF
        if count.value==0:return []
        values=(RawDevice*count.value)()
        result=user.GetRegisteredRawInputDevices(values,C.byref(count),C.sizeof(RawDevice))
        assert result!=0xFFFFFFFF
        return [r for r in values[:count.value] if (r.usUsagePage,r.usUsage)==(13,5)]
    first=WindowsTouchpadListener(lambda *_:None);second=WindowsTouchpadListener(lambda *_:None)
    try:
        first.start();assert first.prepared.wait(4) and not first.failure
        assert any(r.hwndTarget==first.hwnd and r.dwFlags&0x100 for r in registrations())
        first.stop();second.start()
        assert second.prepared.wait(4) and not second.failure
        first.join(3);assert not first.is_alive()
        assert any(r.hwndTarget==second.hwnd for r in registrations())
    finally:
        first.stop();second.stop()
        for listener in [first,second]:
            if listener.ident is not None:listener.join(4)
    assert not first.is_alive() and not second.is_alive()
    assert not registrations()


def test_raw_hid_packet_reaches_scroll_feedback_without_mouse_hook():
    """Exercise real bounded packet extraction, descriptor decoder and gesture path."""
    import struct
    from ctypes import wintypes
    from keycast_touchpad import WindowsTouchpadListener
    hid=HidFixture();events=[]
    listener=WindowsTouchpadListener(lambda *event:events.append(event));listener.hid=hid;listener.natural=True
    class User:
        malformed=False
        def GetRawInputData(self,handle,command,out,length,header_size):
            size=C.sizeof(RawHeader)+8+2
            if out is None:C.cast(length,C.POINTER(C.c_uint32))[0]=size;return 0
            header=RawHeader(2,size,123,0)
            packet=bytes(header)+struct.pack('<II',99 if self.malformed else 2,1)+b'\x07\x00'
            C.memmove(out,packet,len(packet));return len(packet)
        def GetRawInputDeviceInfoW(self,device,command,out,length):
            if out is None:C.cast(length,C.POINTER(C.c_uint32))[0]=8;return 0
            C.memmove(out,b'fixture\0',8);return 8
        def GetCursorPos(self,out):
            point=C.cast(out,C.POINTER(wintypes.POINT)).contents;point.x=-300;point.y=42;return 1
    listener.user=User();listener._read(1)
    assert not events
    hid.scan+=1;hid.points=pair(.3,.32);listener._read(2)
    assert events[0][:3]==('scroll_up',-300,42)
    listener.user.malformed=True;hid.scan+=1;hid.points=pair(.3,.34);listener._read(3)
    assert len(events)==1
    listener.closed.set();listener.user.malformed=False;listener._read(4)
    assert len(events)==1
