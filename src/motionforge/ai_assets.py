"""Explicit visible-pixel extraction for AI-specified masks; never inpaints."""

import hashlib
import uuid
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageDraw
from pydantic import Field

from .motion import Model
from .service import checked_image
from .storage import MotionError, identifier, inside, write_json


class PartMask(Model):
    forbidden_polygons: list[list[tuple[float, float]]] = Field(
        default_factory=list,
        max_length=16,
        description="Source areas owned by other parts (e.g. sleeve pixels that must not remain on the torso). Reject retained opaque pixels here; this validates rather than silently erasing artwork.",
    )
    required_polygons: list[list[tuple[float, float]]] = Field(
        default_factory=list,
        max_length=16,
        description="Source areas this part must preserve (e.g. the entire vest silhouette). Extraction fails if the outline, exclusions or skin filter cut opaque pixels here. Use interior coverage landmarks, not antialiased silhouette edges.",
    )
    clip_polygons: list[list[tuple[float, float]]] = Field(
        default_factory=list,
        max_length=8,
        description="Intersect the selection with these additional polygons (e.g. rounded joint end caps).",
    )
    isolate_warm_skin: bool = Field(
        default=False,
        description="Within the chosen outline, isolate warm skin pixels plus a one-pixel ink border; for sleeveless limbs only.",
    )
    excluded_warm_skin_polygons: list[list[tuple[float, float]]] = Field(default_factory=list, max_length=8)
    alpha_floor: int = Field(
        default=0,
        ge=0,
        le=254,
        description="Optional matte cleanup: discard source alpha below this value; RGB stays original.",
    )
    min_source_component: int = Field(
        default=0,
        ge=0,
        le=10000,
        description="Discard isolated alpha components smaller than this source-pixel area, before part cutting.",
    )
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    polygon: list[tuple[float, float]] = Field(
        min_length=3,
        max_length=256,
        description="Visible part outline in ORIGINAL input pixels: X right, Y down. Must exclude hair/face/other body parts.",
    )
    excluded_polygons: list[list[tuple[float, float]]] = Field(
        default_factory=list,
        max_length=32,
        description="Holes removing unwanted source pixels; each polygon requires at least three points.",
    )
    pivot: tuple[float, float] = Field(
        description="Joint position in original image pixels. Used to calculate the attachment center relative to its bone."
    )


