"""SoundCard Windows ABI repair shared by EXE and MSIX builds.

SoundCard 0.4.x declares only the pointer arm of PROPVARIANT. On x64 this
allocates 16 bytes, but IPropertyStore.GetValue writes a 24-byte PROPVARIANT
(the BLOB/counted-array arm includes both a length and a pointer). That write
corrupts the native heap. Keep the library API and audio pipeline unchanged.
"""
import sys


def repair_soundcard_propvariant(backend=None):
    if backend is None:
        if sys.platform != "win32":
            return False
        from soundcard import mediafoundation as backend
    ffi, ole32 = backend._ffi, backend._ole32
    native_size = max(ffi.sizeof("PROPVARIANT"), ffi.sizeof("BLOB_PROPVARIANT"))
    if getattr(backend._PropVariant, "_wwr_native_size", 0) >= native_size:
        return False
    # Leave a future correctly-sized upstream implementation alone.
    if ffi.sizeof("PROPVARIANT") >= ffi.sizeof("BLOB_PROPVARIANT"):
        return False

    class NativePropVariant:
        _wwr_native_size = native_size

        def __init__(self):
            self.ptr = ffi.NULL
            allocation = ole32.CoTaskMemAlloc(native_size)
            if allocation == ffi.NULL:
                raise MemoryError("Cannot allocate Windows audio property")
            # VT_EMPTY and all union/reserved bytes must be initialized before
            # GetValue, including its failure path.
            ffi.buffer(allocation, native_size)[:] = b"\0" * native_size
            self.ptr = ffi.cast("PROPVARIANT *", allocation)

        def close(self):
            pointer, self.ptr = self.ptr, ffi.NULL
            if pointer != ffi.NULL:
                try:
                    ole32.PropVariantClear(pointer)
                finally:
                    # PropVariantClear frees the contained value, not the outer
                    # structure. The original wrapper also leaked this block.
                    ole32.CoTaskMemFree(pointer)

        def __del__(self):
            try:
                self.close()
            except Exception:
                pass  # Never raise from shutdown/partial-construction cleanup.

    backend._PropVariant = NativePropVariant
    return True
