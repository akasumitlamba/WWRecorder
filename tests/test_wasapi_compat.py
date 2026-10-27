import gc
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import pytest
import cffi
from wasapi_compat import repair_soundcard_propvariant


def backend_with_allocator():
    ffi = cffi.FFI()
    ffi.cdef('''
        typedef struct { unsigned short vt, r1, r2, r3; void *data; } PROPVARIANT;
        typedef struct { unsigned int size; void *data; } BLOB;
        typedef struct { unsigned short vt, r1, r2, r3; BLOB blob; } BLOB_PROPVARIANT;
    ''')
    allocations, cleared, freed = [], [], []
    def allocate(size):
        buf = ffi.new("char[]", size + 16)
        ffi.buffer(buf, size + 16)[:] = b"\xa5" * (size + 16)
        allocations.append((size, buf))
        return buf
    backend = SimpleNamespace(_ffi=ffi, _ole32=SimpleNamespace(
        CoTaskMemAlloc=allocate, PropVariantClear=cleared.append, CoTaskMemFree=freed.append),
        _PropVariant=type("OldPropVariant", (), {}))
    return backend, allocations, cleared, freed


def test_native_property_write_fits_allocation_and_clear_free_once():
    backend, allocations, cleared, freed = backend_with_allocator()
    assert repair_soundcard_propvariant(backend)
    value = backend._PropVariant()
    size, buf = allocations[0]
    assert size == backend._ffi.sizeof("BLOB_PROPVARIANT")
    assert bytes(backend._ffi.buffer(buf, size)) == b"\0" * size
    native = backend._ffi.cast("BLOB_PROPVARIANT*", value.ptr)
    native.vt = 65
    native.blob.size = 40
    native.blob.data = backend._ffi.cast("void*", 1234)
    assert bytes(backend._ffi.buffer(buf, size + 16)[size:]) == b"\xa5" * 16
    value.close()
    value.close()
    del value
    gc.collect()
    assert len(cleared) == len(freed) == 1


def test_repair_is_idempotent():
    backend, *_ = backend_with_allocator()
    assert repair_soundcard_propvariant(backend)
    wrapper = backend._PropVariant
    assert not repair_soundcard_propvariant(backend)
    assert backend._PropVariant is wrapper


def test_allocation_failure_is_safe():
    backend, _, cleared, freed = backend_with_allocator()
    backend._ole32.CoTaskMemAlloc = lambda size: backend._ffi.NULL
    repair_soundcard_propvariant(backend)
    with pytest.raises(MemoryError):
        backend._PropVariant()
    gc.collect()
    assert not cleared and not freed
