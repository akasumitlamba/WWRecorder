"""Passive Windows precision-touchpad feedback for Keycast.

Raw HID input complements mouse hooks: Windows can route two-finger gestures
straight to the target application's manipulation stack without a wheel hook.
Only the digitizer/touchpad collection is registered; no input is suppressed,
injected, redirected or persisted. This module never creates Qt objects.
"""
from dataclasses import dataclass
import ctypes as C
import math
import struct
import threading
import time

U16=C.c_uint16
U32=C.c_uint32
I32=C.c_int32
PTR=C.c_void_p
SUCCESS=0x00110000


class HidCaps(C.Structure):
    _fields_=[('Usage',U16),('UsagePage',U16),('InputReportByteLength',U16),
              ('OutputReportByteLength',U16),('FeatureReportByteLength',U16),
              ('Reserved',U16*17)]+[(name,U16) for name in (
                  'NumberLinkCollectionNodes','NumberInputButtonCaps','NumberInputValueCaps',
                  'NumberInputDataIndices','NumberOutputButtonCaps','NumberOutputValueCaps',
                  'NumberOutputDataIndices','NumberFeatureButtonCaps','NumberFeatureValueCaps',
                  'NumberFeatureDataIndices')]


class ValueCaps(C.Structure):
    _fields_=[('UsagePage',U16),('ReportID',C.c_ubyte),('IsAlias',C.c_ubyte),
              ('BitField',U16),('LinkCollection',U16),('LinkUsage',U16),('LinkUsagePage',U16),
              ('IsRange',C.c_ubyte),('IsStringRange',C.c_ubyte),
              ('IsDesignatorRange',C.c_ubyte),('IsAbsolute',C.c_ubyte),
              ('HasNull',C.c_ubyte),('Reserved',C.c_ubyte),('BitSize',U16),
              ('ReportCount',U16),('Reserved2',U16*5),('UnitsExp',U32),('Units',U32),
              ('LogicalMin',I32),('LogicalMax',I32),('PhysicalMin',I32),('PhysicalMax',I32),
              ('UsageInfo',U16*8)]


class RawHeader(C.Structure):
    _fields_=[('dwType',U32),('dwSize',U32),('hDevice',PTR),('wParam',C.c_size_t)]


class RawDevice(C.Structure):
    _fields_=[('usUsagePage',U16),('usUsage',U16),('dwFlags',U32),('hwndTarget',PTR)]


@dataclass(frozen=True)
class Contact:
    identity:int
    x:float
    y:float
    active:bool=True


class ContactFrames:
    """Assemble hybrid HID reports; never infer motion from a partial frame."""
    def __init__(self):
        self.scan=None
        self.expected=0
        self.pending={}
        self.complete=False

    def append(self,scan,count,contacts):
        if not 0<=count<=5:
            self.scan=None;self.pending.clear();return None
        if scan!=self.scan:
            self.scan=scan;self.expected=count;self.pending={};self.complete=False
        elif self.complete:
            return None
        elif count:
            self.expected=count
        if self.expected==0:
            self.complete=True
            return []
        for contact in contacts:
            old=self.pending.get(contact.identity)
            if old is None or contact.active or not old.active:
                self.pending[contact.identity]=contact
        if len(self.pending)<self.expected:
            return None
        if len(self.pending)>self.expected:
            self.pending.clear();self.complete=True;return None
        self.complete=True
        return list(self.pending.values())


class ScrollGesture:
    """Track common two-finger translation, ignoring taps, palms and pinches."""
    def __init__(self,natural=True,threshold=.002):
        self.natural=natural
        self.threshold=threshold
        self.previous={}
        self.accum=[0.,0.]
        self.last_at=None

    def feed(self,contacts,now):
        current={p.identity:p for p in contacts if p.active}
        valid=(len(current)==2 and current.keys()==self.previous.keys()
               and self.last_at is not None and 0<=now-self.last_at<.25)
        previous=self.previous;self.previous=current;self.last_at=now
        if not valid:
            self.accum=[0.,0.];return []
        deltas=[(p.x-previous[i].x,p.y-previous[i].y) for i,p in current.items()]
        dx=sum(p[0] for p in deltas)/2;dy=sum(p[1] for p in deltas)/2
        # Opposing motion is pinch/rotation, not a scroll. A large discontinuity
        # is a new contact/frame gap, not a huge gesture.
        divergent=math.hypot(deltas[0][0]-deltas[1][0],deltas[0][1]-deltas[1][1])
        movement=math.hypot(dx,dy)
        if movement>.15 or divergent>max(.003,movement):
            self.accum=[0.,0.];return []
        self.accum[0]+=dx;self.accum[1]+=dy
        result=[]
        for axis in (0,1):
            value=self.accum[axis]
            if abs(value)<self.threshold:continue
            # Arrows describe Windows scroll direction, honoring the user's
            # PrecisionTouchPad ScrollDirection setting on both axes.
            positive=value>0
            if self.natural:positive=not positive
            result.append(('scroll_right' if positive else 'scroll_left') if axis==0
                          else ('scroll_down' if positive else 'scroll_up'))
            self.accum[axis]=0.
        return result


