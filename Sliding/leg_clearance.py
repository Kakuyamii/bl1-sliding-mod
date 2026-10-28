
import unrealsdk
from .ground_view import vec
from .legs_pose import matrix,apply

def world_joints(joints,scale,rotation,translation,pawn):
    component=matrix(rotation);actor=matrix((0,float(pawn.Rotation.Yaw),0))
    origin=(float(pawn.Location.X),float(pawn.Location.Y),float(pawn.Location.Z))
    result=[]
    for joint in joints:
        local=apply(component,tuple(joint[i]*scale[i] for i in range(3)))
        offset=apply(actor,tuple(local[i]+translation[i] for i in range(3)))
        result.append(tuple(origin[i]+offset[i] for i in range(3)))
    return result

def clear_legs(pawn,bridge,joints):


    for a,b in ((0,1),(1,2),(3,4),(4,5),(2,6),(5,7)):
        actor,point,normal,info=bridge.trace(pawn,HitLocation=vec(),HitNormal=vec(),
            TraceStart=vec(*joints[a]),TraceEnd=vec(*joints[b]),bTraceActors=True,
            Extent=vec(10,10,10),HitInfo=unrealsdk.make_struct('Engine.Actor:TraceHitInfo'),ExtraTraceFlags=1)
        if actor is not None or info.HitComponent is not None:return False
    return True


def floor_lift(pawn,bridge,joints):

    samples=list(joints)
    samples.extend(tuple((joints[a][i]+joints[b][i])*.5 for i in range(3)) for a,b in ((0,1),(1,2),(3,4),(4,5)))
    lift=0.0
    for x,y,z in samples:
        actor,point,normal,info=bridge.trace(pawn,HitLocation=vec(),HitNormal=vec(),
            TraceStart=vec(x,y,z+64),TraceEnd=vec(x,y,z-96),bTraceActors=True,
            Extent=vec(8,8,0),HitInfo=unrealsdk.make_struct('Engine.Actor:TraceHitInfo'),ExtraTraceFlags=1)
        if actor is None and info.HitComponent is None:continue
        if normal.Z<.35:return None
        lift=max(lift,float(point.Z)+18-z)


    return lift if lift<=48 else None
