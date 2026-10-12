"""Independent CPU renderer for the supported layered-character data subset.

Uses affine bone matrices, linear skinning and barycentric texture sampling.
No Spine executable, runtime or desktop integration is used by this module.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .joints import ordered_slots, texture_effects
from .motion import duration, validate_skeleton
from .render import easing, inverse, multiply, point, sample, transform, worlds
from .rigid_skinning import rigid_blend_point
from .storage import MotionError, inside


def rgba(value="ffffffff"):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", value):
        raise MotionError("Colors must be six or eight hexadecimal digits, without #.")
    return np.array([int((value + "ff")[i : i + 2], 16) / 255 for i in (0, 2, 4, 6)])


def curve_alpha(key, alpha):
    curve = key.get("curve")
    if isinstance(curve, (int, float)):
        curve = [curve, key.get("c2", 0), key.get("c3", 1), key.get("c4", 1)]
    return easing(curve, alpha)


def keys_valid(keys):
    if not isinstance(keys, list) or len(keys) > 1201:
        raise MotionError("A timeline must contain at most 1201 keyframes.")
    previous = -1
    for key in keys:
        if not isinstance(key, dict):
            raise MotionError("Every keyframe must be a JSON object.")
        t = key.get("time", 0)
        if not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 <= t <= 20 or t <= previous:
            raise MotionError("Key times must increase strictly within 0..20 seconds.")
        previous = t
        curve = key.get("curve")
        if curve is not None and curve not in ("linear", "stepped"):
            control = (
                curve
                if isinstance(curve, list)
                else [curve, key.get("c2", 0), key.get("c3", 1), key.get("c4", 1)]
            )
            if len(control) != 4 or not all(
                isinstance(x, (float, int)) and math.isfinite(x) for x in control
            ):
                raise MotionError("Invalid cubic Bezier curve.")
            if not 0 <= control[0] <= control[2] <= 1:
                raise MotionError("Bezier time controls must be ordered within 0..1.")


def animation_shape(animation):
    if not isinstance(animation, dict):
        raise MotionError("An animation must be a JSON object of timelines.")
    for kind in ("bones", "slots", "deform"):
        value = animation.get(kind, {})
        if not isinstance(value, dict) or not all(isinstance(v, dict) for v in value.values()):
            raise MotionError(f"Animation '{kind}' must be an object keyed by name.")
    for kind in ("drawOrder", "events"):
        if not isinstance(animation.get(kind, []), list):
            raise MotionError(f"Animation '{kind}' must be a list of keys.")
    for channels in (*animation.get("bones", {}).values(), *animation.get("slots", {}).values()):
        if not all(isinstance(keys, list) for keys in channels.values()):
            raise MotionError("Every timeline channel must be a list of keys.")


def supported(data, animation):
    validate_skeleton(data)
    animation_shape(animation)
    issues = []
    if any(data.get(k) for k in ("ik", "transform", "path")):
        issues.append("IK/transform/path constraints")
    if any(b.get("transform", "normal") != "normal" or b.get("skin") for b in data["bones"]):
        issues.append("non-normal inheritance or skin-required bones")
    for s in data.get("slots", []):
        if s.get("blend", "normal") != "normal" or s.get("dark"):
            issues.append("blend modes or two-color tint")
    for skin in data.get("skins", []):
        for attachments in skin.get("attachments", {}).values():
            for a in attachments.values():
                if a.get("type", "region") not in ("region", "mesh"):
                    issues.append("linked meshes, clipping or non-image attachments")
    for kind, values in animation.items():
        if kind not in ("bones", "slots", "deform", "drawOrder", "events") and values:
            issues.append(f"{kind} timeline")
    for bone, channels in animation.get("bones", {}).items():
        if bone not in {b["name"] for b in data["bones"]}:
            raise MotionError(f"Unknown animated bone: {bone}")
        for channel, keys in channels.items():
            if channel not in ("rotate", "translate", "scale", "shear"):
                issues.append(f"bone {channel}")
            keys_valid(keys)
            for k in keys:
                for f in ("angle", "x", "y"):
                    if f in k and (not isinstance(k[f], (int, float)) or not math.isfinite(k[f])):
                        raise MotionError("Bone key values must be finite numbers.")
    slots = {s["name"] for s in data.get("slots", [])}
    for slot, channels in animation.get("slots", {}).items():
        if slot not in slots:
            raise MotionError(f"Unknown animated slot: {slot}")
        for channel, keys in channels.items():
            if channel not in ("attachment", "color"):
                issues.append(f"slot {channel}")
            keys_valid(keys)
            if channel == "color":
                for key in keys:
                    rgba(key.get("color", "ffffffff"))
    keys_valid(animation.get("drawOrder", []))
    keys_valid(animation.get("events", []))
    for skin in animation.get("deform", {}).values():
        for slot in skin.values():
            for keys in slot.values():
                keys_valid(keys)
    if issues:
        raise MotionError("Independent renderer does not support: " + ", ".join(sorted(set(issues))))


def draw_order(slots, offsets):
    names = [s["name"] for s in slots]
    order = [None] * len(names)
    moved, untouched = set(), []
    for entry in offsets:
        if entry.get("slot") not in names or not isinstance(entry.get("offset", 0), int):
            raise MotionError("Draw order needs known slots and integer offsets.")
        i = names.index(entry["slot"])
        j = i + entry.get("offset", 0)
        if i in moved or not 0 <= j < len(names) or order[j] is not None:
            raise MotionError("Draw order has duplicate or out-of-range destinations.")
        moved.add(i)
        order[j] = slots[i]
    untouched = iter(s for i, s in enumerate(slots) if i not in moved)
    return [next(untouched) if s is None else s for s in order]


def deform_at(keys, t, size):
    empty = np.zeros(size, dtype=np.float64)

    def vector(key):
        a = empty.copy()
        offset, values = key.get("offset", 0), key.get("vertices", [])
        if not isinstance(offset, int) or offset < 0 or offset + len(values) > size:
            raise MotionError("Deform offsets exceed the mesh's vertex data.")
        a[offset : offset + len(values)] = values
        if not np.isfinite(a).all():
            raise MotionError("Deform offsets must be finite.")
        return a

    if not keys or t < keys[0].get("time", 0):
        return empty
    left = keys[0]
    for right in keys[1:]:
        end, start = right.get("time", 0), left.get("time", 0)
        if t < end:
            a = curve_alpha(left, (t - start) / (end - start))
            return vector(left) * (1 - a) + vector(right) * a
        left = right
    return vector(left)


class SoftwareRenderer:
    name = "MotionForge CPU 1"

    def __init__(self, data: dict, project: Path, animation: str, skin="default"):
        if animation not in data.get("animations", {}):
            raise MotionError(f"Unknown animation: {animation}")
        self.data, self.animation, self.skin = data, data["animations"][animation], skin
        supported(data, self.animation)
        self.names = [b["name"] for b in data["bones"]]
        self.bind_matrices = worlds(data, {}, 0)
        skins = {s["name"]: s.get("attachments", {}) for s in data.get("skins", [])}
        if skin not in skins:
            raise MotionError(f"Unknown skin: {skin}")
        self.parts = {}
        self._textures = {}
        vertex_count = 0
        for slot in data.get("slots", []):
            choices = dict(skins.get("default", {}).get(slot["name"], {}))
            choices.update(skins[skin].get(slot["name"], {}))
            for name, a in choices.items():
                path = inside(project / "images", a.get("path", name) + ".png")
                if path not in self._textures:
                    with Image.open(path) as source:
                        if source.width * source.height > 16_000_000:
                            raise MotionError("Texture exceeds 16 megapixels.")
                        tex = np.asarray(source.convert("RGBA"), dtype=np.float32) / 255
                    self._textures[path] = tex
                tex = texture_effects(self._textures[path], a)
                tex[:, :, :3] *= tex[:, :, 3:4]
                h, w = tex.shape[:2]
                if a.get("type", "region") == "region":
                    aw, ah = a.get("width", w), a.get("height", h)
                    local = transform(
                        a.get("x", 0),
                        a.get("y", 0),
                        a.get("rotation", 0),
                        a.get("scaleX", 1),
                        a.get("scaleY", 1),
                    )
                    vertices = [
                        point(local, x, y)
                        for x, y in (
                            (-aw / 2, ah / 2),
                            (aw / 2, ah / 2),
                            (aw / 2, -ah / 2),
                            (-aw / 2, -ah / 2),
                        )
                    ]
                    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)
                    triangles = np.array([[0, 1, 2], [0, 2, 3]])
                    influences = [[(slot["bone"], x, y, 1)] for x, y in vertices]
                else:
                    uv = np.asarray(a.get("uvs", []), dtype=float)
                    raw, tri = a.get("vertices", []), a.get("triangles", [])
                    if (
                        uv.size < 6
                        or uv.size % 2
                        or not np.isfinite(uv).all()
                        or (uv < 0).any()
                        or (uv > 1).any()
                    ):
                        raise MotionError("Mesh UVs must be finite pairs within 0..1.")
                    uv = uv.reshape(-1, 2)
                    if (
                        not tri
                        or len(tri) % 3
                        or any(not isinstance(v, int) or not 0 <= v < len(uv) for v in tri)
                    ):
                        raise MotionError("Invalid mesh triangle indices.")
                    triangles = np.array(tri).reshape(-1, 3)
                    influences = []
                    if len(raw) == uv.size:
                        influences = [[(slot["bone"], x, y, 1)] for x, y in np.array(raw).reshape(-1, 2)]
                    else:
                        i = 0
                        for _ in uv:
                            if i >= len(raw) or not isinstance(raw[i], int) or not 1 <= raw[i] <= 16:
                                raise MotionError("Malformed mesh influence count.")
                            count = raw[i]
                            i += 1
                            group = []
                            for _ in range(count):
                                if i + 4 > len(raw):
                                    raise MotionError("Truncated weighted mesh.")
                                bone, x, y, weight = raw[i : i + 4]
                                i += 4
                                if (
                                    not isinstance(bone, int)
                                    or not 0 <= bone < len(self.names)
                                    or not 0 <= weight <= 1
                                ):
                                    raise MotionError("Invalid mesh influence.")
                                group.append((self.names[bone], x, y, weight))
                            if not math.isclose(sum(g[3] for g in group), 1, abs_tol=1e-4):
                                raise MotionError("Mesh weights must sum to one.")
                            influences.append(group)
                        if i != len(raw):
                            raise MotionError("Unused weighted mesh data.")
                vertex_count += len(uv)
                if vertex_count > 20000:
                    raise MotionError("Character exceeds 20000 attachment vertices.")
                flat = [(bone, x, y, wt) for group in influences for bone, x, y, wt in group]
                if not all(math.isfinite(v) for _, x, y, wt in flat for v in (x, y, wt)):
                    raise MotionError("Mesh positions and weights must be finite.")
                origin_skin = skin if name in skins[skin].get(slot["name"], {}) else "default"
                keys = (
                    self.animation.get("deform", {}).get(origin_skin, {}).get(slot["name"], {}).get(name, [])
                )
                part = dict(
                    rigid_skinning=a.get("skinning") == "rigid",
                    texture=tex,
                    uv=uv,
                    triangles=triangles,
                    influences=influences,
                    color=rgba(a.get("color", "ffffffff")),
                    deform=keys,
                )
                self.parts[(slot["name"], name)] = part
        for skin_name, slots in self.animation.get("deform", {}).items():
            if skin_name not in skins:
                raise MotionError("Deform references an unknown skin.")
            for slot, attachments in slots.items():
                for name in attachments:
                    if name not in skins[skin_name].get(slot, {}):
                        raise MotionError("Deform references an unknown attachment.")
        # Check every key's attachment and drawing order, including short-lived poses.
        for slot, tracks in self.animation.get("slots", {}).items():
            for k in tracks.get("attachment", []):
                if k.get("name") is not None and (slot, k["name"]) not in self.parts:
                    raise MotionError(f"Missing attachment: {slot}/{k['name']}")
        for key in self.animation.get("drawOrder", []):
            draw_order(data.get("slots", []), key.get("offsets", []))
        ordered_slots(data.get("slots", []), data.get("layerConstraints", []))

    def positions(self, part, matrices, t, setup=False):
        if part.get("rigid_skinning"):
            if part["deform"]:
                raise MotionError("Rigid skinning does not accept vertex deform tracks.")
            transforms = {n: multiply(matrices[n], inverse(self.bind_matrices[n])) for n in matrices}
            positions = []
            for group in part["influences"]:
                bind = [point(self.bind_matrices[n], x, y) for n, x, y, wt in group]
                if any(math.dist(bind[0], p) > 1e-4 for p in bind[1:]):
                    raise MotionError("Rigid influences must share a bind-world position.")
                positions.append(rigid_blend_point(bind[0], [(transforms[n], wt) for n, x, y, wt in group]))
            return np.array(positions)
        count = sum(len(g) for g in part["influences"])
        delta = deform_at([] if setup else part["deform"], t, count * 2).reshape(-1, 2)
        result, i = [], 0
        for group in part["influences"]:
            x = y = 0
            for bone, lx, ly, weight in group:
                wx, wy = point(matrices[bone], lx + delta[i, 0], ly + delta[i, 1])
                x += wx * weight
                y += wy * weight
                i += 1
            result.append((x, y))
        a = np.array(result)
        if not np.isfinite(a).all() or np.abs(a).max() > 1e8:
            raise MotionError("Pose coordinates are nonfinite or unreasonably large.")
        return a

    def pose(self, t):
        matrices = worlds(self.data, self.animation, t)
        slots = self.data.get("slots", [])
        for key in self.animation.get("drawOrder", []):
            if key.get("time", 0) <= t:
                slots = draw_order(self.data.get("slots", []), key.get("offsets", []))
        result = []
        for slot in ordered_slots(slots, self.data.get("layerConstraints", [])):
            name = slot.get("attachment")
            channels = self.animation.get("slots", {}).get(slot["name"], {})
            for key in channels.get("attachment", []):
                if key.get("time", 0) <= t:
                    name = key.get("name")
            if name is None:
                continue
            if (slot["name"], name) not in self.parts:
                raise MotionError(f"Missing setup attachment: {slot['name']}/{name}")
            part = self.parts[(slot["name"], name)]
            color_keys = [
                {**k, **dict(zip("rgba", rgba(k.get("color", "ffffffff"))))}
                for k in channels.get("color", [])
            ]
            tint = (
                np.array(
                    list(
                        sample(color_keys, t, dict(zip("rgba", rgba(slot.get("color", "ffffffff"))))).values()
                    )
                )
                * part["color"]
            )
            result.append((slot["name"], name, part, self.positions(part, matrices, t), tint))
        return result

    def bounds(self, times):
        points = [v for t in times for _, _, _, v, tint in self.pose(t) if tint[3] > 0]
        if not points:
            raise MotionError("Animation has no visible geometry.")
        p = np.concatenate(points)
        return [float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max())]

    @staticmethod
    def camera(bounds, size, padding=0.04):
        if (
            len(bounds) != 4
            or not all(math.isfinite(v) for v in bounds)
            or bounds[2] <= bounds[0]
            or bounds[3] <= bounds[1]
        ):
            raise MotionError("Bounds must be [xmin,ymin,xmax,ymax] with positive area.")
        x0, y0, x1, y1 = bounds
        s = size * (1 - 2 * padding) / max(x1 - x0, y1 - y0)
        return (s, 0, size / 2 - s * (x0 + x1) / 2, 0, -s, size / 2 + s * (y0 + y1) / 2)

    def frame(self, t, size, camera, supersample=2):
        n = size * supersample
        cam = multiply((supersample, 0, 0, 0, supersample, 0), camera)
        canvas = np.zeros((n, n, 4), dtype=np.float32)
        for _, _, part, vertices, tint in self.pose(t):
            if tint[3] <= 0:
                continue
            dst = np.array([point(cam, *v) for v in vertices])
            x0, y0 = np.maximum(0, np.floor(dst.min(axis=0)).astype(int))
            x1, y1 = np.minimum(n, np.ceil(dst.max(axis=0)).astype(int))
            if x0 >= x1 or y0 >= y1:
                continue
            map_x = np.full((y1 - y0, x1 - x0), -100, np.float32)
            map_y = map_x.copy()
            covered = np.zeros(map_x.shape, dtype=bool)
            layer = np.zeros((*map_x.shape, 4), dtype=np.float32)
            th, tw = part["texture"].shape[:2]
            uv = part["uv"] * [tw, th] - 0.5
            for tri in part["triangles"]:
                a, b, c = dst[tri]
                det = np.linalg.det(np.array([b - a, c - a]))
                if abs(det) < 1e-10:
                    continue
                tx0, ty0 = np.maximum([x0, y0], np.floor(dst[tri].min(axis=0)).astype(int))
                tx1, ty1 = np.minimum([x1, y1], np.ceil(dst[tri].max(axis=0)).astype(int))
                if tx0 >= tx1 or ty0 >= ty1:
                    continue
                xx, yy = np.meshgrid(np.arange(tx0, tx1) + 0.5 - a[0], np.arange(ty0, ty1) + 0.5 - a[1])
                u = (xx * (c[1] - a[1]) - yy * (c[0] - a[0])) / det
                v = ((b[0] - a[0]) * yy - (b[1] - a[1]) * xx) / det
                mask = (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7)
                region = (slice(ty0 - y0, ty1 - y0), slice(tx0 - x0, tx1 - x0))
                q = uv[tri]
                sx = (q[0, 0] + u * (q[1, 0] - q[0, 0]) + v * (q[2, 0] - q[0, 0])).astype(np.float32)
                sy = (q[0, 1] + u * (q[1, 1] - q[0, 1]) + v * (q[2, 1] - q[0, 1])).astype(np.float32)
                # Adjacent triangles share a texel on their edge: composite it once.
                # Folded mesh surfaces may overlap at DIFFERENT UVs: alpha-composite
                # those surfaces, so a later transparent texel cannot erase an arm.
                shared = (
                    covered[region]
                    & (np.abs(map_x[region] - sx) < 1e-3)
                    & (np.abs(map_y[region] - sy) < 1e-3)
                )
                fragment = cv2.remap(
                    part["texture"], sx, sy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
                )
                fragment *= (mask & ~shared)[:, :, None]
                previous = layer[region]
                previous[:] = fragment + previous * (1 - fragment[:, :, 3:4])
                map_x[region][mask] = sx[mask]
                map_y[region][mask] = sy[mask]
                covered[region] |= mask
            layer[:, :, :3] *= tint[:3] * tint[3]
            layer[:, :, 3] *= tint[3]
            dst_pixels = canvas[y0:y1, x0:x1]
            dst_pixels[:] = layer + dst_pixels * (1 - layer[:, :, 3:4])
        if supersample > 1:
            canvas = cv2.resize(canvas, (size, size), interpolation=cv2.INTER_AREA)
        alpha = canvas[:, :, 3:4]
        canvas[:, :, :3] = np.divide(
            canvas[:, :, :3], alpha, out=np.zeros_like(canvas[:, :, :3]), where=alpha > 1e-7
        )
        return Image.fromarray(np.uint8(np.clip(canvas, 0, 1) * 255 + 0.5))

    def diagnostics(self, times):
        setup = worlds(self.data, {}, 0)
        baselines = {key: self.positions(p, setup, 0, True) for key, p in self.parts.items()}
        findings = []
        switches = []
        for slot, tracks in self.animation.get("slots", {}).items():
            switches.extend(
                {"slot": slot, "time": k.get("time", 0), "attachment": k.get("name")}
                for k in tracks.get("attachment", [])
            )
        for index, t in enumerate(times):
            for slot, name, p, vertices, tint in self.pose(t):
                if tint[3] <= 0:
                    continue
                tri = p["triangles"]
                base = baselines[(slot, name)][tri]
                now = vertices[tri]

                def area(v):
                    ab, ac = v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]
                    return ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]

                ba, na = area(base), area(now)
                ratio = np.divide(na, ba, out=np.ones_like(na), where=np.abs(ba) > 1e-8)
                candidates = np.flatnonzero((ratio < 0.12) | (ratio > 6))
                if len(candidates):
                    findings.append(
                        dict(
                            frame=index,
                            time=t,
                            slot=slot,
                            attachment=name,
                            triangles=candidates.tolist(),
                            min_area_ratio=float(ratio.min()),
                            max_area_ratio=float(ratio.max()),
                        )
                    )
        return dict(
            note="Geometry candidates only; natural motion, finger anatomy and seams require image review.",
            candidates=findings[:2000],
            candidate_count=len(findings),
            attachment_switches=switches,
            visual_review_passed=False,
        )


def timeline(animation, fps):
    seconds = duration(animation)
    if not 0 < seconds <= 20 or not 1 <= fps <= 60:
        raise MotionError("Animation must last 0..20 seconds; FPS must be 1..60.")
    # Native JSON rounds key times to four decimal places. A rounded 3.6667
    # must not add a near-zero interval after frame 110 at 30 FPS.
    nearest = round(seconds * fps)
    count = (
        nearest
        if nearest > 0 and abs(seconds - nearest / fps) <= 0.00005
        else math.ceil(seconds * fps - 1e-8)
    )
    times = [min(i / fps, seconds) for i in range(count)]
    return times + [seconds]
