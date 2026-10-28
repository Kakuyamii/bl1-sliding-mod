
def action_busy(pc,pawn):
    if pawn is None:return False
    try:
        return bool((pc is not None and pc.bPerformingMeleeAttack) or pawn.IsReloading() or pawn.IsPerformingRestrictedActionSkill())
    except Exception:return False

def scoped_aim(pc,pawn):
    if pc is None or pawn is None:return False
    try:
        weapon=pawn.Weapon
        return weapon is not None and bool(pc.IsZoomed()) and bool(weapon.IsScoped())
    except Exception:return False
