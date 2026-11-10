"""Fast, frame-exact trim/delete export for WWRecorder's own H.264 videos.

A full re-encode of a long recording takes a long time and saturates the CPU.
For edits that only remove time (trim, delete sections) and change audio
(mute sections, export without audio), most of the video can be copied
unchanged. Only the frames between a cut point and the next keyframe are
re-encoded, with the same encoder settings WWRecorder uses for recordings.

Every step is checked. The caller falls back to a complete re-encode whenever
this module returns False: an unsupported source, re-encoded pieces whose
H.264 parameter sets differ from the source (which could misplay in some
players), or an output whose frame count or duration is not exactly the
expected edited timeline. Deleted frames are never present in the output;
copied pieces are whole closed GOPs that lie entirely inside kept ranges.
"""
from fractions import Fraction
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

ENCODE_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-pix_fmt", "yuv420p"]
# Recordings carry Opus in Matroska, whose codec delay is signalled exactly.
# MP4 keeps the editor's established AAC audio for player compatibility.
AUDIO_ARGS = {'.mkv': ["-c:a", "libopus", "-b:a", "112k"],
              '.mp4': ["-c:a", "aac", "-b:a", "128k"]}
SUPPORTED_SUFFIXES = {'.mkv'}  # WWRecorder recordings and edits


class SmartCutUnavailable(Exception):
    """The edit cannot be exported safely by copying; use a full re-encode."""


class SmartCutCancelled(Exception):
    pass


def _creation_flags():
    if sys.platform != 'win32':
        return 0
    # Background priority keeps the desktop responsive during long exports.
    return subprocess.CREATE_NO_WINDOW | 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS


class _Runner:
    def __init__(self, ffmpeg, cancelled):
        self.ffmpeg = ffmpeg
        self.cancelled = cancelled or (lambda: False)
        self.process = None

    def run(self, args, timeout, stdout=subprocess.DEVNULL):
        if self.cancelled():
            raise SmartCutCancelled()
        self.process = subprocess.Popen(
            [self.ffmpeg, '-hide_banner', '-nostdin', *args],
            stdout=stdout, stderr=subprocess.PIPE, creationflags=_creation_flags())
        try:
            out, err = self.process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.kill()
            raise SmartCutUnavailable('A media step exceeded its time limit.')
        finally:
            process, self.process = self.process, None
        if self.cancelled():
            raise SmartCutCancelled()
        return process.returncode, out or b'', (err or b'').decode(errors='replace')

    def kill(self):
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.kill()
                process.wait(timeout=3)
            except Exception:
                pass


def parse_stream_info(text):
    """Video codec/format/size/rate and audio presence from `ffmpeg -i` output."""
    video = re.search(r'Stream #0:(\d+)[^:]*: Video: (\w+)[^,]*, (\w+)(?:\([^)]*\))?, (\d+)x(\d+)', text)
    if not video:
        return None
    rate = re.search(r'Stream #0:%s[^\n]*?, ([\d.]+) fps' % video.group(1), text)
    duration = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', text)
    start = re.search(r'start: (-?[\d.]+)', text)
    return {
        'codec': video.group(2), 'pix_fmt': video.group(3),
        'width': int(video.group(4)), 'height': int(video.group(5)),
        'fps': rate.group(1) if rate else None,
        'duration': (int(duration.group(1)) * 3600 + int(duration.group(2)) * 60
                     + float(duration.group(3))) if duration else None,
        'start': float(start.group(1)) if start else 0.0,
        'audio_streams': len(re.findall(r'Stream #0:\d+[^:]*: Audio:', text)),
        'video_streams': len(re.findall(r'Stream #0:\d+[^:]*: Video:', text)),
    }


def frame_rate(text):
    """Exact frame rate for common recording rates (30 fps and NTSC variants)."""
    value = float(text)
    for candidate in (Fraction(30000, 1001), Fraction(24000, 1001), Fraction(60000, 1001)):
        if abs(float(candidate) - value) < 0.005:
            return candidate
    rounded = Fraction(round(value * 1000), 1000).limit_denominator(1001)
    if abs(float(rounded) - value) > 0.001:
        raise SmartCutUnavailable('Unsupported frame rate.')
    return rounded


def keep_frame_ranges(keep_seconds, fps, total_frames):
    """Frame index ranges [a, b) whose timestamps fall in the kept intervals."""
    ranges = []
    for start, end in keep_seconds:
        a = max(0, math.ceil(start * fps - 1e-6))
        b = min(total_frames, math.ceil(end * fps - 1e-6))
        if b > a:
            if ranges and a <= ranges[-1][1]:
                ranges[-1] = (ranges[-1][0], max(b, ranges[-1][1]))
            else:
                ranges.append((a, b))
    return ranges


