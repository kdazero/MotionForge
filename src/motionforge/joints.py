"""Reusable joint registration, continuous skin binding and explicit occlusion rules.

These operations use measured artwork landmarks. They do not infer anatomy from
an arbitrary picture, and do not repaint source PNGs.
"""

from __future__ import annotations

import copy
import math

import cv2
import numpy as np
from PIL import Image
from pydantic import Field, model_validator

from .mesh import MeshSpec, MeshVertex, bind_region
from .motion import Model
from .render import multiply, point, transform, worlds
from .storage import MotionError, inside


class JointRegistration(Model):
    source_edges: tuple[tuple[float, float], tuple[float, float]]
    target_edges: tuple[tuple[float, float], tuple[float, float]]
    # Source pixels are top-left/Y-down; target coordinates are slot-local/Y-up.
    source_sample: tuple[int, int, int, int] | None = None
    reference_slot: str | None = None
    reference_attachment: str | None = None
    reference_sample: tuple[int, int, int, int] | None = None
    root_fade: float = Field(default=0, ge=0, le=128)
    tip: tuple[float, float] | None = None

    @model_validator(mode="after")
    def landmarks(self):
        if not all(math.isfinite(v) for pair in (*self.source_edges, *self.target_edges) for v in pair):
            raise ValueError("Joint landmarks must be finite.")
        if any(math.dist(*edges) < 1 for edges in (self.source_edges, self.target_edges)):
            raise ValueError("Use two distinct edges across the joint, at least one pixel apart.")
        samples = (self.source_sample, self.reference_slot, self.reference_attachment, self.reference_sample)
        if any(v is not None for v in samples) and not all(v is not None for v in samples):
            raise ValueError(
                "Color matching requires source and reference sample rectangles and an attachment."
            )
        if self.root_fade and self.tip is None:
            raise ValueError("Root feathering requires a tip landmark pointing into the hand.")
        return self


def attachments(data, slot, skin="default"):
    try:
        return next(s for s in data["skins"] if s["name"] == skin)["attachments"][slot]
    except (StopIteration, KeyError) as exc:
        raise MotionError("Unknown skin or attachment slot.") from exc


def sample_rgb(image, box):
    x, y, w, h = box
    if min(w, h) <= 0 or x < 0 or y < 0 or x + w > image.width or y + h > image.height:
        raise MotionError("Color sample rectangle must be inside the texture.")
    pixels = np.asarray(image.convert("RGBA"))[y : y + h, x : x + w]
    valid = pixels[:, :, 3] >= 245
    rgb = pixels[:, :, :3][valid]
    if len(rgb) < 9:
        raise MotionError(
            "Sample at least nine opaque skin pixels, away from outlines and transparent edges."
        )
    value = np.median(rgb, axis=0)
    if value.min() < 32:
        raise MotionError("Color sample is too dark; select skin, not ink or background.")
    return value


def register_joint(region, image, spec, reference_image=None):
    """Compute a similarity transform from wrist edges; image padding is irrelevant."""
    width, height = image.size
    alpha = np.asarray(image.convert("RGBA"))[:, :, 3]
    _, _, components, _ = cv2.connectedComponentsWithStats((alpha >= 32).astype(np.uint8))
    areas = components[1:, cv2.CC_STAT_AREA]
    if sum(area >= 4 for area in areas) != 1:
        raise MotionError(
            "Joint artwork must contain one connected opaque part; remove detached clothing/background fragments before registration."
        )
    if any(not (0 <= x < width and 0 <= y < height) for x, y in spec.source_edges):
        raise MotionError("Source landmarks must lie inside the attachment image.")
    src = np.asarray([(x, -y) for x, y in spec.source_edges], dtype=float)
    dst = np.asarray(spec.target_edges, dtype=float)
    sv, dv = src[1] - src[0], dst[1] - dst[0]
    scale = float(np.linalg.norm(dv) / np.linalg.norm(sv))
    if not 0.01 <= scale <= 10:
        raise MotionError("Joint registration scale is outside 0.01..10.")
    angle = math.degrees(math.atan2(dv[1], dv[0]) - math.atan2(sv[1], sv[0]))
    matrix = transform(0, 0, angle, scale, scale)
    center = np.array([width / 2, -height / 2]) - src.mean(axis=0)
    x, y = np.array(point(matrix, *center)) + dst.mean(axis=0)
    result = copy.deepcopy(region)
    result.update(x=float(x), y=float(y), rotation=angle, scaleX=scale, scaleY=scale)
    report = dict(scale=scale, rotation=angle, anchor_error=0.0, color_matched=False)
    if spec.source_sample:
        source_rgb = sample_rgb(image, spec.source_sample)
        target_rgb = sample_rgb(reference_image, spec.reference_sample)
        gains = target_rgb / source_rgb
        if (gains < 0.65).any() or (gains > 1.5).any():
            raise MotionError(
                "Colors differ too much for a reliable joint correction; supply matching artwork."
            )
        result["rgbGain"] = gains.tolist()
        report.update(
            color_matched=True,
            source_rgb=source_rgb.tolist(),
            target_rgb=target_rgb.tolist(),
            rgb_gain=gains.tolist(),
            median_error_before=float(np.linalg.norm(target_rgb - source_rgb)),
        )
    if spec.root_fade:
        root = np.mean(spec.source_edges, axis=0)
        direction = np.asarray(spec.tip) - root
        length = np.linalg.norm(direction)
        if not math.isfinite(length) or length < 1:
            raise MotionError("Tip landmark must be distinct from the joint root.")
        result["rootFade"] = dict(
            origin=root.tolist(), direction=(direction / length).tolist(), width=spec.root_fade
        )
    result["jointRegistration"] = dict(
        source_edges=spec.source_edges,
        target_edges=spec.target_edges,
        transform=[result[k] for k in ("x", "y", "rotation", "scaleX", "scaleY")],
    )
    return result, report


