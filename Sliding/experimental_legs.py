
from .leg_only import mask_body
from .brick_slide_mesh import resolve_slide_mesh
import unrealsdk
from unrealsdk.unreal import WeakPointer
import time
import math
from types import SimpleNamespace
from .ground_view import ground_target,local_offset,vec
from .legs_pose import reclined_rotation,anchored_translation
from .leg_skeleton import lower_body_selection
from .bone_pose import apply_pose
from .leg_viewmodel import placement,allowed_view
from .leg_motion import LegMotion
from .leg_materials import sync_materials
from .leg_bone_sway import animate
from .leg_surface import surface_offset
from .slide_actions import scoped_aim
from .leg_rendering import FRAMING,configure,absolute_transform
from .leg_diagnostics import report
from .leg_clearance import world_joints,clear_legs,floor_lift


class Legs:

    @property
    def mesh(self):
        ref=getattr(self,'_mesh_ref',None)
        return ref() if ref is not None else None

    @mesh.setter
    def mesh(self,value):
        self._mesh_ref=WeakPointer(value) if value is not None else None

    @property
    def pawn(self):
        ref=getattr(self,'_pawn_ref',None)
        return ref() if ref is not None else None

    @pawn.setter
    def pawn(self,value):
        self._pawn_ref=WeakPointer(value) if value is not None else None

    def matches_owner(self,current):
        owner=self.pawn
        return current is not None and owner is not None and owner==current and self.mesh is not None

    def discard_if_changed(self,current):
        if self._pawn_ref is not None and not self.matches_owner(current):

            self.stop(detach=False)
            self.failed=False
            self.log('legs: discarded previous character/world references')
            return True
        return False

    def __init__(self, log):
        self.log=log
        self.mesh=None
        self.pawn=None
        self.failed=False
        self.ready=False
        self.wait_started=0.0
        self.spine=None
        self.next_update=0.0
        self.visible=False
        self.presentation_floor=0.0
        self.motion=LegMotion()
        self.motion_time=None
        self.next_material_sync=0.0
        self.applied_fov=None
        self.applied_rotation=self.applied_translation=None
        self.debug_transform=FRAMING
        self.motion_speed=1.0
        self.floor_offset=0.0
        self.reveal=1.0
        self.pose_repairs=0
        self.view_contact=None
        self.status='not initialized'

    def stop(self,detach=True):
        mesh,owner=self.mesh,self.pawn
        if detach and mesh is not None and owner is not None:
            try:
                owner.DetachComponent(mesh)
            except Exception as e:
                self.log('legs detach: '+str(e))
        self.view_contact=None
        self.draw_scale=None
        self.mesh=self.pawn=None
        self.ready=False
        self.visible=False
        self.next_update=0.0
        self.floor_offset=self.presentation_floor=0.0
        self.motion=LegMotion()
        self.motion_time=None
        self.next_material_sync=0.0
        self.applied_fov=None
        self.applied_rotation=self.applied_translation=None
        self.pose_repairs=0
        self.floor_warned=False

    def set_visible(self, visible):
        mesh=self.mesh
        if mesh is not None and visible != self.visible:
            mesh.SetHidden(not visible)
            self.visible=visible
            self.log(f'legs visibility: {visible}; {self.status}')

    def update(self,pawn,active,controller=None,bridge=None,aspect=16/9,reveal=1.0):
        self.discard_if_changed(pawn)
        self.reveal=reveal
        if not active:
            self.motion=LegMotion()
            self.motion_time=None
            self.status='inactive'
            self.set_visible(False)
            return
        if self.failed:
            return
        if self.pawn == pawn and self.mesh is not None:
            now=time.perf_counter()
            if now < self.next_update:
                if self.ready:self.draw(controller,aspect)
                return
            self.next_update=now+.05
            if not self.ready:
                self.finish_setup()
            if self.ready:
                self.place(controller,bridge,aspect)
            return
        self.stop()
        try:
            source=pawn.Mesh
            self.log('legs: initializing current character '+str(source.SkeletalMesh))
            names=[str(source.GetBoneName(i)) for i in range(len(source.LocalAtoms))]
            parents={name:str(source.GetParentBone(name)) for name in names}
            self.log('legs skeleton: '+repr(list(enumerate((name,parents[name]) for name in names))))
            self.feet,self.hidden_bones=lower_body_selection(names,parents)
            self.bone_names,self.parents=names,parents
            self.log('legs selection: feet='+repr(self.feet)+'; hidden='+repr([names[i] for i in self.hidden_bones]))
            mesh=unrealsdk.construct_object(cls='GearboxSkeletalMeshComponent',outer=pawn)
            self.mesh,self.pawn=mesh,pawn
            mesh.SetSkeletalMesh(resolve_slide_mesh(source.SkeletalMesh,self.log))
            self.turn_sway = "char_mordecai" in str(source.SkeletalMesh).lower()
            self.sync_phase_materials = "char_lilith" in str(source.SkeletalMesh).lower()
            for i,material in enumerate(source.Materials):
                if material is not None:
                    mesh.SetMaterial(i,material)
            mesh.SetHidden(True)
            mesh.bUpdateSkelWhenNotRendered=True
            mesh.bOwnerNoSee=False
            mesh.bOnlyOwnerSee=True
            mesh.CastShadow=False
            mesh.CollideActors=False
            mesh.BlockActors=False
            mesh.SetDepthPriorityGroup(2)
            mesh.SetFOV(0.0)
            mesh.Translation=source.Translation
            mesh.Rotation=source.Rotation
            mesh.Scale=source.Scale
            mesh.Scale3D=source.Scale3D

            mesh.SetAnimTreeTemplate(source.AnimTreeTemplate)
            absolute_transform(mesh)
            configure(mesh,self.log)
            pawn.AttachComponent(mesh)
            self.spine=max(self.hidden_bones)
            self.required_pose_count=len(names)
            self.source_rotation=(int(source.Rotation.Pitch),int(source.Rotation.Yaw),int(source.Rotation.Roll))
            self.wait_started=time.perf_counter()
            self.log('experimental legs: attached hidden; waiting for pose initialization')
        except Exception as e:
            self.stop()
            self.failed=True
            self.status='setup failed: '+str(e)
            self.log('experimental legs unavailable: '+type(e).__name__+': '+str(e))

    def finish_setup(self):
        try:
            mesh=self.mesh
            counts=(len(mesh.LocalAtoms),len(mesh.BoneVisibility),len(mesh.SpaceBases))
            if min(counts) < self.required_pose_count:
                if time.perf_counter()-self.wait_started < .75:
                    return
                raise RuntimeError(f'Pose initialization timed out: LocalAtoms={counts[0]}, BoneVisibility={counts[1]}, SpaceBases={counts[2]}')


            for index in self.hidden_bones:
                if index >= min(counts):
                    raise RuntimeError('Upper-body index exceeds pose storage')
                mesh.HideBone(index,False)


            mesh.ForceSkelUpdate()
            self.pose_joints,self.pose_chains=apply_pose(mesh,self.bone_names,self.parents,self.source_rotation)
            local_feet=[mesh.GetBoneLocation(name,1) for name in self.feet]
            self.feet_local=[(float(v.X),float(v.Y),float(v.Z)) for v in local_feet]
            if not all(math.isfinite(v) for f in self.feet_local for v in f):
                raise RuntimeError('Invalid component-space foot coordinates')
            if len(self.feet_local)<2 or all(sum(v*v for v in f)<1 for f in self.feet_local):
                raise RuntimeError('Could not resolve two foot positions')
            self.body_mask_indices=mask_body(mesh,self.bone_names,self.pose_chains)
            self.pose_indices=list(range(len(self.bone_names)))
            self.sway_toes=[self.bone_names.index('Bip01_'+side+'_Toe0') for side in ('L','R')]
            self.last_animated={}
            self.next_bone_sway=0.0
            self.saved_bases=[tuple(tuple(float(getattr(getattr(entry,f),k)) for k in ('X','Y','Z','W')) for f in ('XPlane','YPlane','ZPlane','WPlane')) for entry in mesh.SpaceBases]
            self.pose_scale=tuple(float(getattr(mesh.Scale3D,k))*float(mesh.Scale) for k in ('X','Y','Z'))
            mesh.bPauseAnims=True
            mesh.SetHidden(True)
            self.ready=True
            self.diagnostic_samples=0
            self.diagnostic_due=time.perf_counter()+.25
            self.status='Blender pose ready'
            self.log('legs: authored Blender pose and framing; relative tuning='+repr(self.debug_transform))
            self.log('legs posed joints (component space): '+repr(self.pose_joints))
            self.log('experimental legs: frozen independent pose; feet='+repr(self.feet)+'; hidden bones='+str(len(self.hidden_bones))+'; component feet='+repr(self.feet_local))
        except Exception as e:
            self.stop()
            self.failed=True
            self.status='setup failed: '+str(e)
            self.log('experimental legs unavailable: '+type(e).__name__+': '+str(e))

    def place(self,controller,bridge,aspect):

        try:
            support=SimpleNamespace(CalcViewLocation=controller.CalcViewLocation,
                CalcViewRotation=SimpleNamespace(Pitch=0,Yaw=controller.CalcViewRotation.Yaw,Roll=0),
                FOVAngle=controller.FOVAngle)
            hit=ground_target(self.pawn,support,bridge,aspect,-.20,.56)
            if hit is not None:
                point,normal=hit
                rotation=reclined_rotation(float(controller.CalcViewRotation.Yaw),float(self.pawn.Rotation.Yaw),self.source_rotation)
                origin=self.pawn.Location
                target=local_offset((point.X-origin.X,point.Y-origin.Y,point.Z+14-origin.Z),float(self.pawn.Rotation.Yaw))
                translation=anchored_translation(target,self.feet_local,rotation,self.pose_scale)
                joints=world_joints(self.pose_joints,self.pose_scale,rotation,translation,self.pawn)
                lift=floor_lift(self.pawn,bridge,joints)
                desired=surface_offset((normal.X,normal.Y,normal.Z),float(controller.CalcViewRotation.Yaw),0. if lift is None else lift)
                self.floor_offset += (desired-self.floor_offset)*.35
                self.view_contact=(float(point.X),float(point.Y),float(point.Z))
                self.status=f'foreground legs; correction {self.floor_offset:.1f}; repairs {self.pose_repairs}'
            else:
                self.status=f'foreground legs; retained correction {self.floor_offset:.1f}'
        except Exception as error:

            self.status='foreground legs; floor query unavailable'
            if not getattr(self,'floor_warned',False):
                self.log('legs floor correction unavailable: '+str(error))
                self.floor_warned=True
        self.draw(controller,aspect)

    def draw(self,controller,aspect):


        current=controller.Pawn if controller is not None else None
        self.discard_if_changed(current)
        if not self.matches_owner(current) or not self.ready:
            return
        try:
            if self.reveal<=.01 or controller is None or scoped_aim(controller,current) or not allowed_view(getattr(controller,"Rotation",controller.CalcViewRotation)):
                if controller is not None and not allowed_view(getattr(controller,"Rotation",controller.CalcViewRotation)):
                    self.status='hidden: view angle'
                self.set_visible(False)
                return
            mesh=self.mesh
            if len(mesh.SpaceBases)<self.required_pose_count or len(mesh.LocalAtoms)<self.required_pose_count:
                self.status='pose storage changed; rebuilding'
                self.stop()
                return


            changed=False
            for index in (self.pose_chains[0][2],self.pose_chains[1][2],self.body_mask_indices[0]):
                actual=mesh.SpaceBases[index]
                expected=self.last_animated.get(index,self.saved_bases[index])
                for field,values in zip(('XPlane','YPlane','ZPlane','WPlane'),expected):
                    plane=getattr(actual,field)
                    if any(abs(float(getattr(plane,k))-values[i])>.001 for i,k in enumerate(('X','Y','Z'))):
                        changed=True
                        break
            if changed:
                for index in self.pose_indices:
                    values=self.saved_bases[index]
                    entry=mesh.SpaceBases[index]
                    for field,plane_values in zip(('XPlane','YPlane','ZPlane','WPlane'),values):
                        plane=getattr(entry,field)
                        for key,value in zip(('X','Y','Z','W'),plane_values):setattr(plane,key,value)
                    mesh.SpaceBases[index]=entry
                self.last_animated={}
                self.next_bone_sway=0.0
                self.pose_repairs+=1
                if self.pose_repairs<=3:self.log('legs: engine pose reset repaired '+str(self.pose_repairs))


            view=getattr(controller,'Rotation',controller.CalcViewRotation)
            proxy=SimpleNamespace(CalcViewRotation=SimpleNamespace(Pitch=view.Pitch,Yaw=view.Yaw,Roll=controller.CalcViewRotation.Roll),
                CalcViewLocation=controller.CalcViewLocation,ForegroundFOV=controller.ForegroundFOV,
                FOVAngle=controller.FOVAngle,bForegroundFOV=controller.bForegroundFOV)
            now=time.perf_counter()
            if self.sync_phase_materials and now >= self.next_material_sync:
                self.next_material_sync=now+.10
                sync_materials(current.Mesh,mesh)
            dt=0.0 if self.motion_time is None else now-self.motion_time
            if self.motion_time is None or dt>=.001:self.motion_time=now
            motion=self.motion.step(float(view.Yaw),dt,self.motion_speed)
            if now>=self.next_bone_sway:
                self.next_bone_sway=now+1/30
                posed=animate(self.saved_bases,self.pose_chains,self.sway_toes,self.motion.phase,self.motion.turn if self.turn_sway else 0.0,max(.35,min(1.,self.motion_speed)))
                for index,values in posed.items():
                    entry=mesh.SpaceBases[index]
                    for field,plane_values in zip(('XPlane','YPlane','ZPlane','WPlane'),values):
                        plane=getattr(entry,field)
                        for key,value in zip(('X','Y','Z','W'),plane_values):setattr(plane,key,value)
                    mesh.SpaceBases[index]=entry
                self.last_animated=posed
            self.presentation_floor+=(self.floor_offset-self.presentation_floor)*(1-math.exp(-12*max(0,min(.1,dt))))
            zoom,x,y,z=self.debug_transform
            rendered=placement(proxy,aspect,self.source_rotation,self.feet_local,self.pose_joints,self.pose_scale,self.view_contact,self.reveal,self.presentation_floor,zoom,(x,y,z),motion)
            if rendered is None:
                self.status='hidden: viewmodel exceeds lower-screen bounds'
                self.set_visible(False)
                return
            rotation,translation,draw_scale,fov=rendered
            mesh=self.mesh
            absolute_transform(mesh)
            mesh.Scale=1.0
            if getattr(self,'draw_scale',None)!=draw_scale:
                mesh.SetScale3D(vec(*draw_scale))
                self.draw_scale=draw_scale
            if self.applied_fov != fov:
                mesh.SetFOV(fov)
                self.applied_fov = fov
            if getattr(self, 'applied_rotation', None) != rotation:
                mesh.SetRotation(unrealsdk.make_struct('Rotator',Pitch=rotation[0],Yaw=rotation[1],Roll=rotation[2]))
                self.applied_rotation=rotation
            if getattr(self, 'applied_translation', None) != translation:
                mesh.SetTranslation(vec(*translation))
                self.applied_translation=translation


            self.set_visible(True)
            if self.diagnostic_samples<2 and now>=self.diagnostic_due:
                self.diagnostic_samples+=1
                self.diagnostic_due=now+.4
                report(mesh,self.pawn.Mesh,sorted({i for chain in self.pose_chains for i in chain}),self.bone_names,self.log,
                       'absolute transform sample '+str(self.diagnostic_samples))
        except Exception as error:
            self.stop()
            self.failed=True
            self.status='foreground placement failed: '+str(error)
            self.log(self.status)
