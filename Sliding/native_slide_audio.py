
from __future__ import annotations
import ctypes as ct
import io
import random
import time
import wave
from .slide_audio import SlideAudio as Decoder, decode_embedded, RATE_MIN, RATE_MAX
from .fmod_bridge import Bridge

class SlideAudio(Decoder):
    def __init__(self, log=None, bridge_factory=Bridge):
        super().__init__(log=log)
        self._bridge_factory = bridge_factory
        self._bridge = None
        self._sound = None
        self._channel = None
        self._native_wav = None
        self._started = 0.0
        self._last_tick = 0.0
        self._fade_start = None
        self._fade_duration = 0.0
        self._fade_gain = 1.0
        self._paused_at = None
        self._gain = 0.0

    def load(self, wav_bytes):
        if self._channel or self._sound:
            self.close()
        super().load(wav_bytes)

        stream = io.BytesIO()
        with wave.open(stream, 'wb') as wav:
            wav.setnchannels(self.channels)
            wav.setsampwidth(2)
            wav.setframerate(self.rate_hz)
            wav.writeframes(self._src.tobytes())
        self._native_wav = stream.getvalue()
        self._disabled = False
        self.error = ''

    def _prepare(self):
        from mods_base import SETTINGS_DIR
        if self._bridge is None:
            self._bridge = self._bridge_factory()
            self._log(f'using game FMOD {self._bridge.version:#x}, existing SFX group')
        if not self._bridge.alive():
            raise RuntimeError('Game audio system changed; reload the mod')
        self._bridge.sfx = self._bridge.find_sfx()
        if not self._sound:
            path = SETTINGS_DIR / 'Sliding_FMOD_normalized.wav'
            path.write_bytes(self._native_wav)
            sound = ct.c_void_p()

            self._bridge.check(self._bridge.create(self._bridge.system, str(path).encode('mbcs'), 0x9, None, ct.byref(sound)), 'load slide WAV')
            self._sound = sound.value

    def _owns(self, channel):
        sound = ct.c_void_p()
        return self._bridge.current_sound(channel, ct.byref(sound)) == 0 and sound.value == self._sound

    def _stop(self):
        channel, self._channel = self._channel, None
        if channel and self._bridge and self._bridge.alive() and self._owns(channel):

            self._bridge.stop(channel)
        self._fade_start = None
        self._paused_at = None
        self._gain = 0.0

    def _fail(self, error):
        self.error = f'{type(error).__name__}: {error}'
        self._disabled = True
        try:
            self._stop()
        except Exception:
            self._channel = None
        self._log('native audio disabled: ' + self.error)

    def start(self, expected_seconds, volume, pitch_variation):
        if not self.loaded or self._disabled:
            return
        try:
            self._prepare()
            self._stop()
            expected = max(0.2, float(expected_seconds))
            self._jitter = 1.0 + random.uniform(-pitch_variation, pitch_variation)
            self._base_rate = min(RATE_MAX, max(RATE_MIN, self.audible_seconds / (expected + 0.15)))
            self.volume = max(0.0, min(1.0, volume))
            self.remaining = expected
            channel = ct.c_void_p()
            b = self._bridge
            b.check(b.play(b.system, -1, self._sound, 1, ct.byref(channel)), 'start paused slide')
            self._channel = channel.value
            b.check(b.set_group(self._channel, b.sfx), 'route slide to SFX')
            b.check(b.set_frequency(self._channel, self.rate_hz * self.rate), 'set slide pitch')
            b.check(b.set_volume(self._channel, 0.0), 'set initial slide gain')
            b.check(b.set_paused(self._channel, 0), 'start slide')
            self._started = self._last_tick = time.perf_counter()
        except Exception as error:
            self._fail(error)

    @property
    def playing(self):
        return self._channel is not None

    def set_remaining(self, seconds):
        self.remaining = max(0.0, float(seconds))

    def fade_out(self, seconds):
        if not self.playing:
            return
        now = time.perf_counter()
        duration = max(0.005, float(seconds))
        if self._fade_start is None or now + duration < self._fade_start + self._fade_duration:
            self._fade_start = now
            self._fade_duration = duration
            self._fade_gain = self._gain

    def tick_native(self, paused=False):
        if not self.playing:
            return
        try:
            b = self._bridge
            if not b.alive():

                self._channel = self._sound = None
                raise RuntimeError('Game audio system changed; reload the mod')
            if not self._owns(self._channel):
                self._channel = None
                return
            now = time.perf_counter()
            if paused:
                if self._paused_at is None:
                    b.check(b.set_paused(self._channel, 1), 'pause slide')
                    self._paused_at = now
                return
            if self._paused_at is not None:
                elapsed = now - self._paused_at
                self._started += elapsed
                if self._fade_start is not None:
                    self._fade_start += elapsed
                self._last_tick = now
                self._paused_at = None
                b.check(b.set_paused(self._channel, 0), 'resume slide')
            active = ct.c_int()
            result = b.is_playing(self._channel, ct.byref(active))
            if result or not active.value:

                self._channel = None
                return
            dt = max(0.0, min(0.1, now - self._last_tick))
            self._last_tick = now
            if self._fade_start is not None:
                fraction = (now - self._fade_start) / self._fade_duration
                if fraction >= 1.0:
                    self._stop()
                    return
                self._gain = self._fade_gain * max(0.0, 1.0 - fraction)
            else:
                self._gain = min(1.0, (now - self._started) / 0.02)
                if self.remaining is not None and self.remaining > 0.05:
                    position = ct.c_uint()
                    b.check(b.position(self._channel, ct.byref(position), 1), 'get slide position')
                    left = max(0.0, self.audible_seconds - position.value/1000.0)
                    target = min(RATE_MAX, max(RATE_MIN, left/(self.remaining + 0.15)))

                    self._base_rate += (target - self._base_rate) * (1.0 - 0.75**(dt/0.023))
                    b.check(b.set_frequency(self._channel, self.rate_hz * self.rate), 'update slide pitch')
            b.check(b.set_volume(self._channel, max(0.0, min(1.0, self.volume))*self._gain), 'update slide gain')
        except Exception as error:
            self._fail(error)

    def close(self):
        try:
            self._stop()
            if self._sound and self._bridge and self._bridge.alive():
                self._bridge.release(self._sound)
        except Exception as error:
            self._log(f'native cleanup: {error}')
        finally:
            self._sound = self._channel = self._bridge = None
            self._disabled = False
            self.error = ''

    def status(self):
        if self._disabled:
            return 'FMOD off (' + self.error + ')'
        if not self.loaded:
            return 'FMOD not loaded'
        if self.playing:
            return f'FMOD SFX rate {self.rate:.2f} gain {self._gain:.2f}'
        return 'FMOD ready'