def texture_effects(texture, attachment):
    """Apply non-destructive RGB calibration and root alpha in straight-alpha space."""
    gain = attachment.get("rgbGain", [1, 1, 1])
    if len(gain) != 3 or not all(math.isfinite(v) and 0.65 <= v <= 1.5 for v in gain):
        raise MotionError("rgbGain needs three finite channel gains within 0.65..1.5.")
    fade = attachment.get("rootFade")
    result = texture.copy()
    result[:, :, :3] = np.clip(result[:, :, :3] * gain, 0, 1)
    if fade:
        origin, direction, width = fade.get("origin", []), fade.get("direction", []), fade.get("width", 0)
        if (
            len(origin) != 2
            or len(direction) != 2
            or not 0 < width <= 128
            or not all(math.isfinite(v) for v in (*origin, *direction, width))
            or not math.isclose(math.hypot(*direction), 1, abs_tol=1e-5)
        ):
            raise MotionError("Invalid root feather geometry.")
        yy, xx = np.indices(result.shape[:2])
        distance = (xx + 0.5 - origin[0]) * direction[0] + (yy + 0.5 - origin[1]) * direction[1]
        alpha = np.clip((distance + width / 2) / width, 0, 1)
        result[:, :, 3] *= alpha * alpha * (3 - 2 * alpha)
    return result


def ordered_slots(slots, constraints):
    """Stable topological order; semantic front/back rules survive drawOrder keys."""
    names = [s["name"] for s in slots]
    edges = {n: set() for n in names}
    for pair in constraints:
        if len(pair) != 2 or any(n not in edges for n in pair) or pair[0] == pair[1]:
            raise MotionError("Layer constraints require two distinct existing slots: [behind, in_front].")
        edges[pair[1]].add(pair[0])
    remaining = list(slots)
    result = []
    while remaining:
        ready = next((s for s in remaining if not edges[s["name"]]), None)
        if ready is None:
            raise MotionError("Layer constraints contain a cycle.")
        result.append(ready)
        remaining.remove(ready)
        for dependencies in edges.values():
            dependencies.discard(ready["name"])
    return result


class JointStrip(Model):
    slot: str
    attachment: str
    parent_bone: str
    child_bone: str
    tip_bone: str | None = None
    start: tuple[float, float]  # Texture pixels, proximal end.
    end: tuple[float, float]  # Texture pixels, distal end.
    blend_width: float = Field(gt=0, le=500)
    rows: int = Field(default=32, ge=8, le=48)
    rigid: bool = True