def plan_pieces(ranges, keyframes, total_frames):
    """Split kept frame ranges into ('encode'|'copy', a, b) pieces.

    Copy pieces start at a keyframe and end at the next GOP boundary (a
    keyframe or the end of the video), so they contain only whole GOPs.
    """
    boundaries = sorted(set(k for k in keyframes if 0 <= k < total_frames) | {total_frames})
    pieces = []
    for a, b in ranges:
        first = next((k for k in boundaries if k >= a), None)
        last = max((k for k in boundaries if k <= b), default=None)
        if first is None or last is None or first >= last or first >= b:
            pieces.append(('encode', a, b))
            continue
        if a < first:
            pieces.append(('encode', a, first))
        pieces.append(('copy', first, last))
        if last < b:
            pieces.append(('encode', last, b))
    return pieces


def _parameter_sets(annexb):
    """SPS/PPS NAL units from an Annex B H.264 byte stream."""
    units = re.split(rb'\x00\x00\x01', annexb)
    found = []
    for unit in units[1:]:
        unit = unit.rstrip(b'\x00')
        if unit and (unit[0] & 0x1F) in (7, 8) and unit not in found:
            found.append(unit)
    return found


def edited_audio_graph(keep_seconds, mute_seconds):
    """Mute in source time, then keep exactly the frame-aligned intervals."""
    stages = [f"volume=0:enable='gte(t,{a:.6f})*lt(t,{b:.6f})'" for a, b in mute_seconds if b > a]
    prefix = ','.join(stages)
    if len(keep_seconds) == 1:
        a, b = keep_seconds[0]
        return (prefix + ',' if prefix else '') + f'atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS'
    count = len(keep_seconds)
    graph = [(prefix + ',' if prefix else '') + f'asplit={count}' + ''.join(f'[s{i}]' for i in range(count))]
    for i, (a, b) in enumerate(keep_seconds):
        graph.append(f'[s{i}]atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS[k{i}]')
    graph.append(''.join(f'[k{i}]' for i in range(count)) + f'concat=n={count}:v=0:a=1')
    return ';'.join(graph)


