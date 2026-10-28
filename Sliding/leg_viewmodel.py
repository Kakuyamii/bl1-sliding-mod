pass
import math
from .legs_pose import matrix,multiply,apply
from .authored_profile import PROFILE

def pitch_degrees(rotation):
    return ((float(rotation.Pitch)+32768)%65536-32768)*180/32768

def allowed_view(rotation):
    return math.isfinite(float(rotation.Pitch)) and pitch_degrees(rotation)<75.0

def look_reveal(rotation):

    t=max(0.0,min(1.0,(pitch_degrees(rotation)-55.0)/20.0))
    return 1.0-t*t*(3.0-2.0*t)

def as_rotator(m):
    return tuple(round(v*32768/math.pi) for v in
        (math.atan2(m[2][0],math.hypot(m[0][0],m[1][0])),math.atan2(m[1][0],m[0][0]),math.atan2(-m[2][1],m[2][2])))

def placement(controller,aspect,source_rotation,feet,joints,scale,ground_anchor=None,reveal=1.0,floor_offset=0.0,zoom=100.0,xyz=(0,0,0),motion=(0,0,0)):
    if not allowed_view(controller.CalcViewRotation):return None
    view=controller.CalcViewRotation
    camera=matrix(tuple(float(getattr(view,k)) for k in ('Pitch','Yaw','Roll')))


    authored=PROFILE['presentation']
    scales=tuple(math.sqrt(sum(authored[i][j]**2 for i in range(3))) for j in range(3))
    orientation=tuple(tuple(authored[i][j]/scales[j] for j in range(3)) for i in range(3))
    local=multiply(matrix((0,0,motion[2]*32768/180)),orientation)
    factor=max(.25,min(3.0,zoom/100.0))
    draw_scale=tuple(v*factor for v in scales)
    fov=PROFILE['fov']
    visible=max(0,min(1,reveal))*look_reveal(view)
    offset=(authored[0][3]+xyz[0],
            authored[1][3]+xyz[1]+motion[0],
            authored[2][3]+xyz[2]+motion[1]+max(-4,min(6,floor_offset))-(1-visible)*100)
    world_offset=apply(camera,offset)
    origin=controller.CalcViewLocation
    translation=tuple(float(getattr(origin,k))+world_offset[i] for i,k in enumerate(('X','Y','Z')))
    return as_rotator(multiply(camera,local)),translation,draw_scale,fov


def reveal_amount(age,speed,stop_speed):
    def smooth(x):
        x=max(0.0,min(1.0,x))
        return x*x*(3-2*x)
    return min(smooth(age/.20),smooth((speed-stop_speed)/180.0))
