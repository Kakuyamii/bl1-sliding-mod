import math


def jump_retention(age):
    if age <= .12:
        return 0.0
    if age < .38:
        x=(age-.12)/.26
        return x*x*(3-2*x)
    if age <= .68:
        return 1.0
    return max(.55,1-(age-.68)*1.5)


def tuned_slope(projected):

    return max(0.0,projected)*12.0


def sway(age,speed):
    strength=min(1.25,max(.4,speed/1350))
    return (math.sin(age*9)*180*strength,math.sin(age*6.5)*.65*strength)


def downhill_support(projected, age, drag):

    if projected <= 0:return 0.0
    power=max(0.0,projected)*8.0
    sustained=min(power,drag*.80)*max(0.0,1.0-age/6.0)
    initial=min(power,drag+240.0)
    return sustained+(initial-sustained)*math.exp(-max(0.0,age)/.45)


def steer_slide(direction, initial, camera_yaw, dt):

    wrap=lambda a:(a+math.pi)%(2*math.pi)-math.pi
    current=math.atan2(direction[1],direction[0]);start=math.atan2(initial[1],initial[0])
    target=camera_yaw*math.pi/32768
    target=start+max(-math.radians(12),min(math.radians(12),wrap(target-start)))
    error=wrap(target-current)
    step=max(-math.radians(5)*dt,min(math.radians(5)*dt,error*(1-math.exp(-.5*dt))))
    return math.cos(current+step),math.sin(current+step)
