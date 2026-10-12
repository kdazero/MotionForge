"""Local character storage and revision management; no desktop integration."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import shutil
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .demo import make_demo
from .fidelity import validate_fidelity
from .mesh import MeshSpec, bind_region
from .motion import Bone, Layer, duration, preset_animation, validate_skeleton, with_animation
from .software_renderer import supported
from .storage import MotionError, Settings, identifier, inside, portable_path, read_json, write_json


def preview_issues(data, animation):
    try:
        supported(data, animation)
    except MotionError as exc:
        return [str(exc)]
    return []


def now():
    return datetime.now(timezone.utc).isoformat()


def ticket():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]


def checked_image(path: Path) -> tuple[int, int]:
    if path.stat().st_size > 16_000_000:
        raise MotionError("Image exceeds 16 MB.")
    try:
        with Image.open(path) as img:
            if img.format != "PNG":
                raise MotionError("Use a PNG image. upload_asset converts JPEG/WebP to PNG.")
            if img.width * img.height > 16_000_000 or max(img.size) > 8192:
                raise MotionError("Image exceeds 16 megapixels / 8192 pixels per side.")
            img.verify()
            return img.size
    except (OSError, Image.DecompressionBombError) as exc:
        raise MotionError("Invalid or oversized image.") from exc


class MotionService:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.ensure_dirs()
        self.thread_lock = threading.RLock()

    @contextmanager
    def lock(self):
        """Serialize read/modify/write across HTTP and separate stdio processes."""
        with self.thread_lock:
            path = self.settings.workspace / ".authoring.lock"
            with path.open("a+b") as handle:
                handle.seek(0, 2)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise MotionError("Another MotionForge job is writing. Retry when it finishes.") from exc
                try:
                    yield
                finally:
                    handle.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle, fcntl.LOCK_UN)

    def relative(self, path: Path) -> str:
        return path.relative_to(self.settings.workspace).as_posix()

    def _load(self, project_id):
        folder = self.settings.project_dir(project_id)
        manifest = read_json(folder / "project.json")
        data = read_json(inside(folder, manifest["active"]))
        return folder, manifest, data

    def _guard_lock(self, folder, manifest, data, relock):
        """Every revision of a locked character must keep the lock and satisfy it."""
        if "active" in manifest:
            previous = read_json(inside(folder, manifest["active"])).get("fidelity")
            if previous and not relock and data.get("fidelity") != previous:
                raise MotionError(
                    "Character is identity-locked; the lock cannot be removed or edited here. "
                    "Call lock_identity again to re-lock deliberately."
                )
        if data.get("fidelity"):
            try:
                validate_fidelity(data, folder, {})
                for animation in data.get("animations", {}).values():
                    validate_fidelity(data, folder, animation)
            except MotionError as exc:
                raise MotionError(
                    f"{exc} Make setup/artwork changes before lock_identity, or call lock_identity again."
                ) from exc

    def _commit(self, folder, manifest, data, reason, relock=False):
        validate_skeleton(data)
        self._guard_lock(folder, manifest, data, relock)
        revision = f"revisions/{ticket()}.json"
        write_json(folder / revision, data)
        manifest = copy.deepcopy(manifest)
        manifest["active"] = revision
        manifest["updated_at"] = now()
        manifest.setdefault("history", []).append({"file": revision, "reason": reason, "at": now()})
        write_json(folder / "project.json", manifest)
        return self._summary(folder, manifest, data)

    def _summary(self, folder, manifest, data):
        result = validate_skeleton(data)
        result.update(
            {
                "project_id": folder.name,
                "roles": manifest.get("roles", {}),
                "revision": manifest["active"],
                "json_path": str(folder / manifest["active"]),
                "animation_details": [
                    {
                        "name": name,
                        "duration": duration(animation),
                        "preview_issues": preview_issues(data, animation),
                    }
                    for name, animation in data.get("animations", {}).items()
                ],
            }
        )
        return result

    def list_assets(self):
        files = []
        for p in sorted((self.settings.workspace / "inbox").rglob("*")):
            if (
                p.is_file()
                and p.suffix.lower() in (".png", ".json")
                and p.resolve().is_relative_to(self.settings.workspace.resolve())
            ):
                files.append({"path": self.relative(p), "bytes": p.stat().st_size})
            if len(files) >= 500:
                break
        return files

    def upload(self, filename: str, content: bytes) -> dict:
        stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(filename).stem).strip("-_")[:48] or "asset"
        try:
            identifier(stem)
        except MotionError:
            stem = "asset"
        suffix = Path(filename).suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".json") or len(content) > 16_000_000:
            raise MotionError("Upload PNG/JPEG/WebP/JSON of at most 16 MB.")
        if suffix != ".json":
            try:
                with Image.open(io.BytesIO(content)) as img:
                    if img.width * img.height > 16_000_000 or max(img.size) > 8192:
                        raise MotionError("Image exceeds 16 megapixels / 8192 pixels per side.")
                    stream = io.BytesIO()
                    img.convert("RGBA").save(stream, format="PNG")
                    content = stream.getvalue()
                    suffix = ".png"
            except (OSError, Image.DecompressionBombError) as exc:
                raise MotionError("Cannot read that image.") from exc
        else:
            try:
                data = json.loads(content.decode("utf-8-sig"))
                if not isinstance(data, dict):
                    raise ValueError()
            except (ValueError, UnicodeError) as exc:
                raise MotionError("Upload a JSON object.") from exc
        with self.lock():
            name = stem + "-" + uuid.uuid4().hex[:8] + suffix
            target = inside(self.settings.workspace, "inbox/" + name, exists=False)
            target.write_bytes(content)
        return {
            "path": self.relative(target),
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    def list_projects(self):
        return [
            {"project_id": p.parent.name, "updated_at": read_json(p).get("updated_at")}
            for p in sorted((self.settings.workspace / "projects").glob("*/project.json"))
            if not p.parent.name.startswith("_staging_")
            and p.resolve().is_relative_to(self.settings.workspace.resolve())
        ]

    def inspect(self, project_id):
        folder, manifest, data = self._load(project_id)
        result = self._summary(folder, manifest, data)
        result["bone_details"] = data["bones"]
        result["slot_details"] = data.get("slots", [])
        result["history"] = manifest.get("history", [])[-20:]
        result["face"] = manifest.get("face")
        return result

    def _create_rig(self, project_id: str, bones: list[Bone], layers: list[Layer], roles: dict | None = None):
        folder = self.settings.project_dir(project_id, exists=False)
        if folder.exists():
            raise MotionError("Project already exists. Use a new project_id.")
        if not 1 <= len(layers) <= 64 or not 1 <= len(bones) <= 128:
            raise MotionError("Use 1–64 layers and 1–128 bones.")
        if len({layer.name.casefold() for layer in layers}) != len(layers):
            raise MotionError("Layer names must be unique, ignoring letter case.")
        for layer in layers:
            identifier(layer.name)
        sources = [(layer, inside(self.settings.workspace, layer.image)) for layer in layers]
        dimensions = [checked_image(src) for _, src in sources]
        data = {
            "skeleton": {"spine": self.settings.spine_version, "images": "./images/"},
            "bones": [b.model_dump(exclude_none=True) for b in bones],
            "slots": [],
            "skins": [{"name": "default", "attachments": {}}],
            "animations": {},
        }
        for (layer, src), (w, h) in zip(sources, dimensions):
            data["slots"].append({"name": layer.name, "bone": layer.bone, "attachment": layer.name})
            data["skins"][0]["attachments"][layer.name] = {
                layer.name: {
                    "type": "region",
                    "path": layer.name,
                    "width": w,
                    "height": h,
                    "x": layer.x,
                    "y": layer.y,
                    "rotation": layer.rotation,
                    "scaleX": layer.scale,
                    "scaleY": layer.scale,
                }
            }
        validate_skeleton(data)
        names = {b.name for b in bones}
        if any(v not in names for v in (roles or {}).values()):
            raise MotionError("Role mapping references a missing bone.")
        # Stage in a sibling directory, then publish only a complete project.
        stage = folder.parent / ("_staging_" + uuid.uuid4().hex)
        try:
            (stage / "images").mkdir(parents=True)
            for layer, src in sources:
                shutil.copyfile(src, stage / "images" / (layer.name + ".png"))
            manifest = {"schema": 1, "created_at": now(), "roles": roles or {}, "source": "layered PNG"}
            self._commit(stage, manifest, data, "Create rig")
            stage.rename(folder)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return self.inspect(project_id)

    def create_rig(self, project_id, bones, layers, roles=None):
        with self.lock():
            return self._create_rig(project_id, bones, layers, roles)

    def bind_mesh(self, project_id: str, mesh: MeshSpec):
        with self.lock():
            folder, manifest, data = self._load(project_id)
            result = bind_region(data, mesh)
            return self._commit(
                folder, manifest, result, f"Bind weighted mesh: {mesh.slot}/{mesh.attachment}"
            )

    def create_demo(self, project_id="demo", theme="mint"):
        with self.lock():
            if theme not in ("mint", "coral"):
                raise MotionError("Demo theme must be mint or coral.")
            bones, layers, roles = make_demo(self.settings.workspace / "inbox" / "demo-parts", theme)
            return self._create_rig(project_id, bones, layers, roles)

    def import_json(self, project_id, json_path, images_dir):
        with self.lock():
            folder = self.settings.project_dir(project_id, exists=False)
            if folder.exists():
                raise MotionError("Project already exists. Use another ID.")
            source = inside(self.settings.workspace, json_path)
            source_images = inside(self.settings.workspace, images_dir)
            if not source_images.is_dir():
                raise MotionError("images_dir must be a directory inside the workspace.")
            data = read_json(source)
            validate_skeleton(data)
            paths = set()
            for skin in data.get("skins", []):
                for attachments in skin.get("attachments", {}).values():
                    for name, att in attachments.items():
                        if att.get("type", "region") in ("region", "mesh", "linkedmesh"):
                            paths.add(att.get("path", name))
            if len({name.casefold() for name in paths}) != len(paths):
                raise MotionError("Image paths must be unique ignoring letter case (Windows/macOS).")
            images = []
            for name in paths:
                portable_path(name)
                path = inside(source_images, name + ".png")
                checked_image(path)
                images.append((path, name + ".png"))
            stage = folder.parent / ("_staging_" + uuid.uuid4().hex)
            try:
                (stage / "images").mkdir(parents=True)
                for src, name in images:
                    target = inside(stage / "images", name, exists=False)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, target)
                data.setdefault("skeleton", {})["images"] = "./images/"
                self._commit(
                    stage,
                    {"schema": 1, "created_at": now(), "roles": {}, "source": self.relative(source)},
                    data,
                    "Import Spine JSON (original preserved)",
                )
                stage.rename(folder)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
            return self.inspect(project_id)

    def map_roles(self, project_id, roles):
        with self.lock():
            folder, manifest, data = self._load(project_id)
            names = {b["name"] for b in data["bones"]}
            if any(name not in names for name in roles.values()):
                raise MotionError("Role mapping references a missing bone.")
            manifest["roles"] = roles
            return self._commit(folder, manifest, data, "Update semantic bone roles")

    def add_preset(self, project_id, preset, name=None, seconds=None, strength=1.0, overwrite=False):
        identifier(name or preset)
        with self.lock():
            folder, manifest, data = self._load(project_id)
            animation = preset_animation(data, preset, manifest.get("roles", {}), seconds, strength)
            data = with_animation(data, name or preset, animation, overwrite)
            result = self._commit(folder, manifest, data, f"Add preset: {name or preset}")
            if preset == "talk":
                result["warning"] = "Body motion only; add mouth attachments and timelines separately."
            return result
