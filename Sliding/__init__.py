

from __future__ import annotations

import math
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import unrealsdk
from unrealsdk import logging
from unrealsdk.hooks import Type
from unrealsdk.unreal import BoundFunction, UObject, WeakPointer, WrappedStruct

from mods_base import SETTINGS_DIR, build_mod, get_pc, hook
from mods_base.options import BoolOption, SliderOption
from .leg_tuning import character_tuning
from .slide_actions import action_busy
from .slide_contact import SlideContact
from .phase_speed import PhaseSpeed, rescale_slide
from .movement_compat import MovementCompatibility
phase_speed = PhaseSpeed()
movement_compat = MovementCompatibility(get_pc, lambda: S.sliding)
from .landing_momentum import LandingMomentum
landing_momentum = LandingMomentum()
from .aerial_slide import air_speed


try:
    import willow1_mod_menu
except ImportError as error:
    logging.dev_warning(f"[Sliding] mod menu initialization unavailable: {error}")
from .slide_particles import SlideParticles
from .slope_physics import projected_acceleration
from .leg_viewmodel import reveal_amount
from .slide_feel import jump_retention, tuned_slope, sway, downhill_support, steer_slide
from .experimental_legs import Legs

try:
    from .terrain_audio import SlideAudio, decode_embedded

except ImportError as _import_error:
    SlideAudio = None
    logging.dev_warning(f"[Sliding] slide sound unavailable: {_import_error}")




IN_THE_AIR = 2

MIN_START_FRACTION = 0.6
SPRINT_GRACE = 0.30
COOLDOWN = 0.25
MOMENTUM_SPRINT_FRACTION = 0.90
EXIT_SPEED = 260.0
AIR_GRACE = 0.20
WALL_RATIO = 0.45
SLOPE_DOWN_GAIN = 1.5
SLOPE_UP_COST = 3.0

SLOPE_G = 1800.0
SLOPE_DEADZONE = 0.08
SLIDE_MAX_FACTOR = 1.5
FIRE_TAIL = 0.6
AUDIO_FADE_ABRUPT = 0.06
AUDIO_FADE_MOMENTUM = 0.35
FOV_RATE = 10.0


UNITS_PER_DEGREE = 65536.0 / 360.0


TILT_IN_TIME = 0.25
TILT_OUT_TIME = 0.40
CAM_IN_TIME = 0.20
CAM_OUT_TIME = 0.35
VIEW_ROT_PARAMS = ("POVRotation", "out_Rotation", "out_CamRot")
DUMP_DELAY = 0.30
LOG_LINES = 400
REF_WINDOW = 0.35
CARRY_WINDOW = 0.30


STOCK_WALK = 440
STOCK_AIM = 293
STOCK_CROUCH = 176
STOCK_SLIDE = 1350
STOCK_SLIDE_DECEL = 770

# These used to be options; they are fixed now.
RUN_SPEED = 764.0       # sprint speed (the game's own is 594)
FOV_BOOST = 12.0        # degrees of extra FOV while sliding
CAMERA_TILT = 14.0      # degrees of camera roll while sliding
ARMS_LEAN = 2450.0      # arms lean while sliding (182 units = 1 degree)
ARMS_OFFSET = -4.0      # arms vertical offset while sliding (units)

FONT = "ui_fonts.font_willowbody_18pt"
TEXT_LEFT = 30
TEXT_TOP = 150

SlideSpeed = SliderOption(f"Slide Speed (default = {STOCK_SLIDE})", STOCK_SLIDE, 200, 4000, 10, True)
SlideDecel = SliderOption(
    f"Slide Deceleration (default = {STOCK_SLIDE_DECEL})",
    STOCK_SLIDE_DECEL,
    100,
    3000,
    10,
    True,
    description="Higher = shorter slide.",
)
SlopeInfluence = SliderOption(
    "Slope Influence (%)",
    100,
    0,
    300,
    10,
    True,
    description="Downhill faster, uphill slower.",
)
SlideMeleeDamage = SliderOption(
    "Slide Melee Damage (%)",
    100,
    0,
    500,
    10,
    True,
    description="Melee damage while sliding (the contact hit), as a percentage of normal. 100 = unchanged.",
)
SlideSound = BoolOption("Slide Sound", True, "Yes", "No")
SlideParticleEffects = BoolOption("Slide Particles", True, "Yes", "No")
SlideParticleDensity = SliderOption("Slide 3D Particle Density (%)", 150, 25, 200, 25, True)
SlideParticleScale = SliderOption("Slide 3D Particle Size (%)", 100, 5, 100, 5, True)
SlideSoundVolume = SliderOption("Slide Sound Volume (%)", 30, 0, 100, 5, True)
SlidePitchVariation = SliderOption("Slide Sound Pitch Variation (%)", 10, 0, 30, 1, True)
CameraEffect = BoolOption("Camera Effect (FOV)", True, "Yes", "No")
DebugTool = BoolOption(
    "Debugging Tool",
    False,
    "On",
    "Off",
    description=(
        "Shows the on-screen slide info, writes a log file and saves a diagnostic dump on every "
        "crouch press. Files go to the Sliding_diagnostics folder."
    ),
)


slide_contact = SlideContact(lambda text: warn_once(text))

