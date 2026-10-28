import time
import unrealsdk
from unrealsdk.unreal import WeakPointer


def configure_contact(definition, pawn, damage_percent=100.0):
    damage = definition.Damage
    damage.BaseValueScaleConstant = float(damage.BaseValueScaleConstant) * (max(0.0, min(500.0, float(damage_percent))) / 100.0)
    definition.Damage = damage
    cylinder = pawn.CylinderComponent
    radius = max(1.0, float(cylinder.CollisionRadius))
    height = max(1.0, float(cylinder.CollisionHeight))
    definition.bUseTargetCone = False
    definition.bUseTraceBox = False
    definition.bUseDamageRadius = True
    definition.DamageRadius = max(radius, 75.0)
    definition.DamageHeight = height * 2.0 + 30.0
    definition.DamageHeightOffset = -height * 0.25
    definition.DamageConeAngle = 180.0
    definition.bAffectFriendly = False
    definition.bAffectNeutral = False
    definition.bAffectEnemy = True
    definition.bStopMeleeOnLanded = False
    definition.bHitEachTargetOnlyOnce = True
    definition.bMeleeOverPeriodOfTime = True
    definition.MaxMeleeDuration = 3600.0
    definition.AttackInterval = 1.0 / 30.0


class SlideContact:
    def __init__(self, log):
        self.log = log
        self.owner = None
        self.definition = None
        self.status = 'inactive'
        self.next_check = 0.0
        self.position = None
        self.origin_offset = None
        self.checks = 0
        self.next_hit = 0.0

    def reset(self):
        owner = self.owner() if self.owner is not None else None
        definition = self.definition() if self.definition is not None else None
        self.owner = self.definition = None
        self.next_hit = 0.0
        if owner is not None and definition is not None:
            try:
                if owner.MeleeState.MeleeDefinition == definition:
                    owner.EndMeleeOverTime()
            except Exception as error:
                self.log('slide melee cleanup: ' + str(error))

    def start(self, pawn, damage_percent=100.0):
        self.reset()
        if float(damage_percent) <= 0.0:
            self.status = 'slide contact disabled by damage setting'
            return
        try:
            weapon = pawn.Weapon
            bladed = weapon is not None and bool(weapon.bUseWeaponMelee)
            name = 'gd_PlayerShared.Behaviors.BehaviorData_PlayerMeleeAttack'
            if bladed:
                name += 'WithBladedWeapon'
            original = unrealsdk.find_object('MeleeDefinition', name)
            if original is None:
                raise RuntimeError('Player melee definition is not loaded: ' + name)
            private = unrealsdk.construct_object(cls=original.Class, outer=pawn, template_obj=original)
            configure_contact(private, pawn, damage_percent)
            self.owner, self.definition = WeakPointer(pawn), WeakPointer(private)
            pawn.BeginMeleeOverTime(MeleeDefinition=private)
            if pawn.MeleeState.MeleeDefinition != private:
                raise RuntimeError('Engine did not activate slide contact melee')
            self.position = tuple(float(getattr(pawn.Location,k)) for k in ('X','Y','Z'))
            origin = pawn.MeleeState.MeleeStartLocation
            self.origin_offset = tuple(float(getattr(origin,k))-self.position[i] for i,k in enumerate(('X','Y','Z')))
            self.next_check = 0.0
            self.checks = 1
            self.attack(pawn, private, time.perf_counter())
            self.status = 'automatic contact active; ' + ('bladed' if bladed else 'normal') + '; once per enemy'
        except Exception as error:
            self.reset()
            self.status = 'automatic contact failed: ' + str(error)
            self.log(self.status)

    def tick(self, pawn, now):
        if now < max(self.next_check, self.next_hit) or self.owner is None or self.definition is None:
            return
        self.next_check = now + 1.0 / 30.0
        owner, definition = self.owner(), self.definition()
        if owner is None or definition is None or owner != pawn:
            self.reset()
            return
        try:
            state = pawn.MeleeState
            if state.MeleeDefinition != definition:
                self.status = 'contact stopped: native melee state replaced'
                return
            position = tuple(float(getattr(pawn.Location,k)) for k in ('X','Y','Z'))
            if self.position is not None:
                origin = state.MeleeStartLocation
                for index, key in enumerate(('X','Y','Z')):
                    setattr(origin,key,position[index]+self.origin_offset[index])
                state.MeleeStartLocation = origin
            self.position = position
            self.attack(pawn, definition, now)
            self.checks += 1
            self.status = 'automatic moving contact; checks=' + str(self.checks) + '; once per enemy'
        except Exception as error:
            self.reset()
            self.status = 'contact update failed: ' + str(error)
            self.log(self.status)

    def attack(self, pawn, definition, now):
        if now < self.next_hit:
            return
        state = pawn.MeleeState
        previous_hits = len(state.HitActors)
        state.bIsMeleeActive = True
        try:
            definition.MeleeAttack(ContextObject=pawn)
        finally:
            state.bIsMeleeActive = False
            if len(state.HitActors) > previous_hits:
                self.next_hit = now + 0.75
