
import math

def rotate(v,axis,angle):
    length=math.sqrt(sum(x*x for x in axis))
    if length<1e-8:return v
    x,y,z=(q/length for q in axis);c=math.cos(angle);s=math.sin(angle);dot=x*v[0]+y*v[1]+z*v[2]
    cross=(y*v[2]-z*v[1],z*v[0]-x*v[2],x*v[1]-y*v[0])
    return tuple(v[i]*c+cross[i]*s+(x,y,z)[i]*dot*(1-c) for i in range(3))

def animate(saved,chains,toes,phase,turn,strength):
    result={i:saved[i] for chain,toe in zip(chains,toes) for i in (*chain,toe)}
    for side,(chain,toe) in enumerate(zip(chains,toes)):
        phase_offset=side*1.7
        for joint,followers,amplitude in ((chain[0],(*chain,toe),.45),(chain[1],(*chain[1:],toe),.30)):
            base=result[joint];pivot=base[3][:3];axis=base[1][:3]
            angle=math.radians((math.sin(phase*(6.2+side*.5)+phase_offset)*amplitude*strength)+turn*(.15 if side==0 else -.12))
            for i in followers:
                old=result[i];axes=[rotate(row[:3],axis,angle)+(row[3],) for row in old[:3]]
                delta=rotate(tuple(old[3][k]-pivot[k] for k in range(3)),axis,angle)
                result[i]=tuple(axes)+(tuple(pivot[k]+delta[k] for k in range(3))+(old[3][3],),)
    return result
