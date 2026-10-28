
import hashlib
from importlib import resources
from pathlib import Path
import os
import tempfile
import unrealsdk
from mods_base import SETTINGS_DIR
from .brick_mesh_manifest import MANIFEST

_failed=False

def is_brick(asset):
    parts=str(asset).lower().replace("'",'').split('.')
    return any(part in ('char_brick','skeletalmeshchar_brick') for part in parts)

def asset_path():


    return Path(SETTINGS_DIR).parent/'Sliding_assets'/(MANIFEST['package']+'.upk')

def ensure_asset():
    path=asset_path()
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==MANIFEST['sha256']:
        return path
    payload=resources.files(__package__).joinpath('assets',path.name).read_bytes()
    if len(payload)!=MANIFEST['bytes'] or hashlib.sha256(payload).hexdigest()!=MANIFEST['sha256']:
        raise RuntimeError('Bundled Brick slide mesh failed integrity check')
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix=path.stem+'.',suffix='.tmp',delete=False) as stream:
            temp=Path(stream.name);stream.write(payload)
        os.replace(temp,path)
    finally:
        if temp is not None and temp.exists():temp.unlink()
    return path

def resolve_slide_mesh(source,log):
    global _failed
    if not is_brick(source) or _failed:return source
    try:

        try:asset=unrealsdk.find_object('SkeletalMesh',MANIFEST['object'])
        except ValueError:asset=None
        if asset is None:
            path=ensure_asset()
            unrealsdk.load_package(str(path))
            asset=unrealsdk.find_object('SkeletalMesh',MANIFEST['object'])
        if asset is None or MANIFEST['package'].lower() not in str(asset).lower():
            raise RuntimeError('Private Brick mesh did not resolve under its own package')
        log('legs: private Brick slide mesh loaded; 205 deleted triangles suppressed')
        return asset
    except Exception as error:
        _failed=True
        log('legs: private Brick slide mesh unavailable; using stock mesh until restart: '+str(error))
        return source
