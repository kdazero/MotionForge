from __future__ import annotations

import copy
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .storage import MotionError


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Bone(Model):
    name: str = Field(min_length=1, max_length=128)
    parent: str | None = None
    x: float = Field(0, ge=-10000, le=10000)
    y: float = Field(0, ge=-10000, le=10000)
    rotation: float = Field(0, ge=-3600, le=3600)
    length: float = Field(0, ge=0, le=10000)


class Layer(Model):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    image: str = Field(description="PNG path relative to the workspace, normally inbox/name.png")
    bone: str = Field(min_length=1, max_length=128)
    x: float = Field(
        0, ge=-10000, le=10000, description="Image center X relative to its bone (Spine Y-up coordinates)."
    )
    y: float = Field(0, ge=-10000, le=10000, description="Image center Y relative to its bone.")
    rotation: float = Field(0, ge=-3600, le=3600)
    scale: float = Field(1, gt=0, le=10)


class Keyframe(Model):
    time: float = Field(ge=0, le=20)
    angle: float | None = Field(None, ge=-3600, le=3600)
    x: float | None = Field(None, ge=-10000, le=10000)
    y: float | None = Field(None, ge=-10000, le=10000)
    curve: Literal["linear", "stepped"] | list[float] = "linear"

    @field_validator("curve")
    @classmethod
    def bezier(cls, value):
        if isinstance(value, list):
            if len(value) != 4 or not all(math.isfinite(v) and 0 <= v <= 1 for v in value):
                raise ValueError("Bezier must be [cx1, cy1, cx2, cy2], each in 0..1.")
            if value[0] > value[2]:
                raise ValueError("Bezier X control points must be ordered.")
        return value


class Track(Model):
    bone: str
    channel: Literal["rotate", "translate", "scale"]
    keys: list[Keyframe] = Field(min_length=1, max_length=601)

    @model_validator(mode="after")
    def check(self):
        times = [k.time for k in self.keys]
        if times != sorted(set(times)):
            raise ValueError("Key times must strictly increase, without duplicates.")
        for k in self.keys:
            if self.channel == "rotate":
                if k.angle is None or k.x is not None or k.y is not None:
                    raise ValueError("Rotate keys require angle only.")
            elif k.angle is not None or k.x is None or k.y is None:
                raise ValueError("Translate/scale keys require x and y only.")
            if self.channel == "scale" and (not 0.01 <= k.x <= 10 or not 0.01 <= k.y <= 10):
                raise ValueError("Scale keys must be between 0.01 and 10.")
        return self


PRESETS = {
    "idle": {
        "label": "待機呼吸",
        "roles": ["body"],
        "duration": 2.4,
        "description": "Subtle breathing scale and rise; optional head counter-motion.",
    },
    "sway": {
        "label": "左右擺動",
        "roles": ["body"],
        "duration": 2.0,
        "description": "Gentle rotation around the body's pivot; optional head follow-through.",
    },
    "bounce": {
        "label": "彈跳",
        "roles": ["root", "body"],
        "duration": 1.2,
        "description": "Anticipation, lift, landing and squash/stretch.",
    },
    "wave": {
        "label": "揮手",
        "roles": ["arm"],
        "duration": 2.0,
        "description": "Raise an arm, wave and return; optional hand follow-through.",
    },
    "nod": {
        "label": "點頭",
        "roles": ["head"],
        "duration": 1.6,
        "description": "Two small head nods with a return to setup pose.",
    },
    "walk": {
        "label": "原地走路",
        "roles": ["body", "leg_left", "leg_right"],
        "duration": 1.0,
        "description": "Simple FK walk-in-place; optional opposing arm swing. No foot IK.",
    },
    "talk": {
        "label": "對話",
        "roles": ["body"],
        "duration": 2.4,
        "description": "Conversational body motion; configure a face to include mouth animation.",
    },
    "think": {
        "label": "思考",
        "roles": ["head", "arm"],
        "duration": 2.4,
        "description": "Tilt the head and raise an arm towards the face. Adjust keyframes for the character's proportions.",
    },
    "hit": {
        "label": "受擊",
        "roles": ["body"],
        "duration": 0.7,
        "description": "Recoil and recovery. Suitable for a single image or a rig.",
    },
    "clap": {
        "label": "拍手",
        "roles": ["arm_left", "arm_right"],
        "duration": 1.6,
        "description": "Bring arms together twice; simple FK, tune pivots/angles to make palms meet.",
    },
    "cast": {
        "label": "法師施法",
        "roles": ["body", "arm"],
        "duration": 1.5,
        "description": "Wind-up, arm raise and release. Does not create a spell effect.",
    },
    "slash": {
        "label": "劍士斬擊",
        "roles": ["body", "arm"],
        "duration": 0.9,
        "description": "Anticipation and fast arm swing. Weapon art must be attached separately.",
    },
    "shoot": {
        "label": "舉槍射擊",
        "roles": ["arm"],
        "duration": 1.0,
        "description": "Raise a weapon arm, recoil and recover. Weapon art must be attached separately.",
    },
}


