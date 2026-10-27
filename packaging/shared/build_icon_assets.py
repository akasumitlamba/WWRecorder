"""Deterministic Windows icon encoding; never redraw the established artwork."""
from pathlib import Path
from PIL import Image, ImageOps

ICON_SIZES = (16, 24, 32, 48, 64, 72, 96, 128, 256)
TARGET_SIZES = (16, 24, 32, 48, 64, 96, 256)


def render_icon(source, size):
    # Transparent gutter keeps resampling away from the canvas boundary and
    # avoids partly opaque corner pixels in small Windows shell variants.
    inset = max(1, round(size * 0.04))
    artwork = source.convert('RGBA')
    artwork.putalpha(artwork.getchannel('A').point(lambda alpha: 255 if alpha >= 240 else alpha))
    bounds = artwork.getchannel('A').point(lambda alpha: 255 if alpha >= 64 else 0).getbbox()
    if bounds: artwork = artwork.crop(bounds)
    content = ImageOps.contain(artwork, (size - inset * 2,) * 2, Image.Resampling.LANCZOS)
    result = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    result.alpha_composite(content, ((size-content.width)//2, (size-content.height)//2))
    return result


def write_ico(source, destination):
    # Explicit PNG frames preserve alpha in every size instead of relying on
    # legacy BMP AND masks with independently downsampled corner alpha.
    import io
    import struct
    frames = []
    for size in ICON_SIZES:
        data = io.BytesIO()
        render_icon(source, size).save(data, format='PNG')
        frames.append((size, data.getvalue()))
    offset = 6 + 16 * len(frames)
    result = bytearray(struct.pack('<HHH', 0, 1, len(frames)))
    for size, data in frames:
        result.extend(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    for _, data in frames:
        result.extend(data)
    Path(destination).write_bytes(result)


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[2]
    with Image.open(root / 'packaging/shared/icon-source.png') as source:
        write_ico(source, root / 'app/icon.ico')
