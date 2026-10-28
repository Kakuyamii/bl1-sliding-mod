
import math
import unrealsdk


def vec(x=0,y=0,z=0):
    return unrealsdk.make_struct('Vector',X=x,Y=y,Z=z)


def ray_direction(rotation,fov,aspect,x,y):
    pitch,yaw,roll=(float(getattr(rotation,k))*math.pi/32768 for k in ('Pitch','Yaw','Roll'))
    sp,cp,sy,cy,sr,cr=math.sin(pitch),math.cos(pitch),math.sin(yaw),math.cos(yaw),math.sin(roll),math.cos(roll)
    f=(cp*cy,cp*sy,sp)
    r=(sr*sp*cy-cr*sy,sr*sp*sy+cr*cy,-sr*cp)
    u=(-cr*sp*cy-sr*sy,-cr*sp*sy+sr*cy,cr*cp)
    t=math.tan(math.radians(max(30,min(150,fov)))/2)
    d=tuple(f[i]+r[i]*x*t-u[i]*y*t/max(.5,aspect) for i in range(3))
    length=math.sqrt(sum(v*v for v in d))
    return tuple(v/length for v in d)


def ground_target(pawn,controller,bridge,aspect,x=0,y=.80):
    if controller is None or bridge is None or int(pawn.Physics)!=1:
        return None
    start=controller.CalcViewLocation
    direction=ray_direction(controller.CalcViewRotation,float(controller.FOVAngle),aspect,x,y)
    if direction[2]>=-.06:
        return None
    end=vec(start.X+direction[0]*240,start.Y+direction[1]*240,start.Z+direction[2]*240)
    actor,point,normal,info=bridge.trace(pawn,HitLocation=vec(),HitNormal=vec(),TraceStart=start,
        TraceEnd=end,bTraceActors=True,Extent=vec(),HitInfo=unrealsdk.make_struct('Engine.Actor:TraceHitInfo'),ExtraTraceFlags=1)
    if actor is None and info.HitComponent is None:
        return None
    if normal.Z < float(pawn.WalkableFloorZ):
        return None
    distance=math.sqrt((point.X-start.X)**2+(point.Y-start.Y)**2+(point.Z-start.Z)**2)
    if not 45<=distance<=230:
        return None
    return point,normal


def local_offset(delta,yaw):
    a=yaw*math.pi/32768
    return (delta[0]*math.cos(a)+delta[1]*math.sin(a),
            -delta[0]*math.sin(a)+delta[1]*math.cos(a),delta[2])
