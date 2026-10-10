"""Opt-in source, rig and camera locks for identity-preserving animation."""

import copy
import hashlib

from .storage import MotionError, inside


def lock_fidelity(data, project, bounds, expression_bones=(), movable_bones=(), effect_bones=()):
    names = {b["name"] for b in data["bones"]}
    if not set(expression_bones) | set(movable_bones) | set(effect_bones) <= names:
        raise MotionError("Fidelity lock references unknown bones.")
    from .software_renderer import SoftwareRenderer

    SoftwareRenderer.camera(bounds, 320)
    result = copy.deepcopy(data)
    assets = {}
    for skin in data["skins"]:
        for choices in skin["attachments"].values():
            for name, attachment in choices.items():
                path = attachment.get("path", name) + ".png"
                assets[path] = hashlib.sha256(inside(project / "images", path).read_bytes()).hexdigest()
    result["fidelity"] = dict(
        bounds=list(bounds),
        bones=copy.deepcopy(data["bones"]),
        skins=copy.deepcopy(data["skins"]),
        assets=assets,
        expression_bones=list(expression_bones),
        movable_bones=list(movable_bones),
        effect_bones=list(effect_bones),
    )
    for animation in result.get("animations", {}).values():
        validate_fidelity(result, project, animation)
    return result


def validate_fidelity(data, project, animation, bounds=None):
    lock = data.get("fidelity")
    if not lock:
        return
    if data["bones"] != lock["bones"] or data["skins"] != lock["skins"]:
        raise MotionError("Fidelity lock: setup proportions or attachment mapping changed.")
    if bounds is not None and list(bounds) != lock["bounds"]:
        raise MotionError("Fidelity lock: all actions must use the same camera bounds.")
    for path, expected in lock["assets"].items():
        if hashlib.sha256(inside(project / "images", path).read_bytes()).hexdigest() != expected:
            raise MotionError("Fidelity lock: source artwork changed: " + path)
    for bone, channels in animation.get("bones", {}).items():
        if bone in lock["effect_bones"]:
            continue
        if channels.get("shear"):
            raise MotionError("Fidelity lock: character shear is forbidden.")
        if bone not in lock["expression_bones"]:
            for key in channels.get("scale", []):
                if key.get("x", 1) != 1 or key.get("y", 1) != 1:
                    raise MotionError("Fidelity lock: character scaling is forbidden: " + bone)
        if bone not in lock["movable_bones"]:
            if any(k.get("x", 0) != 0 or k.get("y", 0) != 0 for k in channels.get("translate", [])):
                raise MotionError("Fidelity lock: joint offsets / limb lengths cannot change: " + bone)
    if animation.get("deform"):
        raise MotionError("Fidelity lock: free vertex deformation is forbidden.")
