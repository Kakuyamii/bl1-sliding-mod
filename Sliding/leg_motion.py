pass
import math

class LegMotion:
    def __init__(self):
        self.last_yaw=None
        self.turn=0.0
        self.phase=0.0
    def step(self,yaw,dt,speed=1.0):
        dt=max(0.0,min(.1,dt))
        if dt<.001:return self.values(speed)
        rate=0.0
        if self.last_yaw is not None:
            delta=(yaw-self.last_yaw+32768)%65536-32768
            rate=max(-240,min(240,delta*180/32768/dt))
        self.last_yaw=yaw
        target=-rate/240
        self.turn+=(target-self.turn)*(1-math.exp(-10*dt))
        self.phase+=dt
        return self.values(speed)
    def values(self,speed):
        strength=max(.35,min(1.0,speed))
        return (0.0,0.0,0.0)
