"""Native BGRA capture composition without unnecessary full-frame copies."""
import numpy as np
from PIL import Image


def capture_bgra_frame(capture, segments, width, height, scratch=None):
    if len(segments) == 1:
        segment = segments[0]
        if (segment['dst_left'] == segment['dst_top'] == 0 and
                segment['src_width'] == segment['dst_width'] == width and
                segment['src_height'] == segment['dst_height'] == height):
            grab = capture.grab({'left': segment['src_left'], 'top': segment['src_top'],
                                 'width': width, 'height': height})
            frame = np.frombuffer(grab.raw, np.uint8).reshape(height, width, 4)
            return frame if frame.flags.writeable else frame.copy()
    canvas = scratch if scratch is not None and scratch.shape == (height, width, 4) else np.empty((height, width, 4), np.uint8)
    canvas.fill(0)
    for segment in segments:
        grab = capture.grab({'left': segment['src_left'], 'top': segment['src_top'],
                             'width': segment['src_width'], 'height': segment['src_height']})
        part = np.frombuffer(grab.raw, np.uint8).reshape(segment['src_height'], segment['src_width'], 4)
        target = segment['dst_width'], segment['dst_height']
        if (segment['src_width'], segment['src_height']) != target:
            # Interpolate each BGRA channel independently for mixed-DPI text.
            # MSS alpha bytes are often zero. Interpolate color without RGBA
            # premultiplication, which would turn those valid pixels black.
            colors = np.asarray(Image.fromarray(part[:, :, :3]).resize(target, Image.Resampling.BICUBIC))
            part = np.empty((target[1], target[0], 4), np.uint8)
            part[:, :, :3] = colors
            part[:, :, 3] = 255
        x, y = segment['dst_left'], segment['dst_top']
        right, bottom = min(width, x + part.shape[1]), min(height, y + part.shape[0])
        canvas[y:bottom, x:right] = part[:bottom-y, :right-x]
    return canvas
