
def air_speed(horizontal,vertical,entry,dt):
    horizontal=max(0.0,horizontal);dt=max(0.0,min(.1,dt))
    if vertical>=-25:return max(0.0,horizontal-45*dt)

    assist=min(30.0,max(0.0,-vertical)*.025)
    return min(horizontal+assist*dt,max(horizontal,entry+60.0))
