
import math
from .authored_profile import PROFILE

IDENTITY=tuple(tuple(float(i==j) for j in range(4)) for i in range(4))
def mul(a,b):
    return tuple(tuple(sum(a[i][k]*b[k][j] for k in range(4)) for j in range(4)) for i in range(4))
def inverse(m):
    rows=[list(m[i])+list(IDENTITY[i]) for i in range(4)]
    for col in range(4):
        pivot=max(range(col,4),key=lambda i:abs(rows[i][col]))
        if abs(rows[pivot][col])<1e-10:raise ValueError('Singular bone transform')
        rows[col],rows[pivot]=rows[pivot],rows[col]
        divisor=rows[col][col];rows[col]=[v/divisor for v in rows[col]]
        for i in range(4):
            if i!=col:
                factor=rows[i][col];rows[i]=[v-factor*w for v,w in zip(rows[i],rows[col])]
    return tuple(tuple(row[4:]) for row in rows)
def from_basis(b):
    return tuple(tuple(b[j][i] if j<3 else b[3][i] for j in range(4)) for i in range(3))+((0.,0.,0.,1.),)
def to_basis(m):
    return tuple(tuple(m[i][j] for i in range(3)) for j in range(4))

def retarget(names,parents,bases,profile=None):
    profile=PROFILE if profile is None else profile
    index={n:i for i,n in enumerate(names)}
    source=[from_basis(b) for b in bases];result=list(source)
    for i,n in enumerate(names):
        entry=profile['bones'].get(n)
        if entry is None:continue
        parent=index[parents[n]]
        local=mul(inverse(source[parent]),source[i])
        delta=[list(row) for row in entry['delta']]


        ratio=math.sqrt(sum(local[j][3]**2 for j in range(3)))/entry['length']
        for j in range(3):delta[j][3]*=ratio
        result[i]=mul(result[parent],mul(local,delta))
    chains=[]
    for side in ('L','R'):
        chains.append([index['Bip01_'+side+'_'+part] for part in ('Thigh','Calf','Foot')])
    return [to_basis(m) if names[i] in profile['bones'] else bases[i] for i,m in enumerate(result)],chains
