
import math
import unrealsdk
from unrealsdk.unreal import WeakPointer
from .trace_bridge import TraceBridge
from .ground_view import ground_target

ASSETS = {
    'dirt': 'fx_bullet_impacts.Particles.part_Impact_Dirt_Large_Dup',
    'rock': 'fx_bullet_impacts.Particles.part_Impact_Dirt_Large_Dup',
    'metal': 'fx_bullet_impacts.Particles.part_Impact_Metal_Large_Dup',
    'water': 'fx_environment_water.Particles.part_water_step_splash',
}


def surface_kind(name):
    name = name.lower()
    if 'water' in name:
        return 'water'
    if 'wood' in name:
        return 'wood'
    if 'metal' in name:
        return 'metal'
    if any(word in name for word in ('rock', 'stone', 'concrete', 'gravel')):
        return 'rock'
    if any(word in name for word in ('dirt', 'sand', 'grass', 'plantlife')):
        return 'dirt'
    return None


def vec(x=0.0, y=0.0, z=0.0):
    return unrealsdk.make_struct('Vector', X=x, Y=y, Z=z)


def normal_rotation(normal):
    return unrealsdk.make_struct('Rotator',
        Pitch=int(math.atan2(normal.Z, math.hypot(normal.X, normal.Y))*32768/math.pi),
        Yaw=int(math.atan2(normal.Y, normal.X)*32768/math.pi), Roll=0)


def finite_template(template):

    found = False
    for emitter in template.Emitters:
        if emitter is None:
            continue
        for lod in emitter.LODLevels:
            if lod is None:
                continue
            required = lod.RequiredModule
            if required is None or int(required.EmitterLoops) <= 0:
                return False
            found = True
    return found