def validate_skeleton(data: dict) -> dict:
    version = data.get("skeleton", {}).get("spine", "")
    if not isinstance(version, str) or not version.startswith("3.8."):
        raise MotionError(
            "Expected the supported 3.8.x JSON schema. Changing the version string does not convert data."
        )
    bones = data.get("bones")
    if not isinstance(bones, list) or not 1 <= len(bones) <= 512:
        raise MotionError("Skeleton must have 1–512 bones.")
    seen = set()
    roots = []
    for bone in bones:
        if not isinstance(bone, dict):
            raise MotionError("Every bone must be an object.")
        name, parent = bone.get("name"), bone.get("parent")
        if not isinstance(name, str) or not name or name in seen:
            raise MotionError("Bone names must be nonempty and unique.")
        if parent is not None and parent not in seen:
            raise MotionError(f"Bone '{name}' must follow its parent '{parent}'.")
        if parent is None:
            roots.append(name)
        seen.add(name)
        for key in ("x", "y", "rotation", "scaleX", "scaleY", "shearX", "shearY", "length"):
            if key in bone and (not isinstance(bone[key], (int, float)) or not math.isfinite(bone[key])):
                raise MotionError(f"Bone '{name}' has invalid {key}.")
    if len(roots) != 1:
        raise MotionError("Exactly one root bone is required.")
    slots = data.get("slots", [])
    slot_names = set()
    for slot in slots:
        if slot.get("bone") not in seen or not slot.get("name") or slot["name"] in slot_names:
            raise MotionError("Slots require unique names and existing bones.")
        slot_names.add(slot["name"])
    skins = data.get("skins", [])
    if not isinstance(skins, list):
        raise MotionError("Spine 3.8 skins must use the array format.")
    for skin in skins:
        if not isinstance(skin, dict) or not skin.get("name"):
            raise MotionError("Invalid skin.")
        if any(slot not in slot_names for slot in skin.get("attachments", {})):
            raise MotionError("Skin attachment references a missing slot.")
    if not isinstance(data.get("animations", {}), dict):
        raise MotionError("Animations must be an object.")
    return {
        "version": version,
        "bones": len(bones),
        "slots": len(slots),
        "skins": [s["name"] for s in skins],
        "animations": list(data.get("animations", {})),
        "root": roots[0],
    }


def duration(animation: dict) -> float:
    def times(value):
        if isinstance(value, dict):
            if isinstance(value.get("time"), (int, float)):
                yield value["time"]
            for child in value.values():
                yield from times(child)
        elif isinstance(value, list):
            for child in value:
                yield from times(child)

    return max(times(animation), default=0)


