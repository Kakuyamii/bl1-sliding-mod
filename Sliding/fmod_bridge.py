
from __future__ import annotations
import ctypes as ct
import hashlib
import struct
from pathlib import Path

EXE_SHA256 = '71b58c404a5124b984a1ca42ab906479b57b5ad7b02944840433f2fed09dc42a'
DLL_SHA256 = 'dff5deb7b89aab3125b65e4f3a57540b4145ffc5004f66b43ff95fca9d17a8e3'

class FMODError(RuntimeError):
    pass

class Bridge:
    def __init__(self):
        if ct.sizeof(ct.c_void_p) != 4:
            raise FMODError('Only the verified 32-bit BL1 build is supported')
        k = ct.WinDLL('kernel32', use_last_error=True)
        k.GetModuleHandleW.argtypes = [ct.c_wchar_p]
        k.GetModuleHandleW.restype = ct.c_void_p
        k.GetModuleFileNameW.argtypes = [ct.c_void_p, ct.c_wchar_p, ct.c_uint]
        k.GetModuleFileNameW.restype = ct.c_uint
        k.GetCurrentProcess.restype = ct.c_void_p
        k.ReadProcessMemory.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_void_p, ct.c_size_t, ct.POINTER(ct.c_size_t)]
        k.ReadProcessMemory.restype = ct.c_int
        self.k = k
        self.process = k.GetCurrentProcess()
        self.base = k.GetModuleHandleW(None)
        dll = k.GetModuleHandleW('fmodex.dll')
        if not dll:
            raise FMODError('The game has not loaded fmodex.dll')
        for module, expected in ((self.base, EXE_SHA256), (dll, DLL_SHA256)):
            path = ct.create_unicode_buffer(32768)
            length = k.GetModuleFileNameW(module, path, len(path))
            if not 0 < length < len(path):
                raise FMODError('Could not identify game module')
            if hashlib.sha256(Path(path.value).read_bytes()).hexdigest() != expected:
                raise FMODError('Unrecognized executable or FMOD DLL; refusing native calls')
        self.global_address = self.base + 0x1b6ff84

        signature = b'\x68' + struct.pack('<I', self.global_address) + bytes.fromhex('e8 82 9e 29 01')
        if self.read(self.base + 0x1414aa, len(signature)) != signature:
            raise FMODError('Loaded FMOD creation call does not match the verified build')
        self.system = self.current_system()
        if not self.system:
            raise FMODError('Game audio system is not initialized')
        self.dll = ct.WinDLL('fmodex.dll', handle=dll)
        P, I, U, F = ct.c_void_p, ct.c_int, ct.c_uint, ct.c_float
        def bind(name, *types):
            fn = getattr(self.dll, '_' + name + '@' + str(4*len(types)))
            fn.argtypes, fn.restype = list(types), I
            return fn
        self.version_fn = bind('FMOD_System_GetVersion', P, ct.POINTER(U))
        self.master = bind('FMOD_System_GetMasterChannelGroup', P, ct.POINTER(P))
        self.group_count = bind('FMOD_ChannelGroup_GetNumGroups', P, ct.POINTER(I))
        self.group_at = bind('FMOD_ChannelGroup_GetGroup', P, I, ct.POINTER(P))
        self.group_name = bind('FMOD_ChannelGroup_GetName', P, P, I)
        self.create = bind('FMOD_System_CreateSound', P, ct.c_char_p, U, P, ct.POINTER(P))
        self.release = bind('FMOD_Sound_Release', P)
        self.play = bind('FMOD_System_PlaySound', P, I, P, I, ct.POINTER(P))
        self.set_group = bind('FMOD_Channel_SetChannelGroup', P, P)
        self.set_frequency = bind('FMOD_Channel_SetFrequency', P, F)
        self.set_volume = bind('FMOD_Channel_SetVolume', P, F)
        self.set_paused = bind('FMOD_Channel_SetPaused', P, I)
        self.is_playing = bind('FMOD_Channel_IsPlaying', P, ct.POINTER(I))
        self.position = bind('FMOD_Channel_GetPosition', P, ct.POINTER(U), U)
        self.stop = bind('FMOD_Channel_Stop', P)
        self.current_sound = bind('FMOD_Channel_GetCurrentSound', P, ct.POINTER(P))
        version = U()
        self.check(self.version_fn(self.system, ct.byref(version)), 'get version')
        self.version = version.value
        if self.version < 0x42402 or self.version >= 0x50000:
            raise FMODError(f'Unexpected FMOD version {self.version:#x}')
        self.sfx = self.find_sfx()

    def read(self, address, size):
        data = ct.create_string_buffer(size)
        count = ct.c_size_t()
        if not self.k.ReadProcessMemory(self.process, address, data, size, ct.byref(count)) or count.value != size:
            raise FMODError('Game memory is not readable')
        return data.raw

    def current_system(self):
        return struct.unpack('<I', self.read(self.global_address, 4))[0]

    def alive(self):
        return self.current_system() == self.system

    @staticmethod
    def check(result, operation):
        if result:
            raise FMODError(f'{operation}: FMOD result {result}')

    def find_sfx(self):
        import unrealsdk


        expected = (bytes.fromhex('8b 86 30 02 00 00 8d ae 1c 02 00 00 55 68')
                    + struct.pack('<I', self.base + 0x166527c)
                    + bytes.fromhex('50 e8 1e 9b 29 01'))
        if self.read(self.base + 0x1418cc, len(expected)) != expected:
            raise FMODError('Loaded SFX group initialization does not match the verified build')
        matches = []
        diagnostics = []
        for device in unrealsdk.find_all('FMODAudioDevice', exact=False):
            address = device._get_address()
            fields = self.read(address + 0x21c, 0x18)
            group = struct.unpack_from('<I', fields, 0)[0]
            system = struct.unpack_from('<I', fields, 0x14)[0]
            if system != self.system or not group:
                continue
            name = ct.create_string_buffer(256)
            self.check(self.group_name(group, name, len(name)), 'validate device SFX group')
            diagnostics.append(name.value.decode('ascii', errors='replace'))
            if name.value.lower() == b'sfx':
                matches.append(group)
        unique = set(matches)
        if len(unique) != 1:
            raise FMODError(f'Expected one live SFX group for FMOD {self.version:#x}; found {diagnostics!r}')
        return unique.pop()
