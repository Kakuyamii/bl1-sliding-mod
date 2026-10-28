def sync_materials(source, target):
    for index in range(max(len(source.Materials),len(target.Materials))):
        material=source.GetMaterial(index)
        if target.GetMaterial(index)!=material:
            target.SetMaterial(index,material)