class SlideParticles:
    def __init__(self, log):
        self.log = log
        self.reset()

    def reset(self):
        self.surface = None
        self.next_emit = 0.0
        self.last_position = None
        self.failed = False
        self.emit_failed = False
        self.status = 'ready'
        self.last_notice = None
        self.trace_detail = 'not traced'
        self.trace_reports = 0
        self.trace_bridge = None
        self.aspect = 16/9
        self.templates = {}
        self.emit_side = -1

    def stop(self):
        self.surface = None
        self.next_emit = 0.0
        self.last_position = None
        if not self.failed:
            self.status = 'idle'

    def notice(self, text):
        self.status = text
        if text != self.last_notice:
            self.log(text)
            self.last_notice = text

    def tick(self, pawn, sliding, now, density=100.0, scale=0.3, paused=False, controller=None, emit_enabled=True):
        if not sliding or paused:
            self.stop()
            return
        if self.failed or now < self.next_emit:
            return

        density = max(25.0, min(200.0, density))/100.0
        self.next_emit = now + 0.09/density
        try:
            if int(pawn.Physics) != 1:
                self.stop()
                return
            self.surface = None
            if self.trace_bridge is None:
                self.trace_bridge = TraceBridge(self.log)
            self.surface = None
            location = pawn.Location
            current = (float(location.X), float(location.Y), float(location.Z))
            if self.last_position is not None:
                dx, dy = current[0]-self.last_position[0], current[1]-self.last_position[1]
                if math.hypot(dx, dy) < 45.0/density:
                    return
            height = float(pawn.CylinderComponent.CollisionHeight)
            radius = float(pawn.CylinderComponent.CollisionRadius)


            start = vec(*current)
            foot_z = current[2] - height
            attempts = []
            contact = None
            attempts_to_try = [
                ('pawn point', pawn, 28.0, vec(), 0),


                ('pawn complex', pawn, 64.0, vec(), 1),
            ]
            if controller is not None:
                attempts_to_try.append(('controller complex', controller, 64.0, vec(), 1))
            attempts_to_try.append(('pawn sweep complex', pawn, 64.0,
                                   vec(min(8.0, radius*0.5), min(8.0, radius*0.5), 2.0), 1))
            for label, source, reach, extent, flags in attempts_to_try:
                end = vec(current[0], current[1], foot_z-reach)
                result = self.trace_bridge.trace(source, HitLocation=vec(), HitNormal=vec(), TraceEnd=end,
                                    TraceStart=start, bTraceActors=True, Extent=extent,
                                    HitInfo=unrealsdk.make_struct('Engine.Actor:TraceHitInfo'),
                                    ExtraTraceFlags=flags)
                if not isinstance(result, tuple) or len(result) != 4:
                    raise RuntimeError('Unexpected Actor.Trace result: ' + repr(result))
                actor, point, normal, info = result
                gap = float(point.Z)-foot_z
                normal_size = math.sqrt(normal.X**2 + normal.Y**2 + normal.Z**2)
                component = getattr(info, 'HitComponent', None)
                geometry = actor is not None or component is not None
                reason = ('no hit object/component' if not geometry else
                          'invalid hit normal' if not 0.5 <= normal_size <= 1.5 or normal.Z < 0.2 else
                          'hit outside contact range' if abs(gap) > 48.0 else 'contact')
                attempts.append(f'{label}: {reason}; flags={flags}; endZ={end.Z:.2f}; actor={actor}; component={component}; '
                                f'hit=({point.X:.2f},{point.Y:.2f},{point.Z:.2f}); '
                                f'normal=({normal.X:.3f},{normal.Y:.3f},{normal.Z:.3f}); gap={gap:.2f}')
                if reason == 'contact':
                    contact = actor, point, normal, info
                    break
            self.trace_detail = (f'center={current}; cylinder height={height:.2f} radius={radius:.2f}; '
                                 f'base={getattr(pawn, "Base", None)}; '
                                 f'cylinder translation={getattr(pawn.CylinderComponent, "Translation", None)}; '
                                 + ' | '.join(attempts))
            if self.trace_reports < 3:
                self.log('trace: ' + self.trace_detail)
                self.trace_reports += 1
            if contact is None:
                self.notice('floor trace rejected (see trace details in dump)')
                return
            actor, point, normal, info = contact
            material = getattr(info, 'PhysMaterial', None)
            if material is None:
                render_material = getattr(info, 'Material', None)
                if render_material is not None:
                    material = render_material.GetPhysicalMaterial()
            if material is None:
                component = getattr(info, 'HitComponent', None)
                if component is not None:
                    material = component.GetPhysicalMaterial(bSearchArrays=True)
            kind = None
            checked = set()
            while material is not None and str(material) not in checked:
                checked.add(str(material))
                kind = surface_kind(str(material))
                if kind is not None:
                    break
                material = material.Parent
            if kind is None:
                self.notice('unmapped terrain: ' + ', '.join(sorted(checked)))
                return
            self.surface = kind
            if not emit_enabled or self.emit_failed:
                self.notice('surface: ' + kind)
                return
            if kind not in ASSETS:
                self.notice('no particle asset: ' + kind)
                return
            ref = self.templates.get(kind)
            template = ref() if ref is not None else None
            if template is None:
                template = unrealsdk.find_object('ParticleSystem',ASSETS[kind])
                if not finite_template(template):
                    self.notice('skipped looping particle: ' + kind)
                    return
                self.templates[kind] = WeakPointer(template)
            pool = pawn.WorldInfo.MyEmitterPool
            if pool is None:
                return
            emitted = 0
            self.emit_side *= -1
            for x in (.22*self.emit_side,):
                hit = ground_target(pawn,controller,self.trace_bridge,self.aspect,x,.68)
                if hit is None:
                    continue
                position,up = hit
                component = pool.SpawnEmitter(EmitterTemplate=template,
                    SpawnLocation=vec(position.X+up.X*2,position.Y+up.Y*2,position.Z+up.Z*2),
                    SpawnRotation=normal_rotation(up),AttachToActor=None)
                if component is not None:

                    component.SetScale(.30*scale*(.55 if kind == 'rock' else 1))
                    emitted += 1
            self.notice(('3D low-view ' + kind) if emitted else 'no low-view ground contact')
        except Exception as error:
            if self.surface is None:
                self.failed = True
            else:
                self.emit_failed = True
            self.notice(f'disabled: {type(error).__name__}: {error}')
