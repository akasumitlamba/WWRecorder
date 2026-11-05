"""Deterministic Windows icon encoding; never redraw the established artwork."""
from pathlib import Path
from PIL import Image, ImageOps

ICON_SIZES = (16, 24, 32, 48, 64, 72, 96, 128, 256)
TARGET_SIZES = (16, 24, 32, 48, 64, 96, 256)


def render_icon(source, size):
    # Small taskbar frames need the full canvas. The artwork itself has rounded
    # transparent corners; larger frames retain a narrow resampling gutter.
    inset = 0 if size <= 32 else max(1, round(size * 0.015))
    artwork = source.convert('RGBA')
    artwork.putalpha(artwork.getchannel('A').point(lambda alpha: 255 if alpha >= 240 else alpha))
    bounds = artwork.getchannel('A').point(lambda alpha: 255 if alpha >= 64 else 0).getbbox()
    if bounds: artwork = artwork.crop(bounds)
    content = ImageOps.contain(artwork, (size - inset * 2,) * 2, Image.Resampling.LANCZOS)
    result = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    result.alpha_composite(content, ((size-content.width)//2, (size-content.height)//2))
    # Lanczos may leave faint colour/alpha in the four outside corners.
    # These pixels are outside the rounded artwork and must stay transparent.
    for point in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
        result.putpixel(point, (0, 0, 0, 0))
    return result


def write_ico(source, destination):
    # Conventional DIB sizes plus a PNG jumbo frame support native shell and
    # installer resource readers; every AND mask derives from the same alpha.
    import io
    import struct
    frames = []
    for size in ICON_SIZES:
        image = render_icon(source, size)
        if size == 256:
            data = io.BytesIO(); image.save(data, format='PNG'); encoded = data.getvalue()
        else:
            # DIB frames are understood by both the shell and Inno's PE icon
            # resource handling. Preserve alpha AND a correctly padded mask.
            color = image.tobytes('raw', 'BGRA', 0, -1)
            stride = ((size + 31) // 32) * 4
            mask = bytearray(stride * size)
            for y in range(size):
                for x in range(size):
                    if image.getpixel((x, size - 1 - y))[3] == 0:
                        mask[y * stride + x // 8] |= 0x80 >> (x % 8)
            header = struct.pack('<IiiHHIIiiII', 40, size, size * 2, 1, 32, 0, len(color) + len(mask), 0, 0, 0, 0)
            encoded = header + color + mask
        frames.append((size, encoded))
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
