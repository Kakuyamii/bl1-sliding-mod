
from .native_slide_audio import SlideAudio as Player, decode_embedded



class SlideAudio:
    def __init__(self, log=None, player_factory=Player):
        self.log = log or (lambda text: None)
        self.factory = player_factory
        self.players = {}
        self.kind = 'default'
        self.remaining = 1.0
        self._volume = 0.3
        self.variation = 0.06
        self.active_slide = False

    @property
    def current(self):
        return self.players.get(self.kind)

    @property
    def loaded(self):
        return bool(self.players)

    @property
    def audible_seconds(self):
        return self.current.audible_seconds if self.current else 0.0

    @property
    def rate(self):
        return self.current.rate if self.current else 1.0

    @property
    def playing(self):
        return any(p.playing for p in self.players.values())

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value):
        self._volume = value
        for player in self.players.values():
            player.volume = value

    def load(self, fallback):


        from .terrain_sound_data import WAVS_ZB64
        players = {}
        for kind, data in [('default', fallback)] + [
                (k, decode_embedded(v)) for k, v in WAVS_ZB64.items()]:
            player = self.factory(log=self.log)
            player.load(data)
            players[kind] = player
        self.players = players

    def select_surface(self, kind):

        kind = 'dirt' if kind == 'rock' else kind
        selected = kind if kind in self.players else (
            self.kind if self.active_slide else 'default')
        if selected == self.kind:
            return
        old = self.current
        self.kind = selected
        if self.active_slide:
            if old:
                old.fade_out(0.08)
            self.current.start(self.remaining, self.volume, self.variation)
            self.log('surface sound changed: ' + selected)

    def start(self, expected_seconds, volume, pitch_variation):
        self.remaining = expected_seconds
        self.volume = volume
        self.variation = pitch_variation
        self.active_slide = True
        for player in self.players.values():
            if player is not self.current:
                player.fade_out(0.06)
        if self.current:
            self.current.start(expected_seconds, volume, pitch_variation)
            self.log('surface sound: ' + self.kind)

    def set_remaining(self, seconds):
        self.remaining = seconds
        if self.current:
            self.current.set_remaining(seconds)

    def fade_out(self, seconds):
        self.active_slide = False
        for player in self.players.values():
            player.fade_out(seconds)

    def tick_native(self, paused=False):
        for player in self.players.values():
            player.tick_native(paused=paused)

    def close(self):
        self.active_slide = False
        for player in self.players.values():
            player.close()

    def status(self):
        return self.kind + ': ' + (self.current.status() if self.current else 'not loaded')