class S:


    sliding = False
    speed = 0.0
    initial_direction = (1.0,0.0)
    dir_x = 0.0
    dir_y = 0.0
    last_z = 0.0
    slide_time = 0.0
    blocked_time = 0.0
    pending_slide_until = 0.0
    pending_ref = None
    air_time = 0.0
    cooldown = 0.0
    stock_crouched = 0.4
    last_sprint = -100.0
    duck_prev = False
    jump_pending = False

    carry = False
    carry_applied = False
    carry_age = 0.0
    carry_speed = 0.0
    stock_air_speed: float | None = None

    fov_active = False
    fov_base = 0.0

    fire_until = 0.0
    poll_bad: set[str] = set()
    max_speed = 0.0
    slope_accel = 0.0
    slope_src = "-"
    anim_mode = "-"
    audio_load_failed = False

    cam_t = 0.0
    cam_calls = 0
    cam_param: str | None = None

    anim_saved: tuple[float, float, float] | None = None
    melee_def_dumped = False

    tilt_t = 0.0
    arm_ref: Any = None
    arm_rest: tuple[float, ...] | None = None
    arm_status = "-"
    dump_at: float | None = None

    snap: tuple[float, float, float, float, bool] | None = None

    hist: tuple[float, float, float, float] | None = None
    why = "-"
    log: deque[str] = deque(maxlen=LOG_LINES)

    last_t: float | None = None
    status = "idle"
    last_event = "-"
    warned: set[str] = set()
    duck_source = "pc.bDuck"


font = None
white = None


def log_path(name: str) -> Path:
    folder = Path(SETTINGS_DIR).parent / "Sliding_diagnostics"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def write_log(msg: str) -> None:

    line = f"{time.strftime('%H:%M:%S')} {msg}"
    S.log.append(line)
    if DebugTool.value:
        try:
            with log_path("Sliding_log.txt").open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass


def warn_once(msg: str) -> None:
    if msg not in S.warned:
        S.warned.add(msg)
        logging.dev_warning(f"[Sliding] {msg}")
        write_log(f"WARN {msg}")


def event(msg: str) -> None:
    S.last_event = msg
    write_log(msg)
    if DebugTool.value:
        logging.info(f"[Sliding] {msg}")


particles = SlideParticles(log=lambda m: write_log(f"particles: {m}"))

legs = Legs(lambda message: write_log(message))

audio = SlideAudio(log=lambda m: write_log(f"audio: {m}")) if SlideAudio is not None else None


def ensure_audio() -> bool:

    if audio is None:
        return False
    if audio.loaded:
        return True
    if S.audio_load_failed:
        return False
    try:
        custom = log_path("Sliding_slide.wav")
        if custom.exists():
            audio.load(custom.read_bytes())
            source = "custom Sliding_slide.wav"
        else:
            from .sound_data import WAV_ZB64
            audio.load(decode_embedded(WAV_ZB64))
            source = "built-in"
        write_log(f"sound loaded ({source}, {audio.audible_seconds:.2f}s audible)")
        return True
    except Exception as ex:
        S.audio_load_failed = True
        warn_once(f"slide sound unavailable ({type(ex).__name__}: {ex})")
        return False


def estimate_remaining() -> float:

    net = max(60.0, float(SlideDecel.value) - S.slope_accel)
    return min(5.0, max(0.0, (S.speed - exit_speed()) / net))


def start_slide_sound() -> None:
    if not SlideSound.value or not ensure_audio() or audio is None:
        return
    pc = get_pc()
    if pc is not None and pc.Pawn is not None:
        particles.tick(pc.Pawn, True, time.perf_counter(), controller=pc,
                       density=float(SlideParticleDensity.value),
                       scale=float(SlideParticleScale.value)/100.0,
                       emit_enabled=bool(SlideParticleEffects.value))
    audio.select_surface(particles.surface)
    audio.start(
        estimate_remaining(),
        float(SlideSoundVolume.value) / 100.0,
        float(SlidePitchVariation.value) / 100.0,
    )
    if audio.playing:
        write_log(f"sound start, playback rate {audio.rate:.2f}, expected {estimate_remaining():.2f}s")
    else:
        write_log(f"sound did not start: {audio.status()}")


def stop_slide_sound(reason: str) -> None:
    if audio is not None:

        audio.fade_out(AUDIO_FADE_MOMENTUM if reason == "slowed down" else AUDIO_FADE_ABRUPT)


def driving(pawn: UObject) -> bool:
    try:
        return pawn.Wheels is not None and len(pawn.Wheels) > 0
    except Exception:
        return False


def duck_held(pc: UObject, pawn: UObject) -> bool:

    if S.duck_source == "pc.bDuck":
        try:
            return bool(pc.bDuck)
        except Exception:
            S.duck_source = "pawn.bWantsToCrouch"
            warn_once("pc.bDuck not found, using pawn.bWantsToCrouch")
    try:
        return bool(pawn.bWantsToCrouch)
    except Exception:
        S.duck_source = "pawn.bIsCrouched"
        return bool(pawn.bIsCrouched)


def min_start_speed() -> float:
    return max(100.0, movement_compat.run_speed(RUN_SPEED) * MIN_START_FRACTION)


def exit_speed() -> float:
    return min(EXIT_SPEED, float(SlideSpeed.value) * 0.5)


def set_ground_speed(pawn: UObject, wanted: float) -> None:
    if bool(getattr(pawn, "bIsPhaseWalking", False)):
        return

    if abs(float(pawn.GroundSpeedBaseValue) - wanted) > 0.5:
        pawn.GroundSpeedBaseValue = wanted
    if abs(float(pawn.GroundSpeed) - wanted) > 0.5:
        pawn.GroundSpeed = wanted


def apply_ground_speed(pc: UObject, pawn: UObject) -> None:
    if movement_compat.active():
        return

    if bool(pawn.bIsCrouched):

        share = float(pawn.CrouchedPct)
        wanted = float(STOCK_CROUCH) / share if share > 0 else float(STOCK_CROUCH)
    elif pc.IsZoomed() is True:
        wanted = float(STOCK_AIM)
    elif bool(pawn.bIsSprinting):
        wanted = RUN_SPEED
    else:
        wanted = float(STOCK_WALK)
    set_ground_speed(pawn, wanted)


