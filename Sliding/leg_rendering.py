
FRAMING=(180.0,-150.0,-30.0,-30.0)

def configure(mesh,log):



    mesh.SetIgnoreOwnerHidden(True)
    mesh.SetOwnerNoSee(False)
    mesh.SetOnlyOwnerSee(True)
    applied=[]


    for name,value in (('bComponentUseFixedSkelBounds',True),('ForcedLodModel',1)):
        try:
            getattr(mesh,name)
            setattr(mesh,name,value)
            applied.append((name,value))
        except Exception as error:
            log('legs optional render setting skipped: '+name+': '+type(error).__name__)
            continue
    log('legs renderer: ignore owner hidden; owner-only; overrides='+repr(applied))
    snapshot={}
    for name in ('bHidden','bOwnerNoSee','bOnlyOwnerSee','bIgnoreOwnerHidden','Bounds','ForcedLodModel','PredictedLODLevel','Scale','Scale3D'):
        try:snapshot[name]=str(getattr(mesh,name))
        except Exception:pass
    log('legs render state: '+repr(snapshot))


def absolute_transform(mesh):



    mesh.AbsoluteTranslation=True
    mesh.AbsoluteRotation=True
    mesh.AbsoluteScale=True
