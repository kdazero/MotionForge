"""Versioned, offline motion recipes with their exact rig and hand artwork."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import uuid
from pathlib import Path

from .fidelity import validate_fidelity
from .software_renderer import SoftwareRenderer, timeline
from .storage import MotionError, identifier, inside, read_json, write_json

RECIPE_ROOT = Path(__file__).with_name("recipes")
CATALOG = {"female_gestures_v1": "wave V3.9 + think V3.6; original hand variants included"}


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def rig_content(data):
    # Slot order and weighted-mesh bone indices are part of the contract.
    value = {key: data.get(key) for key in ("bones", "slots", "skins", "ik", "transform", "path")}
    if "layerConstraints" in data:
        value["layerConstraints"] = data["layerConstraints"]
    return value


def load_recipe(recipe_id):
    if recipe_id not in CATALOG:
        raise MotionError("Unknown recipe. Call list_motion_recipes first.")
    folder = inside(RECIPE_ROOT, recipe_id)
    manifest = read_json(folder / "manifest.json")
    for name, expected in manifest["files"].items():
        path = inside(folder, name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise MotionError(f"Recipe file changed: {name}. Reinstall the original recipe package.")
    data = read_json(folder / "character.json")
    if fingerprint(rig_content(data)) != manifest["rig_sha256"]:
        raise MotionError("Recipe rig checksum mismatch.")
    for name, spec in manifest["actions"].items():
        if fingerprint(data["animations"][name]) != spec["animation_sha256"]:
            raise MotionError(f"Recipe animation checksum mismatch: {name}.")
    return folder, manifest, data


def list_recipes():
    return [dict(recipe_id=name, description=description) for name, description in CATALOG.items()]


def get_recipe(recipe_id, include_animation_data=False):
    folder, manifest, data = load_recipe(recipe_id)
    result = copy.deepcopy(manifest)
    result["guide"] = (folder / "guide.md").read_text(encoding="utf-8")
    result["reproduction_scope"] = (
        "Exact packaged rig, parts and timelines. New characters need their own clean hand poses and joint "
        "calibration using this guide; matching bone names alone is insufficient. Rendering is not Spine "
        "pixel equivalence, and new renders are not automatically visually approved."
    )
    result["new_character_assembly"] = {
        "clothing": "extract_part.required_polygons must cover the full garment, including edges exposed by arm movement.",
        "hands": "register_joint_attachment measures wrist edges and can match opaque skin samples; disconnected fragments are rejected.",
        "elbows": "bind_joint_strip uses one continuous skin texture across a bare elbow; inspect the maximum bend to select blend_width.",
        "occlusion": "set_layer_constraints applies [behind, in_front] rules after drawOrder keys; place the thinking hand above the face.",
        "review": "Inspect all rendered frames. Geometry checks and calibrated landmarks do not certify anatomy or unseen source art.",
    }
    if include_animation_data:
        result["character"] = data
    return result


def _compatibility(folder, data, manifest, reference):
    problems = []
    if fingerprint(rig_content(data)) != manifest["rig_sha256"]:
        problems.append("Rig, mesh registration or slot order differs from the reference.")
    for name, expected in manifest["files"].items():
        if not name.startswith("images/"):
            continue
        path = inside(folder, name, exists=False)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            problems.append("Missing or changed character part: " + name)
    return dict(
        compatible=not problems,
        problems=problems,
        exact_actions={
            name: data.get("animations", {}).get(name) == animation
            for name, animation in reference["animations"].items()
        },
        visual_review_passed=False,
        note="Compatibility and exact timeline checks are not visual approval.",
    )


def verify_recipe(ai, project_id, recipe_id):
    _, manifest, reference = load_recipe(recipe_id)
    with ai.service.lock():
        folder, project, data = ai.service._load(project_id)
        return dict(
            project_id=project_id,
            revision=project["active"],
            recipe_id=recipe_id,
            **_compatibility(folder, data, manifest, reference),
        )


def instantiate_recipe(ai, recipe_id, project_id):
    identifier(project_id)
    source, manifest, data = load_recipe(recipe_id)
    target = inside(ai.workspace / "projects", project_id, exists=False)
    if target.exists():
        raise MotionError("Project already exists. Choose a new ID to preserve earlier work.")
    # Staged under the caller's workspace; no paths from the author's computer.
    stage = ai.workspace / "inbox" / ("recipe-" + uuid.uuid4().hex)
    stage.mkdir()
    for name in manifest["files"]:
        destination = inside(stage, name, exists=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inside(source, name), destination)
    if not _compatibility(stage, data, manifest, data)["compatible"]:
        raise MotionError("Recipe copy changed. Retry from the installed package.")
    write_json(stage / "recipe-manifest.json", manifest)
    ai.service.import_json(
        project_id, ai.service.relative(stage / "character.json"), ai.service.relative(stage / "images")
    )
    ai.service.map_roles(project_id, manifest["roles"])
    result = verify_recipe(ai, project_id, recipe_id)
    result.update(
        guide_path=ai.service.relative(stage / "guide.md"),
        hand_reference_path=ai.service.relative(stage / "hand-reference.png"),
        manifest_path=ai.service.relative(stage / "recipe-manifest.json"),
        render_requests=[
            dict(
                project_id=project_id,
                animation=name,
                **manifest["render_defaults"],
                references=[
                    dict(title=r["title"], url=r["url"], notes=r["note"], interval=r["span"])
                    for r in manifest["references"]
                ],
            )
            for name in manifest["actions"]
        ],
    )
    return result


def apply_recipe(ai, project_id, recipe_id, expected_revision, actions, overwrite=False):
    """Restore exact reference tracks only after validating every rig/art prerequisite."""
    _, manifest, reference = load_recipe(recipe_id)
    if not actions or len(set(actions)) != len(actions) or set(actions) - set(manifest["actions"]):
        raise MotionError("Select unique recipe actions: wave, think.")
    with ai.service.lock():
        folder, project, data = ai.service._load(project_id)
        if project["active"] != expected_revision:
            raise MotionError("Character changed; inspect again before applying a recipe.")
        compatible = _compatibility(folder, data, manifest, reference)
        if not compatible["compatible"]:
            raise MotionError(
                "Exact replay requires the packaged rig and artwork. "
                + " ".join(compatible["problems"][:3])
                + " Read get_motion_recipe for adapting another character; do not paste angles blindly."
            )
        if not overwrite and any(name in data.get("animations", {}) for name in actions):
            raise MotionError("Animation already exists. Set overwrite=true to restore it as a new revision.")
        updated = copy.deepcopy(data)
        for name in actions:
            animation = copy.deepcopy(reference["animations"][name])
            updated.setdefault("animations", {})[name] = animation
            validate_fidelity(updated, folder, animation)
            SoftwareRenderer(updated, folder, name).bounds(timeline(animation, 30))
        result = ai.service._commit(folder, project, updated, f"Apply frozen recipe {recipe_id}: {actions}")
        result.update(recipe_id=recipe_id, actions=actions, visual_review_passed=False)
        return result
