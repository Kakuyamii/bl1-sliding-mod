import math


class PhaseSpeed:
    def __init__(self):
        self.reset()

    def reset(self):
        self.value = 1.0
        self.next_update = 0.0

    def update(self, pc, pawn, now):
        if not bool(getattr(pawn, 'bIsPhaseWalking', False)):
            self.reset()
            return self.value
        if now < self.next_update:
            return self.value
        self.next_update = now + .1
        try:
            skills = pc.WorldInfo.Game.GlobalSkillManager.ActiveSkills
            bonus = 0.0
            for skill in skills:
                if skill.SkillInstigator != pc:
                    continue
                if 'gd_Skills_Lilith.Action.PhaseSpeed' not in str(skill.Definition):
                    continue
                for effect in skill.SkillEffects:
                    if 'FootSpeed' not in str(effect.EffectData.AttributeToModify):
                        continue
                    modifier = effect.Modifier
                    if modifier is not None:
                        bonus += float(modifier.Value)
            if math.isfinite(bonus):
                self.value = max(1.0, 1.0 + bonus)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            self.value = 1.0
        return self.value


def rescale_slide(state, multiplier):
    previous = getattr(state, 'phase_multiplier', 1.0)
    if multiplier != previous:
        ratio = multiplier / previous
        state.speed *= ratio
        state.max_speed *= ratio
        state.air_entry_speed *= ratio
    state.phase_multiplier = multiplier
