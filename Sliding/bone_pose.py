
import math
from .legs_pose import matrix,apply,reclined_rotation

def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def add(a,b):return tuple(x+y for x,y in zip(a,b))
def unit(v):
    length=math.sqrt(sum(x*x for x in v))
    if length<1e-6:raise RuntimeError('Degenerate leg bone')
    return tuple(x/length for x in v)
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def align(a,b):
    a,b=unit(a),unit(b);v=cross(a,b);c=max(-1,min(1,sum(x*y for x,y in zip(a,b))))
    if c<-.9999:
        axis=unit(cross(a,(1,0,0) if abs(a[0])<.9 else (0,1,0)))
        return tuple(tuple(2*axis[i]*axis[j]-(i==j) for j in range(3)) for i in range(3))
    def rotate(x):return add(add(x,cross(v,x)),tuple(t/(1+c) for t in cross(v,cross(v,x))))
    columns=[rotate(tuple(float(i==j) for i in range(3))) for j in range(3)]
    return tuple(tuple(columns[j][i] for j in range(3)) for i in range(3))

def pose_matrices(names,parents,bases,source_rotation,character_mesh=""):
    from .character_profiles import for_mesh
    from .authored_pose import retarget
    return retarget(names,parents,bases,for_mesh(character_mesh))

def apply_pose(mesh,names,parents,source_rotation):
    fields=('XPlane','YPlane','ZPlane','WPlane')
    original=[tuple(tuple(float(getattr(getattr(m,f),k)) for k in ('X','Y','Z')) for f in fields) for m in mesh.SpaceBases]
    posed,chains=pose_matrices(names,parents,original,source_rotation,mesh.SkeletalMesh)


    mesh.bPauseAnims=True
    mesh.bNoSkeletonUpdate=True
    for i,(before,after) in enumerate(zip(original,posed)):
        if before==after:continue
        entry=mesh.SpaceBases[i]
        for field,values in zip(fields,after):
            plane=getattr(entry,field)
            for key,value in zip(('X','Y','Z'),values):setattr(plane,key,value)
        mesh.SpaceBases[i]=entry
    joints=[posed[index][3] for chain in chains for index in chain]
    for side in ('l','r'):
        toes=[i for i,name in enumerate(names) if '_'+side+'_' in name.lower() and name.lower().endswith('_toe0')]
        if len(toes)!=1:raise RuntimeError('Unsupported toe chain: '+side)
        joints.append(posed[toes[0]][3])
    persist_local_pose(mesh,names,parents,original,posed)
    return joints,chains


def local_quaternion(basis,parent):


    axes=[unit(axis) for axis in basis[:3]]
    parent_axes=[unit(axis) for axis in parent[:3]]
    rows=tuple(tuple(sum(axes[j][k]*parent_axes[i][k] for k in range(3)) for j in range(3)) for i in range(3))
    trace=sum(rows[i][i] for i in range(3))
    if trace>0:
        s=math.sqrt(trace+1)*2
        q=((rows[2][1]-rows[1][2])/s,(rows[0][2]-rows[2][0])/s,(rows[1][0]-rows[0][1])/s,s/4)
    else:
        i=max(range(3),key=lambda j:rows[j][j]);j=(i+1)%3;k=(i+2)%3
        s=math.sqrt(max(0,1+rows[i][i]-rows[j][j]-rows[k][k]))*2
        q=[0.0]*4;q[i]=s/4;q[j]=(rows[j][i]+rows[i][j])/s;q[k]=(rows[k][i]+rows[i][k])/s;q[3]=(rows[k][j]-rows[j][k])/s
    return tuple(q)


def persist_local_pose(mesh,names,parents,original,posed):
    index={n:i for i,n in enumerate(names)}
    for i,(before,after) in enumerate(zip(original,posed)):
        if before==after:continue
        parent_index=index.get(parents.get(names[i]))
        if parent_index is None:raise RuntimeError('Posed bone has no known parent')
        parent=posed[parent_index]
        q=local_quaternion(after,parent)
        atom=mesh.LocalAtoms[i]
        for key,value in zip(('X','Y','Z','W'),q):setattr(atom.Rotation,key,value)
        mesh.LocalAtoms[i]=atom