def build_tracks(data: dict, tracks: list[Track]) -> dict:
    names = {b["name"] for b in data["bones"]}
    result: dict = {"bones": {}}
    if not 1 <= len(tracks) <= 128:
        raise MotionError("Provide 1–128 tracks.")
    for track in tracks:
        if track.bone not in names:
            raise MotionError(f"Unknown bone: {track.bone}")
        target = result["bones"].setdefault(track.bone, {})
        if track.channel in target:
            raise MotionError(f"Duplicate channel: {track.bone}/{track.channel}")
        keys = []
        for key in track.keys:
            value = key.model_dump(exclude_none=True)
            if value.get("curve") == "linear":
                del value["curve"]
            elif isinstance(value.get("curve"), list):
                # Spine 3.8 stores Bezier controls as four separate fields.
                c1, c2, c3, c4 = value["curve"]
                value.update(curve=c1, c2=c2, c3=c3, c4=c4)
            keys.append(value)
        # A curve describes the interval to the NEXT key. Spine 3.8's importer
        # can fail if a Bezier is serialized on the terminal key.
        for field in ("curve", "c2", "c3", "c4"):
            keys[-1].pop(field, None)
        target[track.channel] = keys
    return result


def preset_animation(
    data: dict, preset: str, roles: dict[str, str], seconds: float | None = None, strength: float = 1.0
) -> dict:
    if preset not in PRESETS:
        raise MotionError(f"Unknown preset. Choose from: {', '.join(PRESETS)}")
    if not math.isfinite(strength) or not 0.1 <= strength <= 2:
        raise MotionError("Strength must be 0.1–2.")
    seconds = PRESETS[preset]["duration"] if seconds is None else seconds
    if not math.isfinite(seconds) or not 0.4 <= seconds <= 10:
        raise MotionError("Preset duration must be 0.4–10 seconds.")
    names = {b["name"] for b in data["bones"]}
    for role in PRESETS[preset]["roles"]:
        if role not in roles:
            raise MotionError(
                f"Preset '{preset}' needs role '{role}'. Inspect bones and set the role mapping first."
            )
    if any(b not in names for b in roles.values()):
        raise MotionError("Role mapping references a missing bone.")
    result = {"bones": {}}

    def track(role, channel, samples):
        if role not in roles:
            return
        channels = result["bones"].setdefault(roles[role], {})
        if channel in channels:
            raise MotionError(f"Roles collide on {roles[role]}/{channel}; map these roles to separate bones.")
        keys = []
        for t, value in samples:
            frame = {"time": round(t * seconds, 6)}
            if channel == "rotate":
                frame["angle"] = round(value * strength, 5)
            else:
                offset = 1 if channel == "scale" else 0
                frame.update(
                    {axis: round(offset + (v - offset) * strength, 5) for axis, v in zip(("x", "y"), value)}
                )
            keys.append(frame)
        channels[channel] = keys

    samples = [i / 40 for i in range(41)]
    if preset in ("idle", "talk"):

        def pulse(t):
            return (1 - math.cos(2 * math.pi * t)) / 2

        track("body", "scale", [(t, (1 - 0.012 * pulse(t), 1 + 0.026 * pulse(t))) for t in samples])
        track("body", "translate", [(t, (0, 2 * pulse(t))) for t in samples])
        track("head", "rotate", [(t, -1.8 * pulse(t)) for t in samples])
        if preset == "talk":
            track("body", "rotate", [(t, 1.5 * math.sin(4 * math.pi * t)) for t in samples])
    elif preset == "sway":
        track("body", "rotate", [(t, 6 * math.sin(2 * math.pi * t)) for t in samples])
        track("head", "rotate", [(t, -3 * math.sin(2 * math.pi * t)) for t in samples])
    elif preset == "bounce":
        track(
            "root",
            "translate",
            [
                (0, (0, 0)),
                (0.15, (0, 0)),
                (0.3, (0, 36)),
                (0.45, (0, 52)),
                (0.6, (0, 36)),
                (0.75, (0, 0)),
                (1, (0, 0)),
            ],
        )
        track(
            "body",
            "scale",
            [
                (0, (1, 1)),
                (0.15, (1.14, 0.82)),
                (0.3, (0.92, 1.1)),
                (0.6, (0.96, 1.06)),
                (0.75, (1.17, 0.78)),
                (0.88, (0.98, 1.03)),
                (1, (1, 1)),
            ],
        )
    elif preset == "wave":
        angles = (
            [0, 105, 125, 98, 125, 98, 110, 0] if "forearm" not in roles else [0, 38, 42, 36, 42, 36, 38, 0]
        )
        track(
            "arm",
            "rotate",
            list(zip([0, 0.2, 0.32, 0.44, 0.56, 0.68, 0.8, 1], angles)),
        )
        track(
            "forearm",
            "rotate",
            [(0, 0), (0.2, 110), (0.32, 130), (0.44, 100), (0.56, 130), (0.68, 100), (0.8, 110), (1, 0)],
        )
        track(
            "hand",
            "rotate",
            [(0, 0), (0.2, 12), (0.32, -18), (0.44, 18), (0.56, -18), (0.68, 18), (0.8, 5), (1, 0)],
        )
    elif preset == "nod":
        track("head", "rotate", [(0, 0), (0.18, -12), (0.32, 3), (0.48, 0), (0.64, -9), (0.8, 2), (1, 0)])
    elif preset == "walk":

        def wave(t):
            return math.sin(2 * math.pi * t)

        track("leg_left", "rotate", [(t, 22 * wave(t)) for t in samples])
        track("leg_right", "rotate", [(t, -22 * wave(t)) for t in samples])
        track("arm_left", "rotate", [(t, -15 * wave(t)) for t in samples])
        track("arm_right", "rotate", [(t, 15 * wave(t)) for t in samples])
        track("body", "translate", [(t, (0, 4 * (1 - math.cos(4 * math.pi * t)))) for t in samples])
    elif preset == "think":
        track("head", "rotate", [(0, 0), (0.25, 10), (0.7, 10), (1, 0)])
        angle = -15 if "forearm" in roles else -60
        track("arm", "rotate", [(0, 0), (0.25, angle), (0.7, angle), (1, 0)])
        track("forearm", "rotate", [(0, 0), (0.25, -140), (0.7, -140), (1, 0)])
        track("hand", "rotate", [(0, 0), (0.25, -35), (0.7, -35), (1, 0)])
    elif preset == "hit":
        track("body", "rotate", [(0, 0), (0.15, -14), (0.35, -8), (0.65, 3), (1, 0)])
        track(
            "body",
            "translate",
            [(0, (0, 0)), (0.15, (-16, -4)), (0.35, (-12, -3)), (0.7, (2, 0)), (1, (0, 0))],
        )
        track("body", "scale", [(0, (1, 1)), (0.15, (1.08, 0.92)), (0.6, (0.98, 1.02)), (1, (1, 1))])
    elif preset == "clap":
        track("arm_left", "rotate", [(0, 0), (0.2, 52), (0.35, 25), (0.5, 52), (0.65, 25), (0.8, 52), (1, 0)])
        track(
            "arm_right",
            "rotate",
            [(0, 0), (0.2, -52), (0.35, -25), (0.5, -52), (0.65, -25), (0.8, -52), (1, 0)],
        )
    elif preset == "cast":
        track("body", "rotate", [(0, 0), (0.3, -6), (0.5, 5), (0.8, 3), (1, 0)])
        track("arm", "rotate", [(0, 0), (0.3, 155), (0.5, 85), (0.75, 90), (1, 0)])
        track("hand", "rotate", [(0, 0), (0.3, 25), (0.5, -25), (0.75, 0), (1, 0)])
    elif preset == "slash":
        track("body", "rotate", [(0, 0), (0.3, 12), (0.45, -16), (0.65, -10), (1, 0)])
        track("arm", "rotate", [(0, 0), (0.3, 160), (0.45, 25), (0.65, 20), (1, 0)])
    elif preset == "shoot":
        track("arm", "rotate", [(0, 0), (0.3, 90), (0.48, 90), (0.52, 102), (0.7, 90), (1, 0)])
        track("arm", "translate", [(0, (0, 0)), (0.48, (0, 0)), (0.52, (-8, 0)), (0.7, (0, 0)), (1, (0, 0))])
    return result


def with_animation(data: dict, name: str, animation: dict, overwrite: bool) -> dict:
    if not name or len(name) > 128 or any(ord(c) < 32 for c in name):
        raise MotionError("Animation name must be 1–128 printable characters.")
    result = copy.deepcopy(data)
    animations = result.setdefault("animations", {})
    if name in animations and not overwrite:
        raise MotionError(
            f"Animation '{name}' already exists. Choose another name or explicitly set overwrite=true."
        )
    animations[name] = animation
    return result