def dump_melee_definition() -> None:
    """Debugging Tool: once per session, save every property of the slide's melee definition."""
    if S.melee_def_dumped or not DebugTool.value:
        return
    pointer = slide_contact.definition
    definition = pointer() if pointer is not None else None
    if definition is None:
        return
    S.melee_def_dumped = True
    try:
        lines: list[str] = []
        dump_object(lines, "slide melee definition", definition)
        path = log_path(f"Sliding_melee_definition_{time.strftime('%Y%m%d-%H%M%S')}.txt")
        path.write_text("\n".join(lines), encoding="utf-8")
        write_log(f"melee definition dump written: {path}")
    except Exception as ex:
        warn_once(f"melee definition dump failed ({type(ex).__name__}: {ex})")


def set_horizontal_velocity(pawn: UObject, x: float, y: float) -> None:
    v = pawn.Velocity
    v.X = x
    v.Y = y
    pawn.Velocity = v





def apply_slide_values(pawn: UObject, phys_air: bool) -> None:

    base = float(STOCK_WALK)
    set_ground_speed(pawn, base)
    if bool(getattr(pawn, "bIsPhaseWalking", False)):
        base = max(1.0, float(pawn.GroundSpeed))
    pawn.CrouchedPct = S.speed / base
    set_horizontal_velocity(pawn, S.dir_x * S.speed, S.dir_y * S.speed)


def begin_slide(pc: UObject, pawn: UObject, vx: float, vy: float, spd: float) -> None:
    S.sliding = True
    slide_contact.reset()
    S.slide_time = 0.0
    S.air_time = 0.0
    S.blocked_time = 0.0
    airborne = int(pawn.Physics) == IN_THE_AIR
    landing = None if airborne else landing_momentum.consume(time.perf_counter())
    S.phase_multiplier = phase_speed.update(pc, pawn, time.perf_counter())
    S.speed = spd if airborne else max(float(SlideSpeed.value)*S.phase_multiplier, spd)
    if landing is not None:
        S.speed = max(S.speed, landing[2])
        S.speed += min(landing[3], max(0.0, float(SlideSpeed.value)*SLIDE_MAX_FACTOR-S.speed))
    S.air_entry_speed = S.speed
    S.was_air = airborne
    S.max_speed = S.speed * SLIDE_MAX_FACTOR
    S.slope_accel = 0.0
    S.dir_x = vx / spd
    S.dir_y = vy / spd
    S.initial_direction = (S.dir_x,S.dir_y)
    S.last_z = float(pawn.Location.Z)
    S.status = "sliding"
    if not S.fov_active:
        S.fov_base = float(pc.DesiredFOVBaseValue)
    S.fov_active = True
    event(f"slide start {S.speed:.0f} (pre-press speed {spd:.0f})")
    start_slide_sound()
    apply_slide_values(pawn, int(pawn.Physics) == IN_THE_AIR)
    slide_contact.start(pawn, float(SlideMeleeDamage.value))
    dump_melee_definition()


def end_slide(pawn: UObject, reason: str) -> None:
    S.sliding = False
    slide_contact.reset()
    S.cooldown = COOLDOWN
    S.status = "idle"
    stop_slide_sound(reason)
    particles.stop()
    try:
        pawn.CrouchedPct = S.stock_crouched
    except Exception as ex:
        warn_once(f"could not restore CrouchedPct ({ex})")
    event(f"slide end: {reason}")


def slide_jump(pc: UObject, pawn: UObject) -> None:

    actual = math.hypot(float(pawn.Velocity.X),float(pawn.Velocity.Y))
    available = min(S.speed,actual)
    baseline = min(available,movement_compat.run_speed(RUN_SPEED)*.9)
    speed = baseline + (available-baseline)*jump_retention(S.slide_time)
    end_slide(pawn, "jump")
    S.carry = True
    S.carry_applied = False
    S.carry_age = 0.0
    S.carry_speed = speed


    try:
        pc.bDuck = 0
    except Exception as ex:
        warn_once(f"could not clear bDuck ({ex})")


    if int(pawn.Physics) != IN_THE_AIR:
        try:
            pawn.bWantsToCrouch = False
        except Exception as ex:
            warn_once(f"could not clear bWantsToCrouch ({ex})")
        try:
            pawn.DoJump(True)
        except Exception as ex:
            warn_once(f"DoJump failed ({ex})")


def process_carry(pawn: UObject, phys_air: bool, dt: float) -> None:

    if not S.carry:
        return
    S.carry_age += dt
    if phys_air:
        if not S.carry_applied:
            S.carry_applied = True
            if S.stock_air_speed is None:
                S.stock_air_speed = float(pawn.AirSpeed)

            pawn.AirSpeed = max(S.stock_air_speed, S.carry_speed)
            set_horizontal_velocity(pawn, S.dir_x * S.carry_speed, S.dir_y * S.carry_speed)
            event(f"slide jump carry {S.carry_speed:.0f}")
    elif S.carry_applied or S.carry_age > CARRY_WINDOW:
        S.carry = False
        S.carry_applied = False
        if S.stock_air_speed is not None:
            pawn.AirSpeed = S.stock_air_speed
            S.stock_air_speed = None


def ease_fov(pc: UObject, dt: float) -> None:
    if not S.fov_active:
        return
    if not S.sliding and abs(float(pc.DesiredFOV) - S.fov_base) < 0.05:
        pc.DesiredFOV = S.fov_base
        S.fov_active = False
        return
    boost = FOV_BOOST if S.sliding and CameraEffect.value else 0.0
    target = S.fov_base + boost
    cur = float(pc.DesiredFOV)
    pc.DesiredFOV = cur + (target - cur) * min(1.0, dt * FOV_RATE)


