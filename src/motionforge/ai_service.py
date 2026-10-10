"""Revisioned, headless animation production and evidence for AI clients."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw
from pydantic import Field

from .fidelity import lock_fidelity, validate_fidelity
from .gif_export import transparent_gif
from .joints import attachments, joint_strip, ordered_slots, register_joint
from .motion import Model, duration, with_animation
from .render import point
from .service import MotionService, checked_image
from .software_renderer import SoftwareRenderer, timeline
from .storage import MotionError, Settings, identifier, inside, read_json, write_json


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RenderSpec(Model):
    project_id: str
    animation: str
    fps: int = Field(24, ge=1, le=60)
    size: int = Field(512, ge=128, le=2048)
    supersample: int = Field(2, ge=1, le=2)
    skin: str = "default"
    bounds: tuple[float, float, float, float] | None = None
    formats: list[Literal["webp", "apng", "gif", "spritesheet"]] = Field(default_factory=lambda: ["webp"])
    references: list[dict[str, str]] = Field(default_factory=list, max_length=20)


class VisualCheck(Model):
    frame: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    result: Literal["pass", "fail", "uncertain"]
    notes: str = Field(min_length=5, max_length=2000)


def contact_sheet(frames, labels, target, cell=256):
    sheet = Image.new("RGB", (cell * 4, (cell + 24) * math.ceil(len(frames) / 4)), "#344755")
    draw = ImageDraw.Draw(sheet)
    for i, (frame, label) in enumerate(zip(frames, labels)):
        scale = min(cell / frame.width, cell / frame.height)
        im = frame.resize(
            (max(1, round(frame.width * scale)), max(1, round(frame.height * scale))),
            Image.Resampling.LANCZOS,
        )
        x, y = i % 4 * cell, i // 4 * (cell + 24)
        sheet.paste(im, (x + (cell - im.width) // 2, y + 24), im)
        draw.text((x + 6, y + 5), label, fill="white")
    sheet.save(target)


class AIService:
    def __init__(self, workspace: Path):
        # Only the explicit workspace is used; no desktop editor configuration.
        self.service = MotionService(Settings(workspace.resolve()))
        self.workspace = workspace.resolve()
        self.runs = self.workspace / "ai-renders"
        self.runs.mkdir(parents=True, exist_ok=True)
        self._job_lock = threading.Lock()
        self._active = None

    def inspect(self, project_id):
        folder, manifest, data = self.service._load(project_id)
        return dict(
            project_id=project_id,
            revision=manifest["active"],
            roles=manifest.get("roles", {}),
            data=data,
            images_dir=self.service.relative(folder / "images"),
            actions={name: duration(a) for name, a in data.get("animations", {}).items()},
        )

    def put_animation(self, project_id, name, animation, overwrite=False):
        identifier(name)
        with self.service.lock():
            folder, manifest, data = self.service._load(project_id)
            updated = with_animation(data, name, animation, overwrite)
            validate_fidelity(updated, folder, animation)
            renderer = SoftwareRenderer(updated, folder, name)
            times = timeline(animation, 30)
            renderer.bounds(times)  # Validates deform data before creating a revision.
            return self.service._commit(folder, manifest, updated, f"AI author animation: {name}")

    def lock_identity(self, project_id, bounds, expression_bones=(), movable_bones=(), effect_bones=()):
        with self.service.lock():
            folder, manifest, data = self.service._load(project_id)
            data = lock_fidelity(data, folder, bounds, expression_bones, movable_bones, effect_bones)
            return self.service._commit(folder, manifest, data, "Lock source artwork, proportions and camera")

    def retime(self, project_id, animation, speed, name=None):
        if not math.isfinite(speed) or not 0.1 <= speed <= 10:
            raise MotionError("Speed multiplier must be 0.1..10; 1.5 means faster.")
        with self.service.lock():
            folder, manifest, data = self.service._load(project_id)
            if animation not in data["animations"]:
                raise MotionError("Unknown animation.")
            value = copy.deepcopy(data["animations"][animation])

            def visit(node):
                if isinstance(node, dict):
                    if "time" in node:
                        node["time"] /= speed
                    for child in node.values():
                        visit(child)
                elif isinstance(node, list):
                    for child in node:
                        visit(child)

            visit(value)
            target = name or animation
            identifier(target)
            if target != animation and target in data["animations"]:
                raise MotionError("Target animation already exists.")
            updated = with_animation(data, target, value, target == animation)
            SoftwareRenderer(updated, folder, target)
            timeline(value, 30)
            result = self.service._commit(folder, manifest, updated, f"Retime {animation} by {speed}x")
            result.update(animation=target, seconds=duration(value), speed=speed)
            return result

    def register_attachment(self, project_id, slot, name, image_path, x=0.0, y=0.0, scale=1.0):
        identifier(name)
        if not all(math.isfinite(v) for v in (x, y, scale)) or not 0 < scale <= 10:
            raise MotionError("Use finite coordinates and scale within (0,10].")
        with self.service.lock():
            folder, manifest, data = self.service._load(project_id)
            if slot not in {s["name"] for s in data["slots"]}:
                raise MotionError("Unknown slot; use inspect_character first.")
            skin = next(s for s in data["skins"] if s["name"] == "default")
            choices = skin["attachments"].setdefault(slot, {})
            if name in choices:
                raise MotionError("Attachment already exists; use a new name to retain old revisions.")
            source = inside(self.workspace, image_path)
            width, height = checked_image(source)
            file_id = "ai_" + uuid.uuid4().hex
            destination = folder / "images" / (file_id + ".png")
            shutil.copyfile(source, destination)
            choices[name] = dict(
                type="region", path=file_id, x=x, y=y, width=width, height=height, scaleX=scale, scaleY=scale
            )
            return self.service._commit(
                folder, manifest, data, f"Register independent attachment {slot}/{name}"
            )

    def register_joint_attachment(self, project_id, slot, name, image_path, registration):
        identifier(name)
        with self.service.lock():
            folder, manifest, data = self.service._load(project_id)
            choices = attachments(data, slot)
            if name in choices:
                raise MotionError("Attachment already exists; choose a new name.")
            source = inside(self.workspace, image_path)
            width, height = checked_image(source)
            with Image.open(source) as im:
                image = im.convert("RGBA")
            reference = None
            if registration.reference_slot:
                reference_att = attachments(data, registration.reference_slot).get(
                    registration.reference_attachment
                )
                if not reference_att:
                    raise MotionError("Unknown color reference attachment.")
                reference_slot = next(s for s in data["slots"] if s["name"] == registration.reference_slot)
                if any(
                    value.get("color", "ffffffff") != "ffffffff" for value in (reference_att, reference_slot)
                ):
                    raise MotionError(
                        "Sample an untinted reference attachment and slot for skin calibration."
                    )
                with Image.open(
                    inside(
                        folder / "images",
                        reference_att.get("path", registration.reference_attachment) + ".png",
                    )
                ) as im:
                    reference = im.convert("RGBA")
                if reference_att.get("rgbGain"):
                    raise MotionError(
                        "Sample an uncorrected reference texture, not an already tinted attachment."
                    )
            file_id = "joint_" + uuid.uuid4().hex
            region = dict(type="region", path=file_id, width=width, height=height)
            region, report = register_joint(region, image, registration, reference)
            choices[name] = region
            shutil.copyfile(source, folder / "images" / (file_id + ".png"))
            result = self.service._commit(folder, manifest, data, f"Register measured joint {slot}/{name}")
            result.update(registration=report, source_pixels_changed=False)
            return result

    def bind_joint_strip(self, project_id, spec):
        with self.service.lock():
            folder, manifest, data = self.service._load(project_id)
            updated = joint_strip(data, folder, spec)
            for name in updated.get("animations", {}):
                renderer = SoftwareRenderer(updated, folder, name)
                renderer.bounds(timeline(renderer.animation, 30))
            return self.service._commit(folder, manifest, updated, "Bind continuous joint skin")

    def set_layer_constraints(self, project_id, expected_revision, constraints):
        with self.service.lock():
            folder, manifest, data = self.service._load(project_id)
            if manifest["active"] != expected_revision:
                raise MotionError("Character changed; inspect again before changing layer rules.")
            ordered_slots(data["slots"], constraints)
            updated = copy.deepcopy(data)
            updated["layerConstraints"] = constraints
            for animation in updated.get("animations", {}).values():
                validate_fidelity(updated, folder, animation)
            return self.service._commit(folder, manifest, updated, "Set persistent occlusion constraints")

    def analyze(self, project_id, animation, fps=30, skin="default"):
        folder, manifest, data = self.service._load(project_id)
        r = SoftwareRenderer(data, folder, animation, skin)
        times = timeline(r.animation, fps)
        return dict(
            project_id=project_id,
            revision=manifest["active"],
            animation=animation,
            seconds=times[-1],
            frames=len(times),
            bounds=r.bounds(times),
            diagnostics=r.diagnostics(times),
        )

    def _folder(self, run_id):
        return inside(self.runs, identifier(run_id))

    def _progress(self, folder, **values):
        p = folder / "job.json"
        current = read_json(p) if p.exists() else {}
        current.update(values)
        write_json(p, current)

    def start(self, spec: RenderSpec):
        # Only one background renderer per process, avoiding unbounded memory queues.
        with self._job_lock:
            if self._active is not None:
                raise MotionError(f"Render {self._active} is still running; poll render_status.")
            run_id = uuid.uuid4().hex
            run = self.runs / run_id
            with self.service.lock():
                folder, manifest, data = self.service._load(spec.project_id)
                if data.get("fidelity") and spec.bounds is None:
                    spec = spec.model_copy(update={"bounds": tuple(data["fidelity"]["bounds"])})
                validate_fidelity(data, folder, data["animations"].get(spec.animation, {}), spec.bounds)
                renderer = SoftwareRenderer(data, folder, spec.animation, spec.skin)
                times = timeline(renderer.animation, spec.fps)
                if len(times) > 1201 or len(times) * spec.size**2 > 160_000_000:
                    raise MotionError("Render exceeds 160 megapixels; reduce FPS/size or split the action.")
                if spec.bounds is not None:
                    renderer.camera(spec.bounds, spec.size)
                # Preserve every skin referenced by the source, not just the rendered skin.
                image_paths = {
                    inside(folder / "images", attachment.get("path", name) + ".png")
                    for skin in data["skins"]
                    for choices in skin.get("attachments", {}).values()
                    for name, attachment in choices.items()
                }
                (run / "source" / "images").mkdir(parents=True)
                snapshot = copy.deepcopy(data)
                snapshot["skeleton"]["images"] = "./images/"
                write_json(run / "source" / "character.json", snapshot)
                for p in image_paths:
                    destination = run / "source" / "images" / p.relative_to(folder / "images")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(p, destination)
            self._progress(
                run,
                run_id=run_id,
                status="queued",
                completed_frames=0,
                project_id=spec.project_id,
                revision=manifest["active"],
                spec=spec.model_dump(),
                owner_pid=os.getpid(),
                renderer=SoftwareRenderer.name,
            )
            self._active = run_id
            threading.Thread(target=self._worker, args=(run_id, spec), daemon=True).start()
            return self.status(run_id)

    def _worker(self, run_id, spec):
        run = self._folder(run_id)
        try:
            data = read_json(run / "source" / "character.json")
            r = SoftwareRenderer(data, run / "source", spec.animation, spec.skin)
            times = timeline(r.animation, spec.fps)
            bounds = list(spec.bounds) if spec.bounds is not None else r.bounds(times)
            camera = r.camera(bounds, spec.size)
            self._progress(run, status="rendering", total_frames=len(times))
            frames_dir = run / "frames"
            frames_dir.mkdir()
            frames, records = [], []
            for i, t in enumerate(times):
                frame = r.frame(t, spec.size, camera, spec.supersample)
                path = frames_dir / f"{i:04}.png"
                frame.save(path)
                frames.append(frame)
                records.append(dict(frame=i, time=t, path=f"frames/{i:04}.png", sha256=digest(path)))
                self._progress(run, completed_frames=i + 1)
            # Last PNG is the exact endpoint for inspection. Encoded loops exclude it.
            milliseconds = [round(times[i + 1] * 1000) - round(t * 1000) for i, t in enumerate(times[:-1])]
            loop_frames = frames[:-1]
            artifacts = []
            if "webp" in spec.formats:
                loop_frames[0].save(
                    run / "animation.webp",
                    save_all=True,
                    append_images=loop_frames[1:],
                    duration=milliseconds,
                    loop=0,
                    lossless=True,
                    exact=True,
                )
                artifacts.append("animation.webp")
            if "apng" in spec.formats:
                loop_frames[0].save(
                    run / "animation.png",
                    save_all=True,
                    append_images=loop_frames[1:],
                    duration=milliseconds,
                    loop=0,
                    disposal=0,
                    blend=0,
                )
                artifacts.append("animation.png")
            if "gif" in spec.formats:
                ticks = [
                    max(10, (round(times[i + 1] * 100) - round(t * 100)) * 10)
                    for i, t in enumerate(times[:-1])
                ]
                transparent_gif(loop_frames, ticks, run / "animation.gif")
                artifacts.append("animation.gif")
            if "spritesheet" in spec.formats:
                cols = max(1, 2048 // spec.size)
                capacity = cols * cols
                sprites = []
                for start in range(0, len(loop_frames), capacity):
                    selected = loop_frames[start : start + capacity]
                    sheet = Image.new("RGBA", (cols * spec.size, math.ceil(len(selected) / cols) * spec.size))
                    name = f"sprites-{start // capacity:03}.png"
                    for i, im in enumerate(selected):
                        x, y = i % cols * spec.size, i // cols * spec.size
                        sheet.paste(im, (x, y))
                        sprites.append(
                            dict(
                                frame=start + i,
                                sheet=name,
                                rect=[x, y, spec.size, spec.size],
                                duration_ms=milliseconds[start + i],
                            )
                        )
                    sheet.save(run / name)
                    artifacts.append(name)
                write_json(run / "sprites.json", dict(frames=sprites, pivot=list(point(camera, 0, 0))))
                artifacts.append("sprites.json")
            selected = sorted({round(i * (len(frames) - 1) / 11) for i in range(12)})
            contact_sheet(
                [frames[i] for i in selected],
                [f"frame {i} / {times[i]:.3f}s" for i in selected],
                run / "contact-sheet.png",
            )
            frames[len(frames) // 2].save(run / "poster.png")
            diagnostics = r.diagnostics(times)
            write_json(run / "diagnostics.json", diagnostics)
            sources = {
                p.relative_to(run).as_posix(): digest(p) for p in (run / "source").rglob("*") if p.is_file()
            }
            job = read_json(run / "job.json")
            report = dict(
                schema=1,
                run_id=run_id,
                renderer=r.name,
                project_id=spec.project_id,
                revision=job["revision"],
                animation=spec.animation,
                seconds=times[-1],
                fps=spec.fps,
                size=spec.size,
                bounds=bounds,
                camera=list(camera),
                root_pixel=list(point(camera, 0, 0)),
                frames=records,
                endpoint_included=True,
                loop_frame_count=len(loop_frames),
                artifacts=artifacts + ["poster.png", "contact-sheet.png", "diagnostics.json"],
                source_hashes=sources,
                artifact_hashes={
                    name: digest(run / name)
                    for name in artifacts + ["poster.png", "contact-sheet.png", "diagnostics.json"]
                },
                references=spec.references,
                inspected=[],
                checks={},
                diagnostic_candidates=diagnostics["candidate_count"],
                visual_review_passed=False,
                requires_spine=False,
                note="Independent raster animation. No claim of Spine-runtime compatibility. GIF has binary transparency; PNG/WebP/APNG preserve full alpha.",
            )
            write_json(run / "render.json", report)
            self._progress(run, status="complete", report=self.service.relative(run / "render.json"))
        except Exception as exc:
            self._progress(run, status="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            with self._job_lock:
                self._active = None

    def status(self, run_id):
        folder = self._folder(run_id)
        job = read_json(folder / "job.json")
        if job["status"] in ("queued", "rendering") and job["owner_pid"] != os.getpid():
            # Another live MCP process may still own the job. Do not mislabel it failed.
            job["owner_note"] = "Owned by another process; if its MCP session ended, restart this render."
        if job["status"] == "complete":
            report = read_json(folder / "render.json")
            job.update(
                seconds=report["seconds"],
                frame_count=len(report["frames"]),
                artifacts={name: self.service.relative(folder / name) for name in report["artifacts"]},
                reviewed_frames=len(report["checks"]),
                visual_review_passed=report["visual_review_passed"],
                diagnostic_candidates=report["diagnostic_candidates"],
            )
        return job

    def _report(self, run_id):
        folder = self._folder(run_id)
        if read_json(folder / "job.json")["status"] != "complete":
            raise MotionError("Render is not complete. Poll render_status.")
        report = read_json(folder / "render.json")
        for path, sha in report["source_hashes"].items():
            if digest(inside(folder, path)) != sha:
                raise MotionError("Rendered source snapshot changed. Create a new render.")
        return folder, report

    def inspect_frames(self, run_id, indices, crop=None):
        if not 1 <= len(indices) <= 12 or len(set(indices)) != len(indices):
            raise MotionError("Inspect 1–12 distinct frames per call.")
        with self.service.lock():
            folder, report = self._report(run_id)
            frames, records = [], []
            for i in indices:
                if not isinstance(i, int) or not 0 <= i < len(report["frames"]):
                    raise MotionError("Frame index is out of range.")
                entry = report["frames"][i]
                path = inside(folder, entry["path"])
                if digest(path) != entry["sha256"]:
                    raise MotionError("Rendered frame changed; rerender before reviewing.")
                im = Image.open(path).convert("RGBA")
                if crop is not None:
                    x, y, w, h = crop
                    if not (0 <= x < x + w <= im.width and 0 <= y < y + h <= im.height):
                        raise MotionError("Crop must be positive and inside the frame.")
                    im = im.crop((x, y, x + w, y + h))
                frames.append(im)
                records.append({**entry, "path": self.service.relative(path)})
            evidence = folder / "inspections"
            evidence.mkdir(exist_ok=True)
            target = evidence / (uuid.uuid4().hex + ".png")
            contact_sheet(frames, [f"frame {r['frame']} / {r['time']:.3f}s" for r in records], target, 384)
            if crop is None:
                report["inspected"] = sorted(set(report["inspected"]) | set(indices))
            write_json(folder / "render.json", report)
            return dict(
                frames=records,
                sheet=self.service.relative(target),
                crop=crop,
                instruction="Examine actual pixels for seams, stretching, twisting, finger anatomy and motion. Inspection alone does not approve frames.",
            )

    def record_checks(self, run_id, checks: list[VisualCheck]):
        if not 1 <= len(checks) <= 12:
            raise MotionError("Record 1–12 explicitly viewed frames per call.")
        with self.service.lock():
            folder, report = self._report(run_id)
            for check in checks:
                if check.frame not in report["inspected"]:
                    raise MotionError("Inspect the frame before recording its assessment.")
                entry = report["frames"][check.frame]
                if check.sha256 != entry["sha256"] or digest(inside(folder, entry["path"])) != check.sha256:
                    raise MotionError("Frame hash mismatch.")
            for check in checks:
                report["checks"][str(check.frame)] = check.model_dump()
            report["visual_review_passed"] = len(report["checks"]) == len(report["frames"]) and all(
                c["result"] == "pass" for c in report["checks"].values()
            )
            write_json(folder / "render.json", report)
        return self.status(run_id)

    def export(self, run_ids, require_reviewed=True):
        if not 1 <= len(run_ids) <= 12 or len(set(run_ids)) != len(run_ids):
            raise MotionError("Select 1–12 distinct completed renders.")
        with self.service.lock():
            reports = [self._report(r) for r in run_ids]
            if len({(r["project_id"], r["revision"]) for _, r in reports}) != 1:
                raise MotionError("Package renders from one character revision.")
            if require_reviewed and not all(r["visual_review_passed"] for _, r in reports):
                raise MotionError(
                    "Some frames are unreviewed or failed. Inspect and record them, or explicitly export a draft."
                )
            folder = self.workspace / "ai-deliveries" / uuid.uuid4().hex
            folder.mkdir(parents=True)
            bundle = folder / "animation-bundle.zip"
            for run, r in reports:
                for frame in r["frames"]:
                    if digest(inside(run, frame["path"])) != frame["sha256"]:
                        raise MotionError("Frame changed after rendering.")
                for name, sha in r["artifact_hashes"].items():
                    if digest(inside(run, name)) != sha:
                        raise MotionError("Encoded artifact changed after rendering.")
            manifest = dict(
                schema=1,
                renderer=SoftwareRenderer.name,
                requires_spine=False,
                project_id=reports[0][1]["project_id"],
                revision=reports[0][1]["revision"],
                visual_review_passed=all(r["visual_review_passed"] for _, r in reports),
                animations=[
                    dict(
                        name=r["animation"],
                        run_id=r["run_id"],
                        seconds=r["seconds"],
                        fps=r["fps"],
                        frames=len(r["frames"]),
                        root_pixel=r["root_pixel"],
                    )
                    for _, r in reports
                ],
            )
            with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                first = reports[0][0]
                for p in (first / "source").rglob("*"):
                    if p.is_file():
                        z.write(p, p.relative_to(first).as_posix())
                for run, r in reports:
                    for p in run.rglob("*"):
                        if p.is_file() and p.parts[len(run.parts)] not in ("source", "inspections"):
                            z.write(p, "animations/" + r["run_id"] + "/" + p.relative_to(run).as_posix())
            manifest.update(bundle=self.service.relative(bundle), sha256=digest(bundle))
            write_json(folder / "manifest.json", manifest)
            return manifest
