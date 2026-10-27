"""Piecewise Qt-logical to Windows-native desktop coordinate mapping.

Qt exposes each monitor in device-independent coordinates while MSS captures
the Windows virtual desktop in physical pixels.  A single DPR multiplication
cannot map monitors with different scales (especially at negative origins).
"""
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ScreenTransform:
    name: str
    logical_left: int
    logical_top: int
    logical_width: int
    logical_height: int
    native_left: int
    native_top: int
    native_width: int
    native_height: int


def _intersect(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return (left, top, right - left, bottom - top) if right > left and bottom > top else None


def build_capture_plan(region: dict, screens: Iterable[ScreenTransform]) -> dict:
    """Return native source rectangles and a common-density output canvas."""
    rx, ry, rw, rh = (int(region[k]) for k in ("left", "top", "width", "height"))
    screens = list(screens)
    hits = []
    for screen in screens:
        hit = _intersect((rx, ry, rw, rh), (
            screen.logical_left, screen.logical_top,
            screen.logical_width, screen.logical_height,
        ))
        if hit:
            hits.append((screen, hit))
    if not hits:
        raise ValueError("The selected area does not overlap an available display.")

    # Use the densest intersected monitor so high-DPI portions remain sharp.
    target_scale = max(
        max(s.native_width / s.logical_width, s.native_height / s.logical_height)
        for s, _ in hits
    )
    out_w, out_h = max(1, round(rw * target_scale)), max(1, round(rh * target_scale))
    # Video encoders require even dimensions.  Screenshot callers can retain
    # the exact canvas by passing the plan to compose_frozen_desktop unchanged.
    segments = []
    for s, (x, y, w, h) in hits:
        sx = s.native_width / s.logical_width
        sy = s.native_height / s.logical_height
        src_x1 = s.native_left + round((x - s.logical_left) * sx)
        src_y1 = s.native_top + round((y - s.logical_top) * sy)
        src_x2 = s.native_left + round((x + w - s.logical_left) * sx)
        src_y2 = s.native_top + round((y + h - s.logical_top) * sy)
        dst_x1, dst_y1 = round((x - rx) * target_scale), round((y - ry) * target_scale)
        dst_x2, dst_y2 = round((x + w - rx) * target_scale), round((y + h - ry) * target_scale)
        segments.append({
            "src_left": src_x1, "src_top": src_y1,
            "src_width": max(1, src_x2 - src_x1), "src_height": max(1, src_y2 - src_y1),
            "dst_left": dst_x1, "dst_top": dst_y1,
            "dst_width": max(1, dst_x2 - dst_x1), "dst_height": max(1, dst_y2 - dst_y1),
        })
    return {"left": 0, "top": 0, "width": out_w, "height": out_h,
            "logical_region": dict(region), "segments": segments}


def compose_frozen_desktop(image, native_origin: tuple[int, int], plan: dict):
    """Compose a PIL virtual-desktop freeze according to a capture plan."""
    from PIL import Image
    result = Image.new("RGB", (plan["width"], plan["height"]), "black")
    ox, oy = native_origin
    for seg in plan["segments"]:
        box = (seg["src_left"] - ox, seg["src_top"] - oy,
               seg["src_left"] - ox + seg["src_width"],
               seg["src_top"] - oy + seg["src_height"])
        part = image.crop(box)
        target = (seg["dst_width"], seg["dst_height"])
        if part.size != target:
            part = part.resize(target, Image.Resampling.LANCZOS)
        result.paste(part, (seg["dst_left"], seg["dst_top"]))
    return result


def qt_screen_transforms(qscreens) -> list[ScreenTransform]:
    """Pair QScreen logical geometry with Windows native display rectangles."""
    native = _windows_native_displays()
    result = []
    for index, screen in enumerate(qscreens):
        geo = screen.geometry()
        key = screen.name().lower()
        n = native.get(key)
        if n is None and index < len(native.get("__ordered__", [])):
            n = native["__ordered__"][index]
        if n is None:
            dpr = float(screen.devicePixelRatio() or 1.0)
            n = (round(geo.left() * dpr), round(geo.top() * dpr),
                 round(geo.width() * dpr), round(geo.height() * dpr))
        result.append(ScreenTransform(screen.name(), geo.left(), geo.top(), geo.width(), geo.height(), *n))
    return result


def _windows_native_displays():
    import sys
    if sys.platform != "win32":
        return {}
    import ctypes
    from ctypes import wintypes

    class DEVMODEW(ctypes.Structure):
        _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                    ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD),
                    ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                    ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long),
                    ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                    ("dmColor", wintypes.SHORT), ("dmDuplex", wintypes.SHORT),
                    ("dmYResolution", wintypes.SHORT), ("dmTTOption", wintypes.SHORT),
                    ("dmCollate", wintypes.SHORT), ("dmFormName", wintypes.WCHAR * 32),
                    ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD),
                    ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD),
                    ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD)]
    user32 = ctypes.windll.user32
    displays, ordered, i = {}, [], 0
    while True:
        name = f"\\\\.\\DISPLAY{i + 1}"
        dm = DEVMODEW(); dm.dmSize = ctypes.sizeof(DEVMODEW)
        if not user32.EnumDisplaySettingsW(name, -1, ctypes.byref(dm)):
            if i > 15:
                break
            i += 1
            continue
        rect = (dm.dmPositionX, dm.dmPositionY, int(dm.dmPelsWidth), int(dm.dmPelsHeight))
        displays[name.lower()] = rect; ordered.append(rect); i += 1
        if i > 31:
            break
    displays["__ordered__"] = ordered
    return displays
