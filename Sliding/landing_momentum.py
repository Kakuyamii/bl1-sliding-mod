import math


class LandingMomentum:
    def __init__(self):
        self.reset()

    def reset(self):
        self.was_air = False
        self.air_velocity = (0.0, 0.0, 0.0)
        self.landed_at = -1e9
        self.pressed_at = -1e9
        self.available = False

    def press(self, now):
        self.pressed_at = now

    def update(self, airborne, velocity, now):
        if airborne:
            self.air_velocity = tuple(float(v) for v in velocity)
            self.available = False
        elif self.was_air:
            self.landed_at = now
            vx, vy, vz = self.air_velocity
            self.available = vz < -700.0 and math.hypot(vx, vy) >= 150.0
        self.was_air = airborne
        if now-self.landed_at > .20:
            self.available = False

    def reference(self, now):
        if not self.available or not 0 <= now-self.landed_at <= .20:
            return None
        vx, vy, vz = self.air_velocity
        return vx, vy, math.hypot(vx, vy)

    def consume(self, now, before_landing=False):
        ref = self.reference(now)
        if ref is None or (before_landing and not 0 <= self.landed_at-self.pressed_at <= .18):
            return None
        self.available = False
        bonus = min(450.0, max(0.0, -self.air_velocity[2]-700.0)*.25)
        return ref[0], ref[1], ref[2], bonus
