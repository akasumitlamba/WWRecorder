"""Validate actual PE icon resources and the Windows icon loader, not filenames."""
import ctypes,io,json,struct,sys
from pathlib import Path
from PIL import Image

def verify(path):
    import pefile
    pe=pefile.PE(str(path));kinds={r.id:r for r in pe.DIRECTORY_ENTRY_RESOURCE.entries}
    assert 3 in kinds and 14 in kinds,'Executable lacks icon/group resources'
    images={r.id:pe.get_data(r.directory.entries[0].data.struct.OffsetToData,r.directory.entries[0].data.struct.Size) for r in kinds[3].directory.entries}
    sizes=[]
    for group in kinds[14].directory.entries:
        entry=group.directory.entries[0].data.struct
        data=pe.get_data(entry.OffsetToData,entry.Size)
        count=struct.unpack_from('<H',data,4)[0]
        for n in range(count):
            width,height,colors,reserved,planes,bits,length,identifier=struct.unpack_from('<BBBBHHIH',data,6+n*14)
            raw=images[identifier];assert len(raw)==length
            ico=struct.pack('<HHHBBBBHHII',0,1,1,width,height,colors,0,planes,bits,len(raw),22)+raw
            image=Image.open(io.BytesIO(ico)).convert('RGBA')
            assert sum(r>g*1.4 and r>b*1.4 and r>80 and a>100 for r,g,b,a in image.get_flattened_data())>10,'Generic/missing app artwork'
            sizes.append(image.width)
    assert {16,32,48,256}.issubset(sizes),sizes
    if sys.platform=='win32':
        shell=ctypes.windll.shell32;user=ctypes.windll.user32
        shell.ExtractIconExW.argtypes=[ctypes.c_wchar_p,ctypes.c_int,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(ctypes.c_void_p),ctypes.c_uint]
        shell.ExtractIconExW.restype=ctypes.c_uint
        user.DestroyIcon.argtypes=[ctypes.c_void_p]
        # Probe one size per call: asking for both sizes can report two
        # successfully extracted handles for one icon group.
        for large in (True, False):
            handle=ctypes.c_void_p()
            count=shell.ExtractIconExW(str(Path(path).resolve()),0,
                ctypes.byref(handle) if large else None,
                None if large else ctypes.byref(handle),1)
            assert count==1 and handle.value, (Path(path).name, 'large' if large else 'small', count, ctypes.GetLastError())
            user.DestroyIcon(handle)
    pe.close();return {'file':Path(path).name,'sizes':sorted(set(sizes)),'windows_loader':sys.platform=='win32'}

if __name__=='__main__':print(json.dumps(verify(sys.argv[1])))
