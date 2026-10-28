pass
TUNING={'lilith':(95,37,18,-5),'brick':(98,22,16,-4)}
def character_tuning(mesh_name,base):
    parts=str(mesh_name).lower().replace("'",'').split('.')
    for name,(zoom,x,y,z) in TUNING.items():
        if any(p in ('char_'+name,'skeletalmeshchar_'+name) for p in parts):
            return (base[0]*zoom/100.0,base[1]+x,base[2]+y,base[3]+z)
    return base
