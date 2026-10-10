"""Explicit setup-pose binding to Spine 3.8 weighted mesh attachments.

This only handles unconstrained, normal-transform setup bones. Complex existing
rigs should be bound inside the native editor, not approximated here.
"""

from __future__ import annotations

import copy
import math
from typing import Literal

from pydantic import Field, model_validator

from .motion import Model
from .render import inverse, multiply, point, transform, worlds
from .storage import MotionError


class MeshVertex(Model):
    u: float = Field(ge=0, le=1, description="Texture coordinate, left to right.")
    v: float = Field(ge=0, le=1, description="Texture coordinate, top to bottom.")
    weights: dict[str, float] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def normalized(self):
        if any(not math.isfinite(w) or w <= 0 or w > 1 for w in self.weights.values()):
            raise ValueError("Weights must be finite and in (0, 1].")
        if not math.isclose(sum(self.weights.values()), 1, abs_tol=1e-6):
            raise ValueError("Each vertex's weights must sum to 1.")
        return self


class MeshSpec(Model):
    skinning: Literal["linear", "rigid"] = "linear"
    slot: str
    attachment: str
    skin: str = "default"
    vertices: list[MeshVertex] = Field(min_length=3, max_length=256)
    triangles: list[tuple[int, int, int]] = Field(min_length=1, max_length=512)
    hull: int = Field(ge=3, le=256, description="First N vertices form the ordered outer boundary.")

    @model_validator(mode="after")
    def topology(self):
        n = len(self.vertices)
        if self.hull > n:
            raise ValueError("Hull exceeds vertex count.")
        if len({(v.u, v.v) for v in self.vertices}) != n:
            raise ValueError("Duplicate texture vertices.")
        signs = set()
        used = set()
        for triangle in self.triangles:
            if len(set(triangle)) != 3 or any(i < 0 or i >= n for i in triangle):
                raise ValueError("Invalid triangle indices.")
            a, b, c = [self.vertices[i] for i in triangle]
            area = (b.u - a.u) * (c.v - a.v) - (b.v - a.v) * (c.u - a.u)
            if abs(area) < 1e-8:
                raise ValueError("Degenerate mesh triangle.")
            signs.add(area > 0)
            used.update(triangle)
        if len(signs) > 1 or len(used) != n:
            raise ValueError("Use consistent triangle winding and connect every vertex.")
        return self


def bind_region(data: dict, spec: MeshSpec) -> dict:
    if any(data.get(k) for k in ("ik", "transform", "path")) or any(
        b.get("transform", "normal") != "normal" or b.get("skin") for b in data["bones"]
    ):
        raise MotionError("Constrained/non-normal-transform rigs are not supported.")
    result = copy.deepcopy(data)
    skin = next((s for s in result.get("skins", []) if s["name"] == spec.skin), None)
    slot = next((s for s in result.get("slots", []) if s["name"] == spec.slot), None)
    if not skin or not slot:
        raise MotionError("Unknown skin or slot.")
    attachments = skin.get("attachments", {}).get(spec.slot, {})
    region = attachments.get(spec.attachment)
    if not region or region.get("type", "region") != "region":
        raise MotionError("Select an existing region attachment to bind.")
    matrices = worlds(result, {}, 0)
    indices = {b["name"]: i for i, b in enumerate(result["bones"])}
    width, height = region.get("width", 0), region.get("height", 0)
    if width <= 0 or height <= 0:
        raise MotionError("Region dimensions are required for mesh binding.")
    local = transform(
        region.get("x", 0),
        region.get("y", 0),
        region.get("rotation", 0),
        region.get("scaleX", 1),
        region.get("scaleY", 1),
    )
    image_world = multiply(matrices[slot["bone"]], local)
    encoded = []
    for vertex in spec.vertices:
        wx, wy = point(image_world, (vertex.u - 0.5) * width, (0.5 - vertex.v) * height)
        encoded.append(len(vertex.weights))
        for bone, weight in vertex.weights.items():
            if bone not in indices:
                raise MotionError(f"Unknown weight bone: {bone}")
            x, y = point(inverse(matrices[bone]), wx, wy)
            encoded.extend([indices[bone], round(x, 6), round(y, 6), weight])
    mesh = {k: region[k] for k in ("path", "color") if k in region}
    mesh.update(
        type="mesh",
        width=width,
        height=height,
        uvs=[number for v in spec.vertices for number in (v.u, v.v)],
        triangles=[i for tri in spec.triangles for i in tri],
        vertices=encoded,
        hull=spec.hull,
        edges=[i for k in range(spec.hull) for i in (k * 2, ((k + 1) % spec.hull) * 2)],
    )
    if spec.skinning == "rigid":
        mesh["skinning"] = "rigid"
    attachments[spec.attachment] = mesh
    return result