class HidDecoder:
    """Use each device's HID descriptor, never hard-coded byte offsets."""
    def __init__(self,hid,preparsed):
        self.hid=hid;self.preparsed=preparsed;self.frames=ContactFrames();self.gesture=ScrollGesture()
        caps=HidCaps()
        if hid.HidP_GetCaps(preparsed,C.byref(caps))!=SUCCESS or (caps.UsagePage,caps.Usage)!=(0x0D,5):
            raise ValueError('Not a precision touchpad')
        if not 0<caps.NumberInputValueCaps<=1024:raise ValueError('Invalid HID capabilities')
        values=(ValueCaps*caps.NumberInputValueCaps)();length=U16(len(values))
        if hid.HidP_GetValueCaps(0,values,C.byref(length),preparsed)!=SUCCESS:
            raise ValueError('HID value capabilities unavailable')
        self.values={}
        for cap in values[:length.value]:
            lo=cap.UsageInfo[0];hi=cap.UsageInfo[1] if cap.IsRange else lo
            if hi-lo>128:continue
            for usage in range(lo,hi+1):
                self.values[(cap.ReportID,cap.LinkCollection,cap.UsagePage,usage)]=(cap.LogicalMin,cap.LogicalMax)
        self.links=sorted({link for _,link,page,usage in self.values if page==1 and usage==0x30})

    def value(self,report,link,page,usage):
        if (report[0],link,page,usage) not in self.values:return None
        out=U32()
        status=self.hid.HidP_GetUsageValue(0,page,link,usage,C.byref(out),self.preparsed,report,len(report))
        return out.value if status==SUCCESS else None

    def usages(self,report,link,page):
        active=(U16*64)();length=U32(len(active))
        status=self.hid.HidP_GetUsages(0,page,link,active,C.byref(length),self.preparsed,report,len(report))
        return set(active[:length.value]) if status==SUCCESS and length.value<=len(active) else set()

    def decode(self,report,now):
        if not report:return []
        scan=self.value(report,0,0x0D,0x56);count=self.value(report,0,0x0D,0x54)
        if scan is None or count is None:return []
        contacts=[]
        buttons=self.usages(report,0,9)
        for link in self.links:
            identity=self.value(report,link,0x0D,0x51)
            x=self.value(report,link,1,0x30);y=self.value(report,link,1,0x31)
            if identity is None or x is None or y is None:continue
            xlo,xhi=self.values[(report[0],link,1,0x30)];ylo,yhi=self.values[(report[0],link,1,0x31)]
            if xhi<=xlo or yhi<=ylo or not xlo<=x<=xhi or not ylo<=y<=yhi:continue
            usages=self.usages(report,link,0x0D)
            contacts.append(Contact(identity,(x-xlo)/(xhi-xlo),(y-ylo)/(yhi-ylo),
                                    0x42 in usages and 0x47 in usages and not buttons))
        # Fixed-slot reports may include empty padding contacts (often ID 0).
        # Prefer active slots and retain only the declared frame contact count.
        limit=count or (self.frames.expected if scan==self.frames.scan else 0)
        unique={}
        for contact in sorted(contacts,key=lambda c:not c.active):
            unique.setdefault(contact.identity,contact)
        contacts=list(unique.values())[:limit]
        frame=self.frames.append(scan,count,contacts)
        return self.gesture.feed(frame,now) if frame is not None else []


