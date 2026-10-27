"""Native WASAPI microphone streams, without SoundCard's format rewriting.

SoundCard's Windows mono request is unreliable. Keep GetMixFormat unchanged,
read its native interleaved frames, then adapt to the recorder's stereo WAV.
Private backend access is isolated here alongside the PROPVARIANT repair.
"""
import numpy as np


def native_microphone_recorder(device, buffer_seconds=0.5):
    from soundcard import mediafoundation as backend
    ffi, com = backend._ffi, backend._com
    ptr = device._audio_client()
    fmt = ffi.new('WAVEFORMATEXTENSIBLE**')
    try:
        com.check_error(ptr[0][0].lpVtbl.GetMixFormat(ptr[0], fmt))
        wave = fmt[0][0].Format
        rate, channels = int(wave.nSamplesPerSec), int(wave.nChannels)
        # WAVEFORMATEX is packed to 18 bytes by Windows. SoundCard's CFFI
        # WAVEFORMATEXTENSIBLE declaration has padding, so read the subtype
        # at native offset 24 instead of its misaligned SubFormat field.
        # WASAPI shared-mode mix is normally float32. Reject other formats
        # explicitly rather than interpreting PCM bytes as floats.
        if wave.wBitsPerSample != 32 or wave.nBlockAlign != channels * 4:
            raise RuntimeError('Microphone mix format is not float32')
        if wave.wFormatTag != 3 and not (
            wave.wFormatTag == 0xFFFE and
            bytes(ffi.buffer(ffi.cast('char *', fmt[0]), 40))[24:40] ==
            bytes.fromhex('0300000000001000800000aa00389b71')
        ):
            raise RuntimeError('Microphone mix format is not IEEE float')
        # No resample/remix flags and, crucially, no mutation of nChannels,
        # sample rate, channel mask, or sample subtype from GetMixFormat.
        com.check_error(ptr[0][0].lpVtbl.Initialize(
            ptr[0], backend._ole32.AUDCLNT_SHAREMODE_SHARED,
            0, int(buffer_seconds * 10_000_000), 0, fmt[0], ffi.NULL))
        class NativeMixRecorder(backend._Recorder):
            def __enter__(self):
                try:
                    return super().__enter__()
                except Exception:
                    if getattr(self, '_ppCaptureClient', None) is not None:
                        com.release(self._ppCaptureClient)
                    com.release(self._ptr)
                    raise

            def __exit__(self, exc_type, exc_value, traceback):
                try:
                    com.check_error(self._ptr[0][0].lpVtbl.Stop(self._ptr[0]))
                finally:
                    com.release(self._ppCaptureClient)
                    com.release(self._ptr)

        stream = NativeMixRecorder.__new__(NativeMixRecorder)
        stream._ptr = ptr
        stream.channelmap = list(range(channels))
        stream.samplerate = rate
        stream._idle_start_time = None
        return stream, rate
    except Exception:
        com.release(ptr)
        raise
    finally:
        if fmt[0] != ffi.NULL:
            backend._ole32.CoTaskMemFree(fmt[0])


def microphone_stereo(data):
    """Preserve a lone active input at full level in both output channels."""
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 1:
        data = data[:, None]
    if data.shape[1] == 1:
        return np.repeat(data, 2, axis=1)
    # USB interfaces often expose two inputs with only one connected.
    # Copy only when the other channel is silent, preserving true stereo.
    stereo = data[:, :2].copy()
    energy = np.max(np.abs(stereo), axis=0) if len(stereo) else np.zeros(2)
    if energy[0] == 0 and energy[1] > 0:
        stereo[:, 0] = stereo[:, 1]
    elif energy[1] == 0 and energy[0] > 0:
        stereo[:, 1] = stereo[:, 0]
    return stereo