def extract_part(workspace: Path, image_path: str, mask: PartMask):
    identifier(mask.name)
    source = inside(workspace, image_path)
    width, height = checked_image(source)
    polygons = [
        mask.polygon,
        *mask.excluded_polygons,
        *mask.excluded_warm_skin_polygons,
        *mask.clip_polygons,
        *mask.required_polygons,
        *mask.forbidden_polygons,
    ]
    if any(not 3 <= len(p) <= 256 for p in polygons):
        raise MotionError("Each outline/hole needs 3–256 points.")
    if not all(0 <= x <= width and 0 <= y <= height for p in polygons for x, y in p):
        raise MotionError("Polygon coordinates must lie inside the original image.")
    px, py = mask.pivot
    if not 0 <= px <= width or not 0 <= py <= height:
        raise MotionError("Pivot must lie inside the original image.")
    alpha_mask = Image.new("L", (width * 2, height * 2))
    draw = ImageDraw.Draw(alpha_mask)
    for i, polygon in enumerate([mask.polygon, *mask.excluded_polygons]):
        draw.polygon([(x * 2, y * 2) for x, y in polygon], fill=255 if i == 0 else 0)
    alpha_mask = alpha_mask.resize((width, height), Image.Resampling.LANCZOS)
    for polygon in mask.clip_polygons:
        clip = Image.new("L", (width * 2, height * 2))
        ImageDraw.Draw(clip).polygon([(x * 2, y * 2) for x, y in polygon], fill=255)
        alpha_mask = ImageChops.multiply(alpha_mask, clip.resize((width, height), Image.Resampling.LANCZOS))
    with Image.open(source) as original:
        part = original.convert("RGBA")
    original_alpha = np.array(part.getchannel("A"))
    if mask.isolate_warm_skin or mask.excluded_warm_skin_polygons:
        rgb = np.array(part, dtype=np.int16)[:, :, :3]
        rr, gg, bb = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        skin = ((rr > 160) & (gg > 100) & (rr > bb + 7) & (gg > bb * 0.9) & (rr - gg < 90)).astype(np.uint8)
        skin = cv2.dilate(skin, np.ones((3, 3), np.uint8))
        if mask.isolate_warm_skin:
            alpha_mask = ImageChops.multiply(alpha_mask, Image.fromarray(skin * 255))
        for polygon in mask.excluded_warm_skin_polygons:
            exclude = Image.new("L", (width, height))
            ImageDraw.Draw(exclude).polygon(polygon, fill=255)
            exclude = ImageChops.multiply(exclude, Image.fromarray(skin * 255))
            alpha_mask = ImageChops.subtract(alpha_mask, exclude)
    if mask.alpha_floor or mask.min_source_component:
        alpha = np.array(part.getchannel("A"))
        foreground = (alpha > mask.alpha_floor).astype(np.uint8)
        if mask.min_source_component:
            count, labels, stats, centers = cv2.connectedComponentsWithStats(foreground)
            areas = stats[:, cv2.CC_STAT_AREA]
            keep = areas >= mask.min_source_component
            keep[0] = False
            foreground = keep[labels]
        alpha[foreground == 0] = 0
        part.putalpha(Image.fromarray(alpha))
    part.putalpha(ImageChops.multiply(part.getchannel("A"), alpha_mask))
    if mask.forbidden_polygons:
        forbidden = Image.new("L", (width, height))
        for polygon in mask.forbidden_polygons:
            ImageDraw.Draw(forbidden).polygon(polygon, fill=255)
        retained = (np.array(forbidden) > 0) & (np.array(part.getchannel("A")) >= 32)
        if retained.any():
            yy, xx = np.where(retained)
            raise MotionError(
                f"Extraction retains {int(retained.sum())} forbidden pixels belonging to another part near source box "
                f"[{int(xx.min())}, {int(yy.min())}, {int(xx.max()) + 1}, {int(yy.max()) + 1}]. "
                "Correct the outline or exclusions; connected sleeve/skin remnants also need removal."
            )
    if mask.required_polygons:
        required = Image.new("L", (width, height))
        for polygon in mask.required_polygons:
            ImageDraw.Draw(required).polygon(polygon, fill=255)
        expected = (np.array(required) > 0) & (original_alpha >= 245)
        missing = expected & (np.array(part.getchannel("A")) < 220)
        if missing.any():
            yy, xx = np.where(missing)
            raise MotionError(
                f"Extraction cuts {int(missing.sum())} required opaque pixels near source box "
                f"[{int(xx.min())}, {int(yy.min())}, {int(xx.max()) + 1}, {int(yy.max()) + 1}]. "
                "Expand the part outline or correct its exclusions; preserve the complete clothing/skin region."
            )
    box = part.getbbox()
    if not box:
        raise MotionError("Mask contains no visible source pixels.")
    folder = workspace / "inbox" / ("part-" + uuid.uuid4().hex[:12])
    folder.mkdir(parents=True)
    path = folder / (mask.name + ".png")
    part.crop(box).save(path)
    result = dict(
        path=path.relative_to(workspace).as_posix(),
        original=image_path,
        original_size=[width, height],
        crop_box=list(box),
        size=[box[2] - box[0], box[3] - box[1]],
        pivot_original=[px, py],
        attachment_center={"x": (box[0] + box[2]) / 2 - px, "y": py - (box[1] + box[3]) / 2},
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        mask=mask.model_dump(),
        hidden_art_reconstructed=False,
        note="Visible pixels only. Inspect this part for contamination; complete hidden joint/hair regions using a separate image-editing tool before rigging. Original image is unchanged.",
    )
    write_json(folder / "extraction.json", result)
    return result
