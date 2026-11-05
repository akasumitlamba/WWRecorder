"""Fail closed when a frozen application lacks required Qt/runtime resources."""
from pathlib import Path
import argparse
from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

REQUIRED_QT = {'PyQt6'}
REQUIRED_NATIVE = ('QtCore.pyd','QtGui.pyd','QtWidgets.pyd',
                   'QtMultimedia.pyd','QtMultimediaWidgets.pyd',
                   'Qt6Core.dll','Qt6Gui.dll','Qt6Widgets.dll','qwindows.dll')

def validate_payload(root, archive_factory=CArchiveReader):
    root=Path(root)
    executable=root/'WWRecorder.exe'
    if not executable.is_file():raise ValueError('Frozen WWRecorder.exe is missing')
    archive=archive_factory(str(executable))
    # Inspect the PYZ table without executing frozen code or assuming the
    # validation interpreter matches the frozen Python bytecode version.
    import tempfile
    pyz_name=next((n for n in archive.toc if n.endswith('.pyz')),None)
    if pyz_name is None:raise ValueError('Frozen Python module archive is missing')
    with tempfile.TemporaryDirectory() as directory:
        pyz=Path(directory)/'payload.pyz';pyz.write_bytes(archive.extract(pyz_name))
        modules=set(ZlibArchiveReader(str(pyz)).toc)
    missing=sorted(REQUIRED_QT-modules)
    files=list(root.rglob('*'))
    for name in REQUIRED_NATIVE:
        if not any(p.name.lower()==name.lower() for p in files):missing.append(name)
    for name in ('undo.png','redo.png'):
        if not any(p.as_posix().endswith('/icons/modern/'+name) for p in files):missing.append('modern/'+name)
    if missing:raise ValueError('Incomplete frozen payload: '+', '.join(missing))
    return {'qt_modules':len(REQUIRED_QT),'validated':True}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('payload');args=parser.parse_args()
    print(validate_payload(args.payload))
