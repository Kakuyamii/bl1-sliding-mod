

from __future__ import annotations

import base64
import io
import random
import sys
import threading
import time
import wave
import zlib
from array import array
from collections.abc import Callable
from typing import Any

RATE_MIN = 0.6
RATE_MAX = 1.7
RATE_SMOOTH = 0.25
ATTACK_SECONDS = 0.02
SILENCE_FRACTION = 0.02
NORMALISED_PEAK = 0.9
BUFFER_FRAMES = 1024
BUFFER_COUNT = 3

IDLE = 0
PLAYING = 1


def decode_embedded(zb64: str) -> bytes:
    return zlib.decompress(base64.b64decode(zb64))


class WaveOutSink:


    def __init__(self, channels: int, rate: int) -> None:
        import ctypes
        from ctypes import wintypes as wt

        self._ct = ctypes
        self._winmm = ctypes.WinDLL("winmm")

        class WAVEFORMATEX(ctypes.Structure):
            _pack_ = 1
            _fields_ = [
                ("wFormatTag", wt.WORD),
                ("nChannels", wt.WORD),
                ("nSamplesPerSec", ctypes.c_uint32),
                ("nAvgBytesPerSec", ctypes.c_uint32),
                ("nBlockAlign", wt.WORD),
                ("wBitsPerSample", wt.WORD),
                ("cbSize", wt.WORD),
            ]

        class WAVEHDR(ctypes.Structure):
            _fields_ = [
                ("lpData", ctypes.c_void_p),
                ("dwBufferLength", ctypes.c_uint32),
                ("dwBytesRecorded", ctypes.c_uint32),
                ("dwUser", ctypes.c_size_t),
                ("dwFlags", ctypes.c_uint32),
                ("dwLoops", ctypes.c_uint32),
                ("lpNext", ctypes.c_void_p),
                ("reserved", ctypes.c_size_t),
            ]

        self._WHDR_INQUEUE = 0x10
        w = self._winmm
        w.waveOutOpen.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_uint,
            ctypes.POINTER(WAVEFORMATEX),
            ctypes.c_size_t,
            ctypes.c_size_t,
            ctypes.c_uint32,
        ]
        w.waveOutOpen.restype = ctypes.c_uint
        for name in ("waveOutPrepareHeader", "waveOutUnprepareHeader", "waveOutWrite"):
            fn = getattr(w, name)
            fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(WAVEHDR), ctypes.c_uint]
            fn.restype = ctypes.c_uint
        for name in ("waveOutReset", "waveOutClose"):
            fn = getattr(w, name)
            fn.argtypes = [ctypes.c_void_p]
            fn.restype = ctypes.c_uint

        block = channels * 2
        fmt = WAVEFORMATEX(1, channels, rate, rate * block, block, 16, 0)
        self._hwo = ctypes.c_void_p()
        wave_mapper = 0xFFFFFFFF
        callback_null = 0
        res = w.waveOutOpen(ctypes.byref(self._hwo), wave_mapper, ctypes.byref(fmt), 0, 0, callback_null)
        if res != 0:
            raise OSError(f"waveOutOpen failed with code {res}")

        self._bufsize = BUFFER_FRAMES * block
        self._bufs = []
        self._hdrs = []
        for _ in range(BUFFER_COUNT):
            buf = ctypes.create_string_buffer(self._bufsize)
            hdr = WAVEHDR()
            hdr.lpData = ctypes.addressof(buf)
            hdr.dwBufferLength = self._bufsize
            res = w.waveOutPrepareHeader(self._hwo, ctypes.byref(hdr), ctypes.sizeof(hdr))
            if res != 0:
                raise OSError(f"waveOutPrepareHeader failed with code {res}")
            self._bufs.append(buf)
            self._hdrs.append(hdr)

    def has_free_slot(self) -> bool:
        return any(not (h.dwFlags & self._WHDR_INQUEUE) for h in self._hdrs)

    def write(self, data: bytes) -> bool:
        ct = self._ct
        for buf, hdr in zip(self._bufs, self._hdrs):
            if hdr.dwFlags & self._WHDR_INQUEUE:
                continue
            n = min(len(data), self._bufsize)
            ct.memmove(buf, data, n)
            hdr.dwBufferLength = n
            res = self._winmm.waveOutWrite(self._hwo, ct.byref(hdr), ct.sizeof(hdr))
            if res != 0:
                raise OSError(f"waveOutWrite failed with code {res}")
            return True
        return False

    def close(self) -> None:
        ct = self._ct
        w = self._winmm
        try:
            w.waveOutReset(self._hwo)
            for hdr in self._hdrs:
                w.waveOutUnprepareHeader(self._hwo, ct.byref(hdr), ct.sizeof(hdr))
            w.waveOutClose(self._hwo)
        except Exception:
            pass


