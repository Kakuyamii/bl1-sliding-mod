

def mask_body(mesh,names,chains):
    keep={i for i,name in enumerate(names) if
          any(name=='Bip01_'+side+'_'+part for side in ('L','R')
              for part in ('Thigh','Calf','Foot','Toe0'))}
    if len(keep)!=8:raise RuntimeError('Expected eight posed leg bones')
    thighs=[chain[0] for chain in chains]
    anchor=tuple(sum(float(getattr(mesh.SpaceBases[i].WPlane,k)) for i in thighs)/len(thighs)
                 for k in ('X','Y','Z'))
    masked=[]
    for i in range(len(names)):
        if i in keep:continue
        entry=mesh.SpaceBases[i]
        for field in ('XPlane','YPlane','ZPlane'):
            plane=getattr(entry,field)
            for k in ('X','Y','Z','W'):setattr(plane,k,0.0)
        for k,value in zip(('X','Y','Z','W'),anchor+(1.0,)):setattr(entry.WPlane,k,value)
        mesh.SpaceBases[i]=entry
        masked.append(i)
    return masked
