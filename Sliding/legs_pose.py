
import math


def matrix(rotation):
    p,y,r=(v*math.pi/32768 for v in rotation)
    sp,cp,sy,cy,sr,cr=math.sin(p),math.cos(p),math.sin(y),math.cos(y),math.sin(r),math.cos(r)
    return ((cp*cy,sr*sp*cy-cr*sy,-cr*sp*cy-sr*sy),
            (cp*sy,sr*sp*sy+cr*cy,-cr*sp*sy+sr*cy),
            (sp,-sr*cp,cr*cp))


def multiply(a,b):
    return tuple(tuple(sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def apply(m,v):
    return tuple(sum(m[i][j]*v[j] for j in range(3)) for i in range(3))


def reclined_rotation(view_yaw, pawn_yaw, source_rotation):

    m=multiply(matrix((0,view_yaw-pawn_yaw,0)),
               multiply(matrix((72*32768/180,0,0)),matrix(source_rotation)))
    result=(math.atan2(m[2][0],math.hypot(m[0][0],m[1][0])),
            math.atan2(m[1][0],m[0][0]),math.atan2(-m[2][1],m[2][2]))
    return tuple(round(v*32768/math.pi) for v in result)


def anchored_translation(target_local, feet_local, rotation, scale):
    transformed=[apply(matrix(rotation),tuple(f[i]*scale[i] for i in range(3))) for f in feet_local]
    anchor=(sum(f[0] for f in transformed)/len(transformed),
            sum(f[1] for f in transformed)/len(transformed),min(f[2] for f in transformed))
    return tuple(target_local[i]-anchor[i] for i in range(3))
