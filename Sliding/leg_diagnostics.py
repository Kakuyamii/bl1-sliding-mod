pass
import math

def report(mesh,source,indices,names,log,stage):
    def snapshot(obj):
        out={}
        for key in ('AbsoluteTranslation','AbsoluteRotation','AbsoluteScale','Class','SkeletalMesh','HiddenGame','HiddenEditor','bOwnerNoSee','bOnlyOwnerSee','bIgnoreOwnerHidden','Bounds','LastRenderTime','ForcedLodModel','PredictedLODLevel','bForceRefPose','bForceCPUSkinning','bPauseAnims','bNoSkeletonUpdate','DepthPriorityGroup','Translation','Rotation','Scale','Scale3D'):
            try:out[key]=str(getattr(obj,key))
            except Exception:continue
        try:out['Materials']=[str(m) for m in obj.Materials]
        except Exception:pass
        try:out['effective materials']=[str(obj.GetMaterial(i)) for i in range(3)]
        except Exception:pass
        return out
    log('legs runtime '+stage+' copy: '+repr(snapshot(mesh)))
    log('legs runtime '+stage+' source: '+repr(snapshot(source)))
    result=[]
    for i in indices:
        try:
            entry=mesh.SpaceBases[i]
            scales=[math.sqrt(sum(float(getattr(getattr(entry,axis),k))**2 for k in ('X','Y','Z'))) for axis in ('XPlane','YPlane','ZPlane')]
            result.append((names[i],scales,float(mesh.LocalAtoms[i].Scale),int(mesh.BoneVisibility[i])))
        except Exception as error:result.append((names[i],type(error).__name__))
    log('legs runtime '+stage+' bone scales/visibility: '+repr(result))
