import math
import sys


class MovementCompatibility:
    def __init__(self, get_pc, sliding):
        self.get_pc = get_pc
        self.sliding = sliding
        self.module = None
        self.handler = None
        self.original = None
        self.wrapper = None
        self.next_refresh = 0.0

    def active(self):
        return self.handler is not None and self.handler.get_active_count() > 0

    def run_speed(self, default):
        return float(self.module.RunSpeed.value) if self.active() else default

    def refresh(self, now):
        if now < self.next_refresh:
            return
        self.next_refresh = now + .5
        module = sys.modules.get('MovementSpeedChanger')
        handler = getattr(module, 'on_render', None)
        if handler is self.handler:
            return
        if handler is None:
            self.restore()
            return
        self.restore()
        self.module, self.handler = module, handler
        self.original = handler.__wrapped__
        original = self.original

        def wrapped(obj, args, ret, func):
            pc = self.get_pc()
            pawn = pc.Pawn if pc is not None else None
            if pawn is None or module.driving(pawn) or not (
                self.sliding() or bool(getattr(pawn, 'bIsPhaseWalking', False))
            ):
                return original(obj, args, ret, func)
            if not module.ShowSpeed.value or args.Canvas is None:
                return
            if module.font is None:
                module.font = module.unrealsdk.find_object('Font', module.FONT)
                module.white = module.unrealsdk.make_struct('Color', R=255, G=255, B=255, A=255)
            canvas = args.Canvas
            speed = math.hypot(float(pawn.Velocity.X), float(pawn.Velocity.Y))
            canvas.Font, canvas.DrawColor = module.font, module.white
            canvas.SetPos(module.SPEED_LEFT, module.SPEED_TOP)
            state = 'sliding' if self.sliding() else 'phasewalking'
            canvas.DrawText(f'{state}  {speed:.0f} / {float(pawn.GroundSpeed):.0f}', False, 1.0, 1.0)

        self.wrapper = wrapped
        enabled = self.active()
        handler.__wrapped__ = wrapped
        if enabled:
            handler.enable()

    def restore(self):
        if self.handler is not None and self.handler.__wrapped__ is self.wrapper:
            enabled = self.active()
            self.handler.__wrapped__ = self.original
            if enabled:
                self.handler.enable()
        self.module = self.handler = self.original = self.wrapper = None
        self.next_refresh = 0.0
