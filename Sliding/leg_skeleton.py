

def lower_body_selection(names, parents):
    index={name:i for i,name in enumerate(names)}
    def lineage(name):
        seen=set()
        while name in index and name not in seen:
            seen.add(name)
            name=parents.get(name)
        return seen
    ancestry={name:lineage(name) for name in names}
    feet=[name for name in names if 'foot' in name.lower()
          and not any(word in name.lower() for word in ('ik','socket','attach','effect','footstep'))]
    if len(feet)<2:
        raise RuntimeError('Cannot identify two foot bones')
    protected=set().union(*(ancestry[name] for name in feet))


    roots={name for name in names if name not in protected and
           any(word in name.lower() for word in ('spine','chest','neck','head','clav','shoulder','arm','hand'))}
    hidden=[i for i,name in enumerate(names) if ancestry[name]&roots]
    if not hidden:
        raise RuntimeError('No upper-body branch independent of legs')
    return feet,hidden