class WindowsTouchpadListener(threading.Thread):
    """Owned hidden-window message loop, active only while Keycast is enabled."""
    _registration_owner=threading.Lock()

    def __init__(self,on_scroll):
        super().__init__(name='Keycast touchpad',daemon=True)
        self.on_scroll=on_scroll;self.closed=threading.Event();self.prepared=threading.Event()
        self.hwnd=None;self.failure=False;self.decoders={}

    def _bind(self):
        self.user=C.WinDLL('user32',use_last_error=True);self.hid=C.WinDLL('hid',use_last_error=True,winmode=0x800)
        for name,args,result in [
            ('RegisterRawInputDevices',[C.POINTER(RawDevice),U32,U32],C.c_int),
            ('GetRawInputData',[PTR,U32,PTR,C.POINTER(U32),U32],U32),
            ('GetRawInputDeviceInfoW',[PTR,U32,PTR,C.POINTER(U32)],U32),
            ('GetCursorPos',[PTR],C.c_int)]:
            function=getattr(self.user,name);function.argtypes=args;function.restype=result
        for name,args in [
            ('HidP_GetCaps',[PTR,C.POINTER(HidCaps)]),
            ('HidP_GetValueCaps',[C.c_int,C.POINTER(ValueCaps),C.POINTER(U16),PTR]),
            ('HidP_GetUsageValue',[C.c_int,U16,U16,U16,C.POINTER(U32),PTR,PTR,U32]),
            ('HidP_GetUsages',[C.c_int,U16,U16,C.POINTER(U16),C.POINTER(U32),PTR,PTR,U32])]:
            function=getattr(self.hid,name);function.argtypes=args;function.restype=U32

    def _read(self,handle):
        length=U32();header_size=C.sizeof(RawHeader)
        if self.user.GetRawInputData(handle,0x10000003,None,C.byref(length),header_size)!=0:return
        if not header_size+8<=length.value<=1024*1024:return
        raw=C.create_string_buffer(length.value)
        if self.user.GetRawInputData(handle,0x10000003,raw,C.byref(length),header_size)!=length.value:return
        header=RawHeader.from_buffer(raw)
        if header.dwType!=2 or header.dwSize!=length.value:return
        size,count=struct.unpack_from('<II',raw,header_size)
        start=header_size+8
        if not size or not count or size*count>length.value-start:return
        device=header.hDevice
        if device not in self.decoders:
            n=U32()
            self.user.GetRawInputDeviceInfoW(device,0x20000005,None,C.byref(n))
            if not 0<n.value<=256*1024:return
            preparsed=C.create_string_buffer(n.value)
            if self.user.GetRawInputDeviceInfoW(device,0x20000005,preparsed,C.byref(n))==0xFFFFFFFF:return
            decoder=HidDecoder(self.hid,preparsed)
            decoder.gesture.natural=self.natural
            if len(self.decoders)>=8:self.decoders.clear()
            self.decoders[device]=decoder
        decoder=self.decoders[device];now=time.monotonic()
        from ctypes import wintypes
        point=wintypes.POINT()
        if not self.user.GetCursorPos(C.byref(point)):return
        for index in range(count):
            report=raw.raw[start+index*size:start+(index+1)*size]
            for kind in decoder.decode(report,now):
                if not self.closed.is_set():self.on_scroll(kind,point.x,point.y,now)

    def run(self):
        import win32gui,win32api
        name='WWRecorder.Keycast.Touchpad.'+str(id(self));registered=False;owned=False
        try:
            owned=self._registration_owner.acquire(timeout=2)
            if not owned:raise TimeoutError('Previous touchpad listener is stopping')
            if self.closed.is_set():return
            self._bind();self.natural=True
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\PrecisionTouchPad') as key:
                    self.natural=bool(winreg.QueryValueEx(key,'ScrollDirection')[0])
            except OSError:pass
            def procedure(hwnd,message,wparam,lparam):
                if message==0x0010:
                    win32gui.DestroyWindow(hwnd);return 0
                if message==0x0002:
                    win32gui.PostQuitMessage(0);return 0
                try:
                    if message==0x00FF and not self.closed.is_set():self._read(lparam)
                    elif message==0x00FE:self.decoders.pop(lparam,None)
                except Exception:
                    # A malformed/unsupported device report must never abort the
                    # hook callback or expose raw input through diagnostics.
                    self.decoders.clear()
                return win32gui.DefWindowProc(hwnd,message,wparam,lparam)
            wc=win32gui.WNDCLASS();wc.lpszClassName=name;wc.lpfnWndProc=procedure;wc.hInstance=win32api.GetModuleHandle(None)
            win32gui.RegisterClass(wc);registered=True
            self.hwnd=win32gui.CreateWindowEx(0,name,'',0,0,0,0,0,-3,0,wc.hInstance,None)
            registration=RawDevice(0x0D,5,0x0100|0x2000,self.hwnd)
            if not self.user.RegisterRawInputDevices(C.byref(registration),1,C.sizeof(registration)):
                raise OSError('Touchpad registration failed')
            self.prepared.set()
            if self.closed.is_set():win32gui.PostMessage(self.hwnd,0x0010,0,0)
            win32gui.PumpMessages()
        except Exception:
            self.failure=True
        finally:
            self.prepared.set()
            if self.hwnd:
                removal=RawDevice(0x0D,5,1,None)
                self.user.RegisterRawInputDevices(C.byref(removal),1,C.sizeof(removal))
                if win32gui.IsWindow(self.hwnd):win32gui.DestroyWindow(self.hwnd)
            self.hwnd=None;self.decoders.clear()
            if registered:win32gui.UnregisterClass(name,wc.hInstance)
            if owned:self._registration_owner.release()

    def stop(self):
        self.closed.set()
        if self.hwnd:
            import win32gui
            try:win32gui.PostMessage(self.hwnd,0x0010,0,0)
            except win32gui.error:pass