class SlideAudio:
    def __init__(
        self,
        sink_factory: Callable[[int, int], Any] | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self._sink_factory = sink_factory or WaveOutSink
        self._log = log or (lambda _msg: None)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._closing = False
        self._sink: Any = None
        self._disabled = False
        self.error = ""

        self.channels = 2
        self.rate_hz = 44100
        self._src: array | None = None
        self._frames = 0
        self._audible_frames = 0

        self._state = IDLE
        self._pos = 0.0
        self._base_rate = 1.0
        self._jitter = 1.0
        self._gain = 1.0
        self._fade_step = 0.0
        self._age = 0
        self.volume = 0.3
        self.remaining: float | None = None


    @property
    def loaded(self) -> bool:
        return self._src is not None

    def load(self, wav_bytes: bytes) -> None:

        with wave.open(io.BytesIO(wav_bytes)) as w:
            ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            raw = w.readframes(n)
        if width != 2 or ch not in (1, 2):
            raise ValueError(f"need 16-bit mono/stereo PCM, got {width * 8}-bit x{ch}")
        arr = array("h")
        arr.frombytes(raw)
        if sys.byteorder == "big":
            arr.byteswap()
        peak = max((abs(x) for x in arr), default=0)
        if peak == 0:
            raise ValueError("the sound file is silent")
        scale = NORMALISED_PEAK * 32767 / peak
        arr = array("h", (int(x * scale) for x in arr))


        win = max(1, rate // 100)
        threshold = SILENCE_FRACTION * 32767
        audible = n
        for start in range(n - win, -1, -win):
            seg = arr[start * ch : (start + win) * ch]
            if max(abs(x) for x in seg) > threshold:
                audible = min(n, start + win)
                break
        with self._lock:
            self.channels, self.rate_hz = ch, rate
            self._src, self._frames, self._audible_frames = arr, n, max(win, audible)


    @property
    def audible_seconds(self) -> float:
        return self._audible_frames / self.rate_hz if self._src is not None else 0.0

    def start(self, expected_seconds: float, volume: float, pitch_variation: float) -> None:

        if self._src is None or self._disabled:
            return
        expected = max(0.2, expected_seconds)
        desired = self._audible_frames / (expected * self.rate_hz)
        with self._lock:
            self._jitter = 1.0 + random.uniform(-pitch_variation, pitch_variation)
            self._base_rate = min(RATE_MAX, max(RATE_MIN, desired))
            self._pos = 0.0
            self._gain = 1.0
            self._fade_step = 0.0
            self._age = 0
            self.volume = volume
            self.remaining = expected
            self._state = PLAYING
        self._ensure_thread()
        self._wake.set()

    def set_remaining(self, seconds: float) -> None:
        self.remaining = seconds

    def fade_out(self, seconds: float) -> None:
        with self._lock:
            if self._state != PLAYING:
                return
            step = 1.0 / (max(0.005, seconds) * self.rate_hz)
            self._fade_step = max(self._fade_step, step)

    @property
    def playing(self) -> bool:
        return self._state == PLAYING

    @property
    def rate(self) -> float:
        return self._base_rate * self._jitter

    def status(self) -> str:
        if self._disabled:
            return f"off ({self.error})"
        if self._src is None:
            return "not loaded"
        if self._state == PLAYING:
            return f"playing rate {self.rate:.2f} gain {self._gain:.2f}"
        return "ready"


    def render(self, nframes: int) -> bytes:

        ch = self.channels
        out = array("h", bytes(nframes * ch * 2))
        with self._lock:
            src = self._src
            if self._state != PLAYING or src is None:
                return out.tobytes()
            frames = self._frames
            pos = self._pos
            gain = self._gain
            age = self._age
            fade = self._fade_step
            vol = self.volume

            if fade == 0.0 and self.remaining is not None and self.remaining > 0.05:
                left = self._audible_frames - pos
                if left > 0:
                    desired = left / (self.remaining * self.rate_hz)
                    desired = min(RATE_MAX, max(RATE_MIN, desired))
                    self._base_rate += (desired - self._base_rate) * RATE_SMOOTH
            rate = self._base_rate * self._jitter
            attack = max(1.0, ATTACK_SECONDS * self.rate_hz)

            for i in range(nframes):
                ip = int(pos)
                if ip >= frames - 1:
                    self._state = IDLE
                    break
                frac = pos - ip
                g = vol * gain * (age / attack if age < attack else 1.0)
                base = ip * ch
                o = i * ch
                for c in range(ch):
                    a = src[base + c]
                    v = int((a + (src[base + ch + c] - a) * frac) * g)
                    out[o + c] = 32767 if v > 32767 else (-32768 if v < -32768 else v)
                pos += rate
                age += 1
                if fade:
                    gain -= fade
                    if gain <= 0.0:
                        self._state = IDLE
                        break
            self._pos, self._gain, self._age = pos, gain, age
        return out.tobytes()


    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._closing = False
            self._thread = threading.Thread(target=self._run, name="SlidingAudio", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while not self._closing:
            try:
                if self._state != PLAYING:
                    self._wake.wait(0.25)
                    self._wake.clear()
                    continue
                if self._sink is None:
                    self._sink = self._sink_factory(self.channels, self.rate_hz)
                    self._log("audio device opened")
                if self._sink.has_free_slot():
                    self._sink.write(self.render(BUFFER_FRAMES))
                else:
                    time.sleep(0.003)
            except Exception as ex:
                self._disabled = True
                self._state = IDLE
                self.error = f"{type(ex).__name__}: {ex}"
                self._log(f"audio disabled: {self.error}")
                return

    def close(self) -> None:
        self._closing = True
        self._state = IDLE
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(0.5)
        if self._sink is not None:
            try:
                self._sink.close()
            finally:
                self._sink = None