def joint_strip(data, folder, spec):
    """Bind one continuous skin texture across a joint; no overlapping elbow cut edges."""
    region = attachments(data, spec.slot).get(spec.attachment)
    if not region or region.get("type", "region") != "region":
        raise MotionError("Continuous joint binding needs a region with uncut skin across the joint.")
    bones = {b["name"]: b for b in data["bones"]}
    if spec.child_bone not in bones or bones[spec.child_bone].get("parent") != spec.parent_bone:
        raise MotionError("The distal bone must be a direct child of the proximal bone.")
    tip_bone = spec.tip_bone or spec.child_bone
    ancestor = tip_bone
    visited = set()
    while ancestor != spec.child_bone:
        if ancestor not in bones or ancestor in visited:
            raise MotionError("The tip bone must descend from the distal joint bone.")
        visited.add(ancestor)
        ancestor = bones[ancestor].get("parent")
    with Image.open(inside(folder / "images", region.get("path", spec.attachment) + ".png")) as image:
        alpha = np.array(image.convert("RGBA"))[:, :, 3]
    h, w = alpha.shape
    start, end = np.asarray(spec.start), np.asarray(spec.end)
    direction = end - start
    length = np.linalg.norm(direction)
    if not np.isfinite(direction).all() or length < 1:
        raise MotionError("Use distinct finite strip endpoints in texture pixels.")
    direction = direction / length
    normal = np.array([-direction[1], direction[0]])
    yy, xx = np.where(alpha > 24)
    if len(xx) < 12:
        raise MotionError("Joint strip has insufficient visible artwork.")
    pixels = np.column_stack([xx + 0.5, yy + 0.5])
    # Convex hull sections preserve the complete silhouette, including nonvertical arms.
    hull = cv2.convexHull(pixels.astype(np.float32)).reshape(-1, 2)
    local = np.column_stack([(hull - start) @ direction, (hull - start) @ normal])
    lo, hi = local[:, 0].min(), local[:, 0].max()
    ws = worlds(data, {}, 0)
    slot = next(s for s in data["slots"] if s["name"] == spec.slot)
    matrix = multiply(
        ws[slot["bone"]],
        transform(
            region.get("x", 0),
            region.get("y", 0),
            region.get("rotation", 0),
            region.get("scaleX", 1),
            region.get("scaleY", 1),
        ),
    )

    def world(p):
        return np.array(
            point(matrix, (p[0] / w - 0.5) * region["width"], (0.5 - p[1] / h) * region["height"])
        )

    axis = world(end) - world(start)
    axis /= np.linalg.norm(axis)
    joint = np.asarray(point(ws[spec.child_bone], 0, 0))
    raw = []
    # Concentrate vertices at the hinge; avoid broadening a bend just to hide
    # the polygonal contour produced by a uniform grid on otherwise straight skin.
    world_per_pixel = np.linalg.norm(world(end) - world(start)) / length
    center = float((joint - world(start)) @ axis / world_per_pixel)
    radius = spec.blend_width / world_per_pixel * 0.7
    if not lo - 1 <= center <= hi + 1:
        raise MotionError("Joint lies outside this skin cutout; correct its registration before binding.")
    broad_rows = max(8, spec.rows // 3)
    adaptive = sorted(
        set(
            round(float(v), 6)
            for v in [
                *np.linspace(lo + 0.01, hi - 0.01, broad_rows),
                *np.linspace(
                    max(lo + 0.01, center - radius), min(hi - 0.01, center + radius), spec.rows - broad_rows
                ),
            ]
        )
    )
    # A hull corner between sampling rows must be a row itself. Otherwise the
    # mesh chords cut away real opaque pixels, especially a slanted sleeve cuff.
    # More hinge rows alone cannot fix that setup-pose loss.
    critical = sorted(set(round(float(np.clip(v, lo + 0.01, hi - 0.01)), 6) for v in local[:, 0]))
    if len(critical) > 48:
        raise MotionError("Joint silhouette has too many corners; simplify the cutout before binding.")
    distances = list(critical)
    for candidate in adaptive:
        if min(abs(candidate - v) for v in distances) > 0.001:
            distances.append(candidate)
    distances.sort()
    budget = max(spec.rows, len(critical))
    while len(distances) > budget:
        removable = [i for i, v in enumerate(distances) if v not in critical]
        index = min(
            removable,
            key=lambda i: min(distances[i] - distances[i - 1], distances[i + 1] - distances[i]),
        )
        distances.pop(index)
    for distance in distances:
        crosses = []
        for a, b in zip(local, np.roll(local, -1, axis=0)):
            if min(a[0], b[0]) <= distance <= max(a[0], b[0]) and abs(b[0] - a[0]) > 1e-8:
                crosses.append(a[1] + (b[1] - a[1]) * (distance - a[0]) / (b[0] - a[0]))
        if len(crosses) < 2:
            raise MotionError("Cannot section this silhouette; provide a clean continuous limb cutout.")
        left, right = min(crosses) - 1, max(crosses) + 1
        for k in np.linspace(left, right, 5):
            pixel = np.clip(start + direction * distance + normal * k, [0.01, 0.01], [w - 0.01, h - 0.01])
            blend = np.clip(((world(pixel) - joint) @ axis) / spec.blend_width + 0.5, 0, 1)
            blend = float(blend * blend * (3 - 2 * blend))
            weights = (
                {spec.parent_bone: 1 - blend, tip_bone: blend}
                if 0 < blend < 1
                else {tip_bone if blend else spec.parent_bone: 1}
            )
            raw.append(MeshVertex(u=float(pixel[0] / w), v=float(pixel[1] / h), weights=weights))
    nx, ny = 5, len(distances)
    boundary = list(range(nx)) + [j * nx + nx - 1 for j in range(1, ny)]
    boundary += list(range((ny - 1) * nx + nx - 2, (ny - 1) * nx - 1, -1)) + [
        j * nx for j in range(ny - 2, 0, -1)
    ]
    order = boundary + [i for i in range(len(raw)) if i not in boundary]
    remap = {old: new for new, old in enumerate(order)}
    triangles = []
    for row in range(ny - 1):
        for col in range(nx - 1):
            a = row * nx + col
            for tri in ((a, a + 1, a + nx + 1), (a, a + nx + 1, a + nx)):
                ids = [remap[i] for i in tri]
                va, vb, vc = [raw[i] for i in tri]
                if (vb.u - va.u) * (vc.v - va.v) - (vb.v - va.v) * (vc.u - va.u) < 0:
                    ids.reverse()
                triangles.append(tuple(ids))
    mesh = MeshSpec(
        slot=spec.slot,
        attachment=spec.attachment,
        vertices=[raw[i] for i in order],
        triangles=triangles,
        hull=len(boundary),
        skinning="rigid" if spec.rigid else "linear",
    )
    return bind_region(data, mesh)
