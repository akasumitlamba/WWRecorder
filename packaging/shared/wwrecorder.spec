# wwrecorder.spec
# PyInstaller build specification for WWRecorder
#
# Usage:
#   ./scripts/build-distributions.ps1 -Format Both
#
# Prerequisites:
#   pip install pyinstaller
#   • Place ffmpeg.exe in app/ before building.
#   • Place icon.ico in app/ before building.
#
# Output:
#   work/payloads/dual/WWRecorder/   ← distribution folder (zip & distribute, or run Inno Setup on it)

import os
from pathlib import Path

repo_root = Path(SPECPATH).resolve().parents[1]
app_root = repo_root / "app"
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

block_cipher = None

# ── Collect soundcard's native libs (WASAPI backend) ─────────────────────────
soundcard_binaries = collect_dynamic_libs("soundcard")
soundcard_datas = collect_data_files("soundcard")

# certifi is updater.py's verified-CA fallback.  Its PEM bundle is data, not
# Python bytecode, so include it explicitly for machines whose system trust
# store cannot be opened by the frozen app.
certifi_datas = collect_data_files("certifi")

# ── Data files to bundle ──────────────────────────────────────────────────────
# (source_path, dest_folder_inside_bundle)
# Preserve exact runtime package metadata for independent installed-artifact SCA.
metadata_datas = []
for package in ('PyQt6', 'PyQt6-Qt6', 'PyQt6-sip', 'mss', 'numpy', 'Pillow',
                'pywin32', 'soundcard', 'pynput', 'certifi', 'cffi', 'pycparser',
                'six', 'winrt-Windows.ApplicationModel', 'winrt-Windows.Foundation', 'winrt-runtime'):
    metadata_datas += copy_metadata(package)
datas = soundcard_datas + certifi_datas + metadata_datas + [
    (str(app_root / "icon.ico"), "."),
    (str(app_root / "icon.ico"), "assets"),
    (str(app_root / "icon.ico"), "icons"),
    (str(app_root / "icons/*.png"), "icons"),
    (str(app_root / "icons/modern"), "icons/modern"),
    (str(app_root / "icons/*.svg"), "icons"),
    (str(app_root / "icons/*.txt"), "icons"),
]

# Bundle shared FFmpeg from app/; frozen destination stays unchanged
binaries = soundcard_binaries + [
    (str(app_root / "ffmpeg.exe"), "."),               # Extracted to _MEIPASS root at runtime
]

a = Analysis(
    [str(app_root / "main.py")],
    pathex=[str(app_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        # PyQt6 components that PyInstaller sometimes misses
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.QtMultimedia",
        "PyQt6.QtMultimediaWidgets",
        "PyQt6.sip",
        # Audio backends
        "soundcard",
        "soundcard.mediafoundation",   # Windows WASAPI backend
        "cffi",
        "_cffi_backend",
        # mss
        "mss",
        "mss.windows",
        # pynput
        "pynput",
        "pynput.keyboard",
        "pynput.keyboard._win32",
        "pynput.mouse",
        "pynput.mouse._win32",
        "pynput._util",
        "pynput._util.win32",
        # stdlib
        "subprocess",
        "wave",
        "struct",
        "tempfile",
        "winreg",
        "ctypes",
        "ctypes.wintypes",
        "winrt.windows.applicationmodel",
        "winrt.windows.foundation",
        "win32gui",
        "win32ui",
        "win32con",
        "pythoncom",
        "pywintypes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim unused heavy packages
        "matplotlib",
        "scipy",
        "pandas",
        "tkinter",
        "IPython",
        "jupyter",
        "notebook",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# PyInstaller resolves transitive DLLs through PATH.  Developer-tool runtimes
# must never leak into a release: an earlier build picked up Poppler's ICU DLL
# from the Codex runtime, whose version-suffixed exports are incompatible with
# Qt6Core's unversioned ICU imports.  Fail closed instead of shipping another
# machine-specific package; release builds must use a sanitized PATH.
_blocked_binary_source = os.path.normcase(os.path.join(".cache", "codex-runtimes"))
_contaminated_binaries = sorted(
    (dest, source)
    for dest, source, _kind in a.binaries
    if _blocked_binary_source in os.path.normcase(source)
)
if _contaminated_binaries:
    details = "\n".join(f"  {dest} <- {source}" for dest, source in _contaminated_binaries)
    raise RuntimeError(
        "Release build contains DLLs from the Codex tool runtime. "
        "Re-run PyInstaller with a sanitized PATH:\n" + details
    )

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WWRecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        "ffmpeg.exe",          # Don't UPX-compress ffmpeg — it's already packed
        "vcruntime*.dll",
        "api-ms-win*.dll",
    ],
    console=False,             # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(app_root / "icon.ico"),
    version=str(repo_root / "packaging/shared/version_info.txt"),   # Optional: VERSIONINFO resource
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=["ffmpeg.exe", "vcruntime*.dll"],
    name="WWRecorder",         # Output folder: work/payloads/dual/WWRecorder/
)


# ─────────────────────────────────────────────────────────────────────────────
# Optional: version_info.txt template (save separately as version_info.txt)
# ─────────────────────────────────────────────────────────────────────────────
# VSVersionInfo(
#   ffi=FixedFileInfo(
#     filevers=(1, 5, 0, 0),
#     prodvers=(1, 5, 0, 0),
#     mask=0x3f,
#     flags=0x0,
#     OS=0x40004,
#     fileType=0x1,
#     subtype=0x0,
#     date=(0, 0),
#   ),
#   kids=[
#     StringFileInfo([
#       StringTable('040904B0', [
#         StringStruct('CompanyName', 'WWRecorder'),
#         StringStruct('FileDescription', 'WWRecorder - Screen Recorder'),
#         StringStruct('FileVersion', '1.6.0'),
#         StringStruct('InternalName', 'WWRecorder'),
#         StringStruct('LegalCopyright', 'Copyright 2025'),
#         StringStruct('OriginalFilename', 'WWRecorder.exe'),
#         StringStruct('ProductName', 'WWRecorder'),
#         StringStruct('ProductVersion', '1.6.0'),
#       ])
#     ]),
#     VarFileInfo([VarStruct('Translation', [1033, 1200])])
#   ]
# )
