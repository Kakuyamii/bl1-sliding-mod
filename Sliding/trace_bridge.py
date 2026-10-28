
import ctypes as ct
import hashlib
import struct
from pathlib import Path
import unrealsdk

EXE_SHA256 = '71b58c404a5124b984a1ca42ab906479b57b5ad7b02944840433f2fed09dc42a'


def call_with_index_restored(index, call, **kwargs):
    original = index.value
    if original != 277:
        raise RuntimeError(f'Trace native index changed: {original}; expected 277')
    try:
        index.value = 0
        return call(**kwargs)
    finally:
        index.value = original


class TraceBridge:
    def __init__(self, log):
        if ct.sizeof(ct.c_void_p) != 4:
            raise RuntimeError('Trace bridge requires verified 32-bit BL1')
        k = ct.WinDLL('kernel32', use_last_error=True)
        k.GetModuleHandleW.argtypes = [ct.c_wchar_p]
        k.GetModuleHandleW.restype = ct.c_void_p
        k.GetModuleFileNameW.argtypes = [ct.c_void_p, ct.c_wchar_p, ct.c_uint]
        k.GetModuleFileNameW.restype = ct.c_uint
        k.GetCurrentProcess.restype = ct.c_void_p
        k.ReadProcessMemory.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_void_p,
                                       ct.c_size_t, ct.POINTER(ct.c_size_t)]
        k.ReadProcessMemory.restype = ct.c_int
        base = k.GetModuleHandleW(None)
        path = ct.create_unicode_buffer(32768)
        length = k.GetModuleFileNameW(base, path, len(path))
        if not 0 < length < len(path):
            raise RuntimeError('Cannot identify executable for Trace bridge')
        if hashlib.sha256(Path(path.value).read_bytes()).hexdigest() != EXE_SHA256:
            raise RuntimeError('Unverified executable; refusing Trace workaround')

        def read(address, size):
            data = ct.create_string_buffer(size)
            count = ct.c_size_t()
            if not k.ReadProcessMemory(k.GetCurrentProcess(), address, data, size,
                                       ct.byref(count)) or count.value != size:
                raise RuntimeError('Cannot read Trace validation memory')
            return data.raw


        if read(base + 0x19dfe4, 13) != bytes.fromhex('66 39 83 98 00 00 00 0f 85 f0 01 00 00'):
            raise RuntimeError('ProcessEvent native-index check differs from verified build')
        self.function = unrealsdk.find_object('Function', 'Engine.Actor:Trace')
        address = self.function._get_address()
        data = read(address + 0x94, 0x20)
        flags, native = struct.unpack_from('<IH', data)
        params_size, return_offset = struct.unpack_from('<HH', data, 0x12)
        entry = struct.unpack_from('<I', data, 0x1c)[0]
        if (not flags & 0x400 or native != 277 or params_size != 100
                or return_offset != 96 or entry != base + 0x5679d0):
            raise RuntimeError(f'Unexpected Trace layout: flags={flags:#x}, index={native}, '
                               f'params={params_size}, return={return_offset}, entry={entry:#x}')


        script, script_size = struct.unpack('<II', read(address + 0x54, 8))
        if not script or not 41 <= script_size <= 4096:
            raise RuntimeError(f'Trace parameter bytecode unavailable: size={script_size}')
        read(script, script_size)
        self.read = read
        self.base = base
        self.index = ct.c_uint16.from_address(address + 0x98)
        log(f'Trace bridge verified: native index 277; script bytes={script_size}; '
            'temporary clear/restore enabled')

    def trace(self, source, **kwargs):

        return call_with_index_restored(self.index, source.Trace, **kwargs)
