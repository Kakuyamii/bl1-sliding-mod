
import math

def surface_offset(normal,yaw,lift):
    nx,ny,nz=(float(v) for v in normal)
    if not all(math.isfinite(v) for v in (nx,ny,nz,yaw,lift)) or nz<.2:return 0.0
    angle=yaw*math.pi/32768
    slope=-(nx*math.cos(angle)+ny*math.sin(angle))/nz
    return max(-4.,min(6.,max(0.,lift)*.20+slope*6.))