def smoothstep(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def read_arm_rest(mesh: UObject) -> tuple[float, ...]:
    ro = mesh.RotOrigin
    o = mesh.Origin
    return (float(ro.Pitch), float(ro.Yaw), float(ro.Roll), float(o.X), float(o.Y), float(o.Z))


def write_arms(mesh: UObject, v: tuple[float, ...] | list[float]) -> None:
    ro = mesh.RotOrigin
    ro.Pitch = int(round(v[0]))
    ro.Yaw = int(round(v[1]))
    ro.Roll = int(round(v[2]))
    mesh.RotOrigin = ro
    o = mesh.Origin
    o.X = v[3]
    o.Y = v[4]
    o.Z = v[5]
    mesh.Origin = o


def restore_arms() -> None:

    try:
        mesh = S.arm_ref() if S.arm_ref is not None else None
        if mesh is not None and S.arm_rest is not None:
            write_arms(mesh, S.arm_rest)
    except Exception as ex:
        warn_once(f"could not restore arms ({ex})")
    S.arm_ref = None
    S.arm_rest = None
    S.tilt_t = 0.0


def update_tilt(pawn: UObject, dt: float) -> None:

    pc=get_pc()
    want = S.sliding and not action_busy(pc,pawn)
    if not want and S.tilt_t <= 0.0 and S.arm_rest is None:
        S.arm_status = "idle"
        return

    arms = pawn.Arms
    if arms is None:
        S.arm_status = "pawn.Arms is None"
        return

    try:
        if want and len(arms.Attachments) == 0:
            want = False
    except Exception:
        warn_once("arms.Attachments not readable, tilting without the weapon check")
    mesh = arms.SkeletalMesh
    if mesh is None:
        S.arm_status = "arms.SkeletalMesh is None"
        return

    current = S.arm_ref() if S.arm_ref is not None else None
    if current is None or current != mesh:

        S.arm_rest = read_arm_rest(mesh)
        S.arm_ref = WeakPointer(mesh)

    step = dt / (TILT_IN_TIME if want else TILT_OUT_TIME)
    S.tilt_t = min(1.0, S.tilt_t + step) if want else max(0.0, S.tilt_t - step)
    k = smoothstep(S.tilt_t)
    rest = S.arm_rest
    assert rest is not None

    roll_sway,bob_sway = sway(S.slide_time,S.speed)
    delta = (ARMS_LEAN+roll_sway, 0.0, 0.0, 0.0, 0.0, ARMS_OFFSET+bob_sway)
    write_arms(mesh, [r + d * k for r, d in zip(rest, delta)])
    S.arm_status = f"ok t={S.tilt_t:.2f}"
    if S.tilt_t <= 0.0 and not want:
        write_arms(mesh, rest)
        S.arm_ref = None
        S.arm_rest = None





def update_cam(dt: float) -> None:
    want = S.sliding and abs(CAMERA_TILT) > 0.0
    if want:
        S.cam_t = min(1.0, S.cam_t + dt / CAM_IN_TIME)
    else:
        S.cam_t = max(0.0, S.cam_t - dt / CAM_OUT_TIME)


@hook(hook_func="WillowGame.WillowPlayerController:GetPlayerViewPoint", hook_type=Type.POST)
def on_view_point(
    obj: UObject,
    args: WrappedStruct,
    _ret: Any,
    _func: BoundFunction,
) -> None:
    if S.cam_t <= 0.0:
        return
    try:
        roll = CAMERA_TILT * smoothstep(S.cam_t) * UNITS_PER_DEGREE
        names = (S.cam_param,) if S.cam_param else VIEW_ROT_PARAMS
        for name in names:
            try:
                rot = getattr(args, name)
            except AttributeError:
                continue
            rot.Roll = int(round(float(rot.Roll) + roll))
            setattr(args, name, rot)
            S.cam_param = name
            S.cam_calls += 1
            return
        warn_once("GetPlayerViewPoint has none of the expected rotation parameters")
    except Exception as ex:
        warn_once(f"camera roll failed ({type(ex).__name__}: {ex})")





def restore_anim(pawn: UObject | None) -> None:
    saved = S.anim_saved
    S.anim_saved = None
    S.anim_mode = "-"
    if saved is None or pawn is None:
        return
    try:
        pawn.Arms.GlobalAnimRateScale = saved[0]
        pawn.Bob = saved[1]
        pawn.BobBaseValue = saved[2]
    except Exception as ex:
        warn_once(f"could not restore animation values ({ex})")


def firing_now(pc: UObject, pawn: UObject, now: float) -> bool:

    if now < S.fire_until:
        return True
    probes = (
        ("bFire", lambda: int(pc.bFire) != 0),
        ("IsFiring", lambda: bool(pawn.IsFiring())),
        ("bReloading", lambda: int(pawn.bReloading) != 0),
    )
    active = False
    for name, probe in probes:
        if name in S.poll_bad:
            continue
        try:
            if probe():
                active = True
        except Exception as ex:
            S.poll_bad.add(name)
            warn_once(f"fire probe {name} unavailable ({ex})")
    if active:
        S.fire_until = now + FIRE_TAIL
    return active


def note_fire(source: str) -> None:

    S.fire_until = time.perf_counter() + FIRE_TAIL
    if S.sliding and S.anim_saved is not None:
        pc = get_pc()
        if pc is not None and pc.Pawn is not None:
            pc.Pawn.Arms.GlobalAnimRateScale = 1.0


@hook(hook_func="WillowGame.WillowPlayerController:StartFire", hook_type=Type.PRE)
def on_start_fire(
    obj: UObject,
    _args: WrappedStruct,
    _ret: Any,
    _func: BoundFunction,
) -> None:
    try:
        if obj == get_pc():
            note_fire("StartFire")
    except Exception as ex:
        warn_once(f"StartFire hook failed ({type(ex).__name__}: {ex})")


@hook(hook_func="WillowGame.WillowPlayerPawn:WeaponFired", hook_type=Type.PRE)
def on_weapon_fired(
    obj: UObject,
    _args: WrappedStruct,
    _ret: Any,
    _func: BoundFunction,
) -> None:
    try:
        pc = get_pc()
        if pc is not None and pc.Pawn is not None and obj == pc.Pawn:
            note_fire("WeaponFired")
    except Exception as ex:
        warn_once(f"WeaponFired hook failed ({type(ex).__name__}: {ex})")


def update_anim(pc: UObject, pawn: UObject, now: float) -> None:
    want = S.sliding
    if want:
        arms = pawn.Arms
        if S.anim_saved is None:
            S.anim_saved = (
                float(arms.GlobalAnimRateScale),
                float(pawn.Bob),
                float(pawn.BobBaseValue),
            )
            event("walk animation frozen")
        rate = max(.01, S.anim_saved[0]) if S.anim_saved[0] > 0 else 1.0
        mode = "native animations; slide bob suppressed"
        if mode != S.anim_mode:
            S.anim_mode = mode
            event(f"arms animation {mode}")
        if abs(float(arms.GlobalAnimRateScale) - rate) > 1e-4:
            arms.GlobalAnimRateScale = rate
        pawn.BobBaseValue = 0.0
        pawn.Bob = 0.0
    elif S.anim_saved is not None:
        restore_anim(pawn)
        S.anim_mode = "-"
        event("walk animation restored")





def obj_name(o: Any) -> str:
    try:
        return f"{o.Class.Name} '{o._path_name()}'"
    except Exception:
        try:
            return f"{o.Class.Name} '{o.Name}'"
        except Exception:
            return repr(o)


def fmt(v: Any, depth: int = 0) -> str:
    if v is None or isinstance(v, (bool, int, float, str)):
        return repr(v)
    if isinstance(v, UObject):
        return obj_name(v)
    try:
        if isinstance(v, WrappedStruct):
            if depth >= 4:
                return "{...}"
            parts = []
            for f in v._type._fields():
                try:
                    parts.append(f"{f.Name}={fmt(getattr(v, f.Name), depth + 1)}")
                except Exception as ex:
                    parts.append(f"{f.Name}=<err {ex}>")
            return "{" + ", ".join(parts) + "}"
        if type(v).__name__ == "WrappedArray":
            n = len(v)
            shown = ", ".join(fmt(v[i], depth + 1) for i in range(min(n, 8)))
            return f"[{shown}{', ...' if n > 8 else ''}] (len {n})"
    except Exception as ex:
        return f"<err {ex}>"
    return repr(v)


def dump_object(lines: list[str], title: str, obj: Any) -> None:
    lines.append("")
    lines.append("=" * 78)
    lines.append(f"{title}: {obj_name(obj) if obj is not None else 'None'}")
    lines.append("=" * 78)
    if obj is None:
        return
    functions: list[str] = []
    cls = obj.Class
    while cls is not None:
        lines.append(f"--- properties of {cls.Name} ---")
        try:
            for f in cls._fields():
                kind = f.Class.Name
                if kind.endswith("Property"):
                    try:
                        lines.append(f"{f.Name} ({kind}) = {fmt(getattr(obj, f.Name))}")
                    except Exception as ex:
                        lines.append(f"{f.Name} ({kind}) = <err {ex}>")
                elif kind == "Function":
                    functions.append(f"{cls.Name}.{f.Name}")
        except Exception as ex:
            lines.append(f"<could not list fields of {cls.Name}: {ex}>")
        try:
            cls = cls.SuperField
        except Exception:
            break
    lines.append("--- functions ---")
    lines.append(", ".join(functions) if functions else "(none found)")


def dump_info(tag: str, full: bool = True) -> None:
    pc = get_pc()
    lines = [
        f"Sliding {__version__} dump  tag={tag}  {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"python {sys.version.split()[0]}",
        f"mod state: sliding={S.sliding} speed={S.speed:.1f} slide_time={S.slide_time:.2f} "
        f"tilt_t={S.tilt_t:.2f} arms={S.arm_status} duck_source={S.duck_source}",
        f"last event: {S.last_event}",
        f"audio: {audio.status() if audio is not None else 'unavailable'}",
        f"particles: {particles.status}",
        f"particle trace: {particles.trace_detail}",
        f"slide melee: {slide_contact.status}",
        f"legs: attached={legs.mesh is not None} ready={legs.ready} failed={legs.failed} status={getattr(legs, 'status', '')} tuning={getattr(legs, 'debug_transform', None)}",
        f"slope: {S.slope_src} accel {S.slope_accel:+.0f}  anim: {S.anim_mode}",
    ]
    try:
        from mods_base import Game

        lines.append(f"game: {Game.get_current()}")
    except Exception:
        pass


    def section(title: str, getter: Any) -> None:
        try:
            dump_object(lines, title, getter())
        except Exception as ex:
            lines.append("")
            lines.append(f"{title}: <failed: {type(ex).__name__}: {ex}>")

    if pc is None:
        lines.append("no player controller")
    elif full:
        section("PlayerController", lambda: pc)
        section("Pawn", lambda: pc.Pawn)
        section("PlayerCamera", lambda: pc.PlayerCamera)
        section("Pawn.Weapon", lambda: pc.Pawn.Weapon)
        section("Pawn.Arms", lambda: pc.Pawn.Arms)
        section("Pawn.Arms.SkeletalMesh", lambda: pc.Pawn.Arms.SkeletalMesh)
        section("Pawn.Mesh", lambda: pc.Pawn.Mesh)
        section("Pawn.Arms.Animations (AnimTree)", lambda: pc.Pawn.Arms.Animations)
        section("PlayerInput", lambda: pc.PlayerInput)

    lines.append("")
    lines.append("=" * 78)
    lines.append("this mod's own log (most recent last)")
    lines.append("=" * 78)
    lines.extend(S.log if full else list(S.log)[-30:])

    path = log_path(f"Sliding_dump_{tag}_{time.strftime('%Y%m%d-%H%M%S')}.txt")
    path.write_text("\n".join(lines), encoding="utf-8")
    logging.info(f"[Sliding] dump written to {path}")
    write_log(f"dump written: {path}")


def slope_accel(pawn: UObject, dz: float, dt: float) -> float:

    influence = float(SlopeInfluence.value) / 100.0
    try:
        n = pawn.Floor
        normal = (float(n.X),float(n.Y),float(n.Z))
        if normal[2] < float(pawn.WalkableFloorZ):
            S.slope_src = 'unwalkable slope'
            return 0.0
        gravity = float(pawn.GetGravityZ())
        if not math.isfinite(gravity) or abs(gravity) < 1:
            S.slope_src = 'gravity unavailable'
            return 0.0
        projected = projected_acceleration(normal,(S.dir_x,S.dir_y),gravity,influence)

        if S.slide_time > .25 and dt > 0 and dz < 0 and projected >= 0:
            descent=min(.35,-dz/max(1.0,S.speed*dt))
            projected=max(projected,min(4000,abs(gravity))*descent*influence)
        target = downhill_support(projected,S.slide_time,float(SlideDecel.value))
        if target <= 0:
            S.slope_src = 'regular slide (flat/uphill)'
            return 0.0
        S.slope_src = 'downhill boost taper'
        if target < S.slope_accel:
            return target
        return S.slope_accel + (target-S.slope_accel)*(1-math.exp(-12*max(0,dt)))
    except Exception as ex:
        S.slope_src = 'floor/gravity unavailable'
        warn_once(f'slope sampling failed ({ex})')
        return 0.0


def pick_reference(now: float) -> tuple[float, float, float, bool | None, str] | None:

    snap = S.snap
    if snap is not None and now - snap[0] <= REF_WINDOW:
        return snap[1], snap[2], snap[3], snap[4], "hook"
    hist = S.hist
    if hist is not None and now - hist[0] <= REF_WINDOW:
        return hist[1], hist[2], hist[3], None, "history"
    return None


def nearby_walkable_floor(pawn):

    try:
        if float(pawn.Velocity.Z) > 50 or particles.trace_bridge is None:
            return False
        from .slide_particles import vec
        loc = pawn.Location
        foot = float(loc.Z)-float(pawn.CylinderComponent.CollisionHeight)
        reach = float(pawn.MaxStepHeight)+8
        actor,point,normal,info = particles.trace_bridge.trace(pawn,
            HitLocation=vec(),HitNormal=vec(),TraceStart=vec(loc.X,loc.Y,loc.Z),
            TraceEnd=vec(loc.X,loc.Y,foot-reach),bTraceActors=True,Extent=vec(),
            HitInfo=unrealsdk.make_struct('Engine.Actor:TraceHitInfo'),ExtraTraceFlags=0)
        return (actor is not None or info.HitComponent is not None) and normal.Z >= float(pawn.WalkableFloorZ) and abs(point.Z-foot) <= reach
    except Exception:
        return False


def try_begin(pc: UObject, pawn: UObject, now: float, phys_air: bool) -> None:
    ref = pick_reference(now)
    landing = None if phys_air else landing_momentum.reference(now)
    if landing is not None:
        ref=(*landing, True, "landing momentum")
    if phys_air:
        v=pawn.Velocity
        ref=(float(v.X),float(v.Y),math.hypot(float(v.X),float(v.Y)),False,'fall velocity')
    reasons: list[str] = []
    if phys_air and float(pawn.Velocity.Z) >= -25:
        reasons.append("air slide requires falling momentum")
    if S.cooldown > 0.0:
        reasons.append(f"cooldown {S.cooldown:.2f}s")
    vx = vy = spd0 = 0.0
    if ref is None:
        reasons.append("no pre-press velocity recorded")
    else:
        vx, vy, spd0, snap_sprint, src = ref
        if spd0 < (150.0 if landing is not None else min_start_speed()):
            reasons.append(f"too slow: {spd0:.0f} < {min_start_speed():.0f} ({src})")
        momentum = spd0 >= movement_compat.run_speed(RUN_SPEED) * MOMENTUM_SPRINT_FRACTION
        if not (phys_air or snap_sprint is True or now - S.last_sprint <= SPRINT_GRACE or momentum):
            reasons.append("not sprinting")
    S.snap = None
    if reasons:
        S.why = "; ".join(reasons)
        event(f"crouch pressed, no slide: {S.why}")
        return
    S.why = "ok"
    begin_slide(pc, pawn, vx, vy, spd0)


def note_crouch_press(source: str) -> None:

    now = time.perf_counter()
    landing_momentum.press(now)
    if S.sliding:
        return
    if S.snap is not None and now - S.snap[0] < 0.05:
        return
    pc = get_pc()
    if pc is None or pc.Pawn is None:
        return
    pawn = pc.Pawn
    if bool(pawn.bIsCrouched):
        return
    v = pawn.Velocity
    vx, vy = float(v.X), float(v.Y)
    S.snap = (now, vx, vy, math.hypot(vx, vy), bool(pawn.bIsSprinting))
    event(f"{source} hook: speed {S.snap[3]:.0f} sprint {S.snap[4]}")


@hook(hook_func="WillowGame.WillowPlayerInput:Duck", hook_type=Type.PRE)
def on_duck_input(
    obj: UObject,
    _args: WrappedStruct,
    _ret: Any,
    _func: BoundFunction,
) -> None:
    try:
        note_crouch_press("Duck")
    except Exception as ex:
        warn_once(f"Duck hook failed ({type(ex).__name__}: {ex})")


@hook(hook_func="WillowGame.WillowPlayerInput:ToggleDuck", hook_type=Type.PRE)
def on_toggle_duck_input(
    obj: UObject,
    _args: WrappedStruct,
    _ret: Any,
    _func: BoundFunction,
) -> None:
    try:
        note_crouch_press("ToggleDuck")
    except Exception as ex:
        warn_once(f"ToggleDuck hook failed ({type(ex).__name__}: {ex})")


def tick(pc: UObject, pawn: UObject, dt: float, now: float) -> None:
    movement_compat.refresh(now)
    vel = pawn.Velocity
    spd = math.hypot(float(vel.X), float(vel.Y))
    phys_air = int(pawn.Physics) == IN_THE_AIR
    landing_momentum.update(phys_air, (vel.X,vel.Y,vel.Z), now)
    if S.sliding and not phys_air:
        landing = landing_momentum.consume(now, before_landing=True)
        if landing is not None:
            S.speed=max(S.speed,landing[2])
            S.speed+=min(landing[3],max(0.0,float(SlideSpeed.value)*SLIDE_MAX_FACTOR-S.speed))
            S.max_speed=max(S.max_speed,S.speed)
    duck = duck_held(pc, pawn)
    pressed = duck and not S.duck_prev
    S.duck_prev = duck
    S.cooldown = max(0.0, S.cooldown - dt)

    if bool(pawn.bIsSprinting) and not phys_air:
        S.last_sprint = now


    if not duck and not S.sliding and not phys_air:
        S.hist = (now, float(vel.X), float(vel.Y), spd)

    if pressed and DebugTool.value:
        S.dump_at = now + DUMP_DELAY
    if S.dump_at is not None and now >= S.dump_at:
        S.dump_at = None
        try:
            dump_info("slide-auto" if S.sliding else "press-auto", full=False)
        except Exception as ex:
            warn_once(f"auto dump failed ({type(ex).__name__}: {ex})")

    if not S.sliding:
        if not S.carry:
            S.stock_crouched = float(pawn.CrouchedPct)
        apply_ground_speed(pc, pawn)
        process_carry(pawn, phys_air, dt)
        ease_fov(pc, dt)
        if pressed:
            try_begin(pc, pawn, now, phys_air)
        return


    rescale_slide(S, phase_speed.update(pc, pawn, now))
    S.slide_time += dt

    if S.jump_pending:
        S.jump_pending = False
        slide_jump(pc, pawn)
        ease_fov(pc, dt)
        return

    z = float(pawn.Location.Z)
    dz = max(-60.0, min(60.0, z - S.last_z))
    S.last_z = z

    if not phys_air:
        S.dir_x,S.dir_y = steer_slide((S.dir_x,S.dir_y),S.initial_direction,float(pc.Rotation.Yaw),dt)
    S.slope_accel = 0.0 if phys_air else slope_accel(pawn, dz, dt)
    if phys_air:
        if not S.was_air:S.air_entry_speed=spd
        S.speed=air_speed(spd,float(pawn.Velocity.Z),S.air_entry_speed,dt)
        if spd>1:S.dir_x,S.dir_y=float(pawn.Velocity.X)/spd,float(pawn.Velocity.Y)/spd
    else:
        S.speed += (S.slope_accel - float(SlideDecel.value)) * dt
    S.was_air=phys_air
    S.speed = min(S.speed, S.max_speed)

    reason = None
    if not duck:
        reason = "crouch released"
    elif S.speed < exit_speed():
        reason = "slowed down"
    elif phys_air:
        S.air_time += dt
        S.blocked_time = 0.0
        if S.air_time>AIR_GRACE and float(pawn.Velocity.Z)>100:
            reason = 'rising into air'
    else:
        S.air_time = 0.0
        if S.slide_time > 0.15 and spd < S.speed * WALL_RATIO:
            S.blocked_time += dt
            if S.blocked_time >= .12:
                reason = "blocked"
        else:
            S.blocked_time = 0.0

    if reason is not None:
        end_slide(pawn, reason)
        ease_fov(pc, dt)
        return


    slide_contact.tick(pawn, now)
    apply_slide_values(pawn, phys_air)
    if audio is not None and audio.playing:
        audio.volume = float(SlideSoundVolume.value) / 100.0
        audio.set_remaining(estimate_remaining())
    ease_fov(pc, dt)


def reset_state() -> None:
    phase_speed.reset()
    S.phase_multiplier = 1.0
    landing_momentum.reset()
    slide_contact.reset()
    particles.stop()
    legs.stop()
    S.pending_slide_until = 0.0
    S.pending_ref = None
    S.sliding = False
    S.carry = False
    S.carry_applied = False
    S.jump_pending = False
    S.fov_active = False
    S.dump_at = None
    S.snap = None
    S.cam_t = 0.0
    if audio is not None:
        audio.fade_out(AUDIO_FADE_ABRUPT)
    try:
        pc = get_pc()
        restore_anim(pc.Pawn if pc is not None else None)
    except Exception:
        S.anim_saved = None
    restore_arms()
    S.status = "idle"
    S.last_t = None





@hook(hook_func="Engine.Pawn:DoJump", hook_type=Type.PRE)
def on_do_jump(
    obj: UObject,
    _args: WrappedStruct,
    _ret: Any,
    _func: BoundFunction,
) -> None:

    pc = get_pc()
    if pc is not None and pc.Pawn is not None and obj == pc.Pawn:
        S.pending_ref = None
        if S.sliding:
            S.jump_pending = True


def on_leg_tick(obj: UObject, args: WrappedStruct, _ret: Any, _func: BoundFunction) -> None:


    if S.sliding and legs.ready and obj == get_pc() and not obj.bBehindView:
        try:
            if obj.WorldInfo.Pauser is None:
                legs.draw(obj,particles.aspect)
        except Exception as ex:
            warn_once(f"early leg placement unavailable ({ex})")


early_leg_hooks = []
for tick_class in ("WillowGame.WillowPlayerController", "Engine.PlayerController"):
    try:
        if unrealsdk.find_object("Function", tick_class+".PlayerTick") is not None:
            early_leg_hooks.append(hook(hook_func=tick_class+":PlayerTick",hook_type=Type.POST)(on_leg_tick))
            break
    except Exception:
        pass


@hook(hook_func="Engine.GameViewportClient:PostRender", hook_type=Type.POST)
def on_render(
    obj: UObject,
    args: WrappedStruct,
    _ret: Any,
    _func: BoundFunction,
) -> None:
    global font, white

    pc = get_pc()
    paused = False
    if audio is not None:
        try:
            paused = bool(pc is not None and pc.WorldInfo.Pauser is not None)
        except Exception:
            paused = False
        audio.tick_native(paused=paused)
    if pc is None or pc.Pawn is None:
        legs.discard_if_changed(None)
        if S.sliding or S.carry:
            reset_state()
        return
    legs.discard_if_changed(pc.Pawn)
    if int(pc.Pawn.Physics) == 0:
        legs.stop()
        return
    if driving(pc.Pawn):
        if S.sliding or S.carry:
            reset_state()
        return

    now = time.perf_counter()
    dt = 0.0 if S.last_t is None else min(0.1, now - S.last_t)
    S.last_t = now

    try:
        tick(pc, pc.Pawn, dt, now)
    except Exception as ex:
        warn_once(f"tick failed ({type(ex).__name__}: {ex})")
        reset_state()

    if args.Canvas is not None:
        particles.aspect = float(args.Canvas.SizeX)/max(1.0,float(args.Canvas.SizeY))
    particles.tick(pc.Pawn, S.sliding, now,
                   density=float(SlideParticleDensity.value),
                   scale=float(SlideParticleScale.value)/100.0, paused=paused, controller=pc,
                   emit_enabled=bool(SlideParticleEffects.value))
    if S.sliding and audio is not None and SlideSound.value:
        audio.select_surface(particles.surface)
    update_cam(dt)
    try:
        update_anim(pc, pc.Pawn, now)
    except Exception as ex:
        warn_once(f"walk animation freeze failed ({type(ex).__name__}: {ex})")
        S.anim_saved = None

    try:
        update_tilt(pc.Pawn, dt)
    except Exception as ex:
        warn_once(f"arms tilt failed ({type(ex).__name__}: {ex})")
        S.arm_status = f"error: {ex}"
        S.arm_ref = None
        S.arm_rest = None
        S.tilt_t = 0.0

    legs.motion_speed=min(1.0,max(0.0,S.speed/1350.0))
    legs.debug_transform=(180.0,-150.0,-30.0,-30.0)
    legs.debug_transform=character_tuning(pc.Pawn.Mesh.SkeletalMesh,legs.debug_transform)
    legs.update(pc.Pawn, S.sliding and not paused and not pc.bBehindView,
                controller=pc, bridge=particles.trace_bridge, aspect=particles.aspect,
                reveal=reveal_amount(S.slide_time,S.speed,exit_speed()))
    if not DebugTool.value:
        return
    canvas = args.Canvas
    if canvas is None:
        return
    try:
        if font is None:
            font = unrealsdk.find_object("Font", FONT)
            white = unrealsdk.make_struct("Color", R=255, G=255, B=255, A=255)
        pawn = pc.Pawn
        spd = math.hypot(float(pawn.Velocity.X), float(pawn.Velocity.Y))
        lines = [
            f"slide: {S.status}  target {S.speed:.0f}  real {spd:.0f}",
            f"sprint {bool(pawn.bIsSprinting)}  crouched {bool(pawn.bIsCrouched)}"
            f"  physics {int(pawn.Physics)}  crouchedPct {float(pawn.CrouchedPct):.2f}",
            f"duck via {S.duck_source}  carry {S.carry}  fov {float(pc.DesiredFOV):.1f}",
            f"arms: {S.arm_status}",
            f"why: {S.why}",
            f"camera: t={S.cam_t:.2f} hook calls={S.cam_calls} param={S.cam_param}",
            f"anim: {S.anim_mode}  slope: {S.slope_src} accel {S.slope_accel:+.0f}",
            f"audio: {audio.status() if audio is not None else 'unavailable'}",
        f"particles: {particles.status}",
            f"last: {S.last_event}",
        ]
        canvas.Font = font
        canvas.DrawColor = white
        for i, line in enumerate(lines):
            canvas.SetPos(TEXT_LEFT, TEXT_TOP + i * 22)
            canvas.DrawText(line, False, 1.0, 1.0)
    except Exception as ex:
        warn_once(f"could not draw debug text ({ex})")


def on_enable() -> None:
    movement_compat.refresh(time.perf_counter())
    particles.reset()
    reset_state()
    write_log("build 0.11.5: fully absolute leg transform; prevent inherited pawn scale")
    write_log(f"early leg hooks: {len(early_leg_hooks)}")

    legs.failed = False


def on_disable() -> None:
    pc = get_pc()
    try:
        if pc is not None and pc.Pawn is not None:
            if not driving(pc.Pawn) and not movement_compat.active():
                set_ground_speed(pc.Pawn, float(STOCK_WALK))
            pc.Pawn.CrouchedPct = S.stock_crouched
            if S.stock_air_speed is not None:
                pc.Pawn.AirSpeed = S.stock_air_speed
            if S.fov_active:
                pc.DesiredFOV = S.fov_base
    except Exception as ex:
        warn_once(f"could not restore values on disable ({ex})")
    try:
        restore_anim(pc.Pawn if pc is not None else None)
    except Exception:
        pass
    restore_arms()
    reset_state()
    if audio is not None:
        audio.close()
    S.stock_air_speed = None
    movement_compat.restore()



__version__: str
__version_info__: tuple[int, ...]

build_mod(
    options=[
        SlideSpeed,
        SlideDecel,
        SlopeInfluence,
        SlideMeleeDamage,
        SlideSound,
        SlideParticleEffects,
        SlideParticleDensity,
        SlideParticleScale,
        SlideSoundVolume,
        SlidePitchVariation,
        CameraEffect,
        DebugTool,
    ],
    keybinds=[],
    hooks=[
        on_render,
        *early_leg_hooks,
        on_do_jump,
        on_duck_input,
        on_toggle_duck_input,
        on_view_point,
        on_start_fire,
        on_weapon_fired,
    ],
    commands=[],
    on_enable=on_enable,
    on_disable=on_disable,
    settings_file=Path(f"{SETTINGS_DIR}/Sliding.json"),
)

logging.info(f"Sliding Loaded: {__version__}, {__version_info__}")