class SmartCutter:
    def __init__(self, ffmpeg, source, output, cancelled=None, progress=None, workdir=None):
        self.source = source
        self.output = output
        self.progress = progress or (lambda value: None)
        self.workdir = workdir
        self.runner = _Runner(ffmpeg, cancelled)

    def stop(self):
        self.runner.kill()

    # ── inspection ────────────────────────────────────────────────────────

    def inspect(self):
        _, _, text = self.runner.run(['-i', self.source], timeout=30)
        info = parse_stream_info(text)
        if (not info or info['codec'] != 'h264' or info['pix_fmt'] != 'yuv420p'
                or info['video_streams'] != 1 or not info['fps'] or info['duration'] is None
                or info['audio_streams'] > 1 or not -0.1 <= info['start'] <= 0.0015):
            # Opus/AAC codec delay gives a slightly negative audio start; video
            # must start at 0, which scan_frames verifies exactly.
            raise SmartCutUnavailable('The video format needs a full re-encode.')
        info['rate'] = frame_rate(info['fps'])
        return info

    def scan_frames(self, info):
        """Keyframe indices and total frame count, reading packets only."""
        code, out, err = self.runner.run(
            ['-i', self.source, '-map', '0:v:0', '-c', 'copy', '-f', 'framecrc', '-'],
            timeout=max(120, info['duration'] / 4), stdout=subprocess.PIPE)
        if code != 0:
            raise SmartCutUnavailable('Video packets could not be read.')
        rate = info['rate']
        times = []
        keyframes = []
        for line in out.decode(errors='replace').splitlines():
            if line.startswith('#') or not line.strip():
                continue
            fields = [field.strip() for field in line.split(',')]
            if len(fields) < 6:
                continue
            times.append(int(fields[2]))
            # framecrc prints F=0x.. only when flags differ from "keyframe".
            flags = next((f for f in fields[6:] if f.startswith('F=')), None)
            if flags is None or int(flags[2:], 16) & 1:
                keyframes.append(len(times) - 1)
        if not times:
            raise SmartCutUnavailable('The video has no frames.')
        return times, keyframes

    def _frame_index_map(self, pts, info):
        """Map packets (decode order) to display indices; require exact CFR."""
        tb = self._stream_time_base(info)
        ordered = sorted(pts)
        frame = Fraction(1, 1) / info['rate']
        first = Fraction(ordered[0]) * tb
        if abs(first) > Fraction(1, 10):
            raise SmartCutUnavailable('The video starts too late in its file.')
        for index, value in enumerate(ordered):
            if abs(Fraction(value) * tb - first - index * frame) > Fraction(1, 1000):
                raise SmartCutUnavailable('The video is not constant frame rate.')
        # Frame k is at offset + k / rate on FFmpeg's input timeline, the same
        # timeline its decoded audio timestamps, -ss and atrim use.
        info['offset'] = first
        position = {value: index for index, value in enumerate(ordered)}
        return position, len(ordered)

    def _stream_time_base(self, info):
        return info.get('time_base') or Fraction(1, 1000)

    # ── export ────────────────────────────────────────────────────────────

    def export(self, keep_seconds, mute_seconds=(), include_audio=True):
        """Export kept source intervals with muted source intervals.

        Raises SmartCutUnavailable when a full re-encode is required.
        """
        if (os.path.splitext(self.source)[1].lower() not in SUPPORTED_SUFFIXES
                or os.path.splitext(self.output)[1].lower() not in SUPPORTED_SUFFIXES):
            raise SmartCutUnavailable('This file type needs a full re-encode.')
        info = self.inspect()
        info['time_base'] = self._probe_time_base()
        pts, keyframe_packets = self.scan_frames(info)
        position, total = self._frame_index_map(pts, info)
        keyframes = sorted(position[pts[i]] for i in keyframe_packets)
        if not keyframes or keyframes[0] != 0:
            raise SmartCutUnavailable('The video does not start with a keyframe.')
        rate = info['rate']
        offset = info['offset']
        ranges = keep_frame_ranges([(a - float(offset), b - float(offset)) for a, b in keep_seconds],
                                   rate, total)
        if not ranges:
            raise SmartCutUnavailable('Nothing would remain after the edit.')
        pieces = plan_pieces(ranges, keyframes, total)
        expected = sum(b - a for _, a, b in pieces)
        temp = tempfile.mkdtemp(prefix='wwr_edit_', dir=self.workdir)
        try:
            self.progress(2)
            segments = self._split_copy_segments(pieces, total, temp, info['duration'])
            files = []
            done = 0
            source_sets = None
            for index, (kind, a, b) in enumerate(pieces):
                if kind == 'copy':
                    files.extend(segments[(a, b)])
                else:
                    path = self._encode_piece(a, b, rate, offset, os.path.join(temp, f'enc{index:05d}.mkv'))
                    # Joined pieces must share identical H.264 parameter sets,
                    # or some players could misdecode them. Check each piece.
                    source_sets = source_sets or self._parameter_sets(self.source)
                    if not source_sets or self._parameter_sets(path) != source_sets:
                        raise SmartCutUnavailable('Re-encoded pieces do not match the source stream.')
                    files.append((path, b - a))
                done += b - a
                self.progress(5 + int(80 * done / max(1, expected)))
            audio_graph = None
            if include_audio and info['audio_streams']:
                intervals = [(float(offset + a / rate), float(offset + b / rate)) for a, b in ranges]
                audio_graph = edited_audio_graph(intervals, list(mute_seconds))
            self.progress(90)
            self._concat(files, rate, audio_graph, temp, info['duration'])
            self._verify(expected, rate, include_audio and bool(info['audio_streams']), info['duration'])
            self.progress(99)
            return True
        except Exception:
            try:
                if os.path.exists(self.output):
                    os.remove(self.output)
            except OSError:
                pass
            raise
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    def _probe_time_base(self):
        # Matroska stores millisecond timestamps; MP4 needs its track timescale.
        if os.path.splitext(self.source)[1].lower() == '.mkv':
            return Fraction(1, 1000)
        code, out, _ = self.runner.run(
            ['-i', self.source, '-map', '0:v:0', '-c', 'copy', '-frames:v', '1',
             '-f', 'framecrc', '-'], timeout=30, stdout=subprocess.PIPE)
        match = re.search(rb'#tb 0: (\d+)/(\d+)', out)
        if code != 0 or not match:
            raise SmartCutUnavailable('Video timing could not be read.')
        return Fraction(int(match.group(1)), int(match.group(2)))

    def _split_copy_segments(self, pieces, total, temp, duration):
        """Split the source at the needed keyframes in one packet-copy pass."""
        copies = [(a, b) for kind, a, b in pieces if kind == 'copy']
        if not copies:
            return {}
        cuts = sorted(({a for a, _ in copies} | {b for _, b in copies if b < total}) - {0})
        pattern = os.path.join(temp, 'seg%05d.mkv')
        if cuts:
            args = ['-i', self.source, '-map', '0:v:0', '-c', 'copy', '-f', 'segment',
                    '-reset_timestamps', '1', '-segment_frames', ','.join(str(c) for c in cuts),
                    pattern]
        else:  # the whole video is kept (audio-only edits)
            args = ['-i', self.source, '-map', '0:v:0', '-c', 'copy',
                    '-avoid_negative_ts', 'make_zero', pattern % 0]
        code, _, err = self.runner.run(args, timeout=max(600, duration))
        if code != 0:
            raise SmartCutUnavailable('Video could not be split for copying.')
        starts = [0] + cuts
        result = {}
        for a, b in copies:
            first, last = starts.index(a), starts.index(b) if b < total else len(starts)
            bounds = starts + [total]
            paths = [(os.path.join(temp, f'seg{i:05d}.mkv'), bounds[i + 1] - bounds[i])
                     for i in range(first, last)]
            if not all(os.path.isfile(path) for path, _ in paths):
                raise SmartCutUnavailable('Video copy segments are incomplete.')
            result[(a, b)] = paths
        return result

    def _encode_piece(self, a, b, rate, offset, path):
        # Seek half a frame early so millisecond rounding never drops frame a.
        start = offset + (a - Fraction(1, 2)) / rate
        args = []
        if start > 0:
            args += ['-ss', f'{float(start):.6f}']
        # Retime the decoded frames sequentially so the constant-rate encoder
        # never duplicates or drops one because of timestamp rounding.
        args += ['-i', self.source, '-map', '0:v:0', '-an', '-frames:v', str(b - a),
                 '-vf', f'setpts=N/({rate.numerator}/{rate.denominator})/TB',
                 '-r', f'{rate.numerator}/{rate.denominator}', *ENCODE_ARGS, path]
        code, _, err = self.runner.run(args, timeout=max(120, (b - a) / float(rate) * 20))
        if code != 0 or not os.path.isfile(path):
            raise SmartCutUnavailable('A cut point could not be re-encoded.')
        return path

    def _parameter_sets(self, path):
        code, out, _ = self.runner.run(
            ['-i', path, '-map', '0:v:0', '-c', 'copy', '-bsf:v', 'h264_mp4toannexb',
             '-frames:v', '1', '-f', 'h264', '-'], timeout=30, stdout=subprocess.PIPE)
        if code != 0:
            raise SmartCutUnavailable('Video parameters could not be read.')
        return _parameter_sets(out)

    def _concat(self, files, rate, audio_graph, temp, duration):
        listing = os.path.join(temp, 'pieces.txt')
        with open(listing, 'w', encoding='utf-8') as handle:
            handle.write('ffconcat version 1.0\n')
            for path, frames in files:
                escaped = path.replace('\\', '/').replace("'", "'\\''")
                handle.write(f"file '{escaped}'\n")
                # Exact piece length; container durations are rounded to
                # milliseconds and would accumulate drift across many cuts.
                handle.write(f"duration {float(Fraction(frames) / rate):.9f}\n")
        args = ['-f', 'concat', '-safe', '0', '-i', listing]
        if audio_graph:
            # Edited audio is encoded in the same pass that joins the copied
            # video, exactly like a normal export, so AAC timing is standard.
            args += ['-i', self.source, '-filter_complex', f'[1:a:0]{audio_graph}[edited]',
                     '-map', '0:v:0', '-map', '[edited]', '-c:v', 'copy',
                     *AUDIO_ARGS[os.path.splitext(self.output)[1].lower()]]
        else:
            args += ['-map', '0:v:0', '-c', 'copy']
        args += ['-y', self.output]
        code, _, err = self.runner.run(args, timeout=max(600, duration * 2))
        if code != 0 or not os.path.isfile(self.output):
            raise SmartCutUnavailable('Edited pieces could not be joined.')

    def _verify(self, expected, rate, has_audio, duration):
        """Exact frame count and CFR timestamps in the saved file."""
        code, out, _ = self.runner.run(
            ['-i', self.output, '-map', '0:v:0', '-c', 'copy', '-f', 'framecrc', '-'],
            timeout=max(120, duration / 4), stdout=subprocess.PIPE)
        if code != 0:
            raise SmartCutUnavailable('The edited video could not be verified.')
        text = out.decode(errors='replace')
        match = re.search(r'#tb 0: (\d+)/(\d+)', text)
        tb = Fraction(int(match.group(1)), int(match.group(2))) if match else Fraction(1, 1000)
        pts = sorted(int(line.split(',')[2]) for line in text.splitlines()
                     if line and not line.startswith('#') and line.count(',') >= 5)
        if len(pts) != expected:
            raise SmartCutUnavailable('The edited video has an unexpected frame count.')
        frame = 1 / rate
        tolerance = max(Fraction(1, 1000), tb)  # millisecond container rounding
        for index, value in enumerate(pts):
            if abs(Fraction(value) * tb - pts[0] * tb - index * frame) > tolerance:
                raise SmartCutUnavailable('The edited video timing is not continuous.')
        if has_audio:
            code, _, text = self.runner.run(['-i', self.output], timeout=30)
            info = parse_stream_info(text)
            if not info or info['audio_streams'] != 1:
                raise SmartCutUnavailable('The edited audio is missing.')
