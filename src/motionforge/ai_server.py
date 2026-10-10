"""MotionForge: AI-only MCP authoring, with no editor or browser dependency."""

from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Image as MCPImage
from mcp.types import ToolAnnotations
from PIL import Image
from pydantic import Field

from .ai_assets import PartMask
from .ai_assets import extract_part as cut_part
from .ai_service import AIService, RenderSpec, VisualCheck, digest
from .mesh import MeshSpec
from .motion import PRESETS, Bone, Layer, validate_skeleton
from .software_renderer import SoftwareRenderer, supported
from .storage import MotionError, inside

WORKFLOW = """You are operating MotionForge, an AI-only 2D character animation tool.
No Spine, graphical editor or browser is required. Start by inspecting the actual source image.
Use clean reusable transparent parts: face without features, separate hair, eyes, eyebrows,
mouth, torso, upper/lower limbs, sleeves and hands. Preserve the original character's style.
The MCP does NOT contain a generative image model: create missing/occluded artwork with your
own image-editing tool, or use supplied parts. Never call a flat-image wobble a fully rigged character.
Use extract_part with explicit outlines/holes for visible original pixels; it does not fill
hidden regions or remove accidental contamination automatically. Inspect each extracted part.
Use upload_asset, create_character/import_character, inspect_character, bind_mesh and
register_attachment. Keep wrist roots under upper cuff lips and give joints overlapping artwork.
Coordinates: bone-local Y up; texture UV origin at top left; layers back to front.
Independent hand or expression attachments belong to the same character, not a new whole-body image.
Use set_animation for complete bone/slot/deform/drawOrder timelines; key times are seconds,
rotation/translation are setup offsets, scales are multipliers. Use retime_animation to scale
ALL timelines together. Presets are starting points that require character-specific refinement.
Copy parts only when needed; retain earlier revisions. Read exact bone/attachment names first.
Use analyze_motion for geometry candidates and bounds. Share bounds between actions for a
consistent game canvas/pivot. Unsupported features produce errors, not silent approximations.
start_render returns immediately; keep this MCP session alive and poll render_status. After it
completes inspect ALL frames, with crops for wrists/fingers/face. Record only actually viewed
frames with their returned hashes; numeric diagnostics never mean visual approval. Reference
links and observations must describe references you actually examined, not invented sources.
export_animations requires full visual review by default; require_reviewed=false creates a
clearly marked draft. Outputs: transparent PNG frames, WebP, APNG, optional binary-alpha GIF and
paged spritesheets with timing and root pivot. Exact endpoint PNG is for review and omitted
from loops to avoid an extra held frame. Engine-native game skeleton integration is not certified.
All paths are relative to the workspace. Original inputs and past revisions remain available.
"""


def picture(path):
    with Image.open(path) as image:
        im = image.convert("RGBA")
        original = im.size
        im.thumbnail((1536, 1536))
        bg = Image.new("RGBA", im.size, "#344755")
        bg.alpha_composite(im)
        buf = io.BytesIO()
        bg.save(buf, "PNG")
    return original, MCPImage(data=buf.getvalue(), format="png")


def build_ai_server(workspace: Path, port=8776):
    ai = AIService(workspace)
    mcp = FastMCP(
        "MotionForge",
        instructions=WORKFLOW,
        host="127.0.0.1",
        port=port,
        stateless_http=True,
        json_response=True,
        log_level="WARNING",
        max_request_body_size=24_000_000,
    )
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

    @mcp.tool(annotations=read)
    def get_capabilities() -> dict:
        """Read supported production features, boundaries and the complete AI workflow."""
        return dict(
            name="MotionForge",
            version="0.2.0",
            requires_spine=False,
            requires_display=False,
            workspace=str(ai.workspace),
            renderer=SoftwareRenderer.name,
            supports=[
                "layered RGBA parts",
                "explicit polygon extraction with exclusions",
                "FK bones",
                "weighted and unweighted meshes",
                "rigid dual-quaternion skinning",
                "source artwork / proportions / camera lock",
                "Bezier keys",
                "attachment switching",
                "draw order",
                "vertex deformation",
                "slot tint",
                "transparent PNG/WebP/APNG",
                "GIF",
                "spritesheets",
                "revisioned review",
            ],
            unsupported=[
                "automatic occlusion reconstruction",
                "IK/transform/path constraints",
                "linkedmesh",
                "clipping",
                "non-normal inheritance",
                "blend modes",
                "game-runtime certification",
            ],
            presets=PRESETS,
            workflow=WORKFLOW,
        )

    @mcp.tool(annotations=write)
    def lock_identity(
        project_id: str,
        bounds: list[float],
        expression_bones: list[str] = [],
        movable_bones: list[str] = [],
        effect_bones: list[str] = [],
    ) -> dict:
        """Freeze setup proportions, artwork and camera. Explicit exceptions allow facial expression and effects."""
        return ai.lock_identity(project_id, bounds, expression_bones, movable_bones, effect_bones)

    @mcp.tool(annotations=write)
    def upload_asset(filename: str, data_base64: str) -> dict:
        """Upload actual PNG/JPEG/WebP/JSON bytes (max 16 MB). Chat attachment IDs are not local paths."""
        if len(data_base64) > 22_000_000:
            raise MotionError("Upload exceeds 16 MB.")
        try:
            content = base64.b64decode(data_base64, validate=True)
        except ValueError as exc:
            raise MotionError("Expected actual base64 file bytes.") from exc
        return ai.service.upload(filename, content)

    @mcp.tool(annotations=read)
    def list_assets() -> list[dict]:
        """Find uploaded images/JSON before creating a character."""
        return ai.service.list_assets()

    @mcp.tool(annotations=read, structured_output=False)
    def inspect_image(path: str):
        """View an input/part/render image. Returns original pixel dimensions; does not mark frames reviewed."""
        target = inside(ai.workspace, path)
        if (
            target.suffix.lower() not in (".png", ".webp", ".gif", ".jpg", ".jpeg")
            or target.stat().st_size > 32_000_000
        ):
            raise MotionError("Choose an image no larger than 32 MB.")
        size, content = picture(target)
        return [
            json.dumps(dict(path=path, original_size=size, coordinates="original pixels, top left, Y down")),
            content,
        ]

    @mcp.tool(annotations=read)
    def list_characters() -> list[dict]:
        """List existing character IDs in this workspace."""
        return ai.service.list_projects()

    @mcp.tool(annotations=write)
    def extract_part(image_path: str, mask: PartMask) -> dict:
        """Extract visible original pixels using explicit part outline and optional exclusion holes. Returns a NEW transparent PNG plus exact bone-local attachment center. Inspect first: coordinates use original pixels. Cannot reconstruct occluded anatomy or automatically identify parts."""
        return cut_part(ai.workspace, image_path, mask)

    @mcp.tool(annotations=read)
    def inspect_character(project_id: str) -> dict:
        """Read complete editable character data, exact names, actions, current revision and image directory."""
        return ai.inspect(project_id)

    @mcp.tool(annotations=write)
    def create_character(
        project_id: str, bones: list[Bone], layers: list[Layer], roles: dict[str, str] | None = None
    ) -> dict:
        """Create from clean transparent PNG parts. Parent-first bone coordinates Y-up; layers back-to-front. New ID required. Does not generate or inpaint missing artwork."""
        return ai.service.create_rig(project_id, bones, layers, roles)

    @mcp.tool(annotations=write)
    def import_character(project_id: str, json_path: str, images_dir: str) -> dict:
        """Copy existing layered character JSON (3.8 schema) and unpacked PNGs into a new project. No editor call. Analyze each motion before rendering."""
        return ai.service.import_json(project_id, json_path, images_dir)

    @mcp.tool(annotations=write)
    def update_character(project_id: str, expected_revision: str, data: dict) -> dict:
        """Save edited bones/slots/meshes as a NEW revision. Start from inspect_character.data. Must match expected_revision. Existing image paths only; register new art separately."""
        with ai.service.lock():
            folder, manifest, _ = ai.service._load(project_id)
            if manifest["active"] != expected_revision:
                raise MotionError("Character changed; inspect again before editing.")
            validate_skeleton(data)
            supported(data, {})
            probe = {**data, "animations": {**data.get("animations", {}), "__validate": {}}}
            SoftwareRenderer(probe, folder, "__validate")
            for name in data.get("animations", {}):
                r = SoftwareRenderer(data, folder, name)
                r.bounds([0, duration_for(data, name)])
            return ai.service._commit(folder, manifest, data, "AI edit character structure")

    @mcp.tool(annotations=write)
    def bind_mesh(project_id: str, mesh: MeshSpec) -> dict:
        """Bind a rectangular attachment to explicit UV vertices, triangles and normalized bone weights; preserves setup placement. Review extreme joint poses afterward."""
        return ai.service.bind_mesh(project_id, mesh)

    @mcp.tool(annotations=write)
    def register_attachment(
        project_id: str, slot: str, name: str, image_path: str, x: float = 0, y: float = 0, scale: float = 1
    ) -> dict:
        """Add a new independent hand/face/prop PNG choice to an existing slot. Center x/y is bone-local Y-up. Key its name through set_animation slots. Never overwrites old artwork."""
        return ai.register_attachment(project_id, slot, name, image_path, x, y, scale)

    @mcp.tool(annotations=write)
    def map_roles(project_id: str, roles: dict[str, str]) -> dict:
        """Assign semantic roles (body/head/arm/hand/arm_left/right/etc.) after reading actual bone names."""
        return ai.service.map_roles(project_id, roles)

    @mcp.tool(annotations=write)
    def add_motion_preset(
        project_id: str,
        preset: str,
        name: str | None = None,
        seconds: float | None = None,
        strength: float = 1,
        overwrite: bool = False,
    ) -> dict:
        """Create editable starting motion from get_capabilities.presets. Tune it for proportions and artwork; preset creation does not approve quality."""
        return ai.service.add_preset(project_id, preset, name, seconds, strength, overwrite)

    @mcp.tool(annotations=write)
    def set_animation(project_id: str, name: str, animation: dict, overwrite: bool = False) -> dict:
        """Write complete bones/slots/deform/drawOrder timelines. Example: {bones:{head:{rotate:[{time:0,angle:0},{time:1,angle:5},{time:2,angle:0}]}}}. All previous revisions retained. Use actual attachment names for slots; interpolation linear/stepped/[cx1,cy1,cx2,cy2]."""
        return ai.put_animation(project_id, name, animation, overwrite)

    @mcp.tool(annotations=write)
    def retime_animation(project_id: str, animation: str, speed: float, name: str | None = None) -> dict:
        """Scale every key time together, including hand changes, expressions, draw order and deform. 1.5 means 1.5x faster. Optional new name preserves the old action too."""
        return ai.retime(project_id, animation, speed, name)

    @mcp.tool(annotations=read)
    def analyze_motion(project_id: str, animation: str, fps: int = 30, skin: str = "default") -> dict:
        """Check supported features, full-motion bounds, triangle collapse/flip candidates and hand switches. Numeric results do NOT certify seam quality, anatomy or natural motion."""
        return ai.analyze(project_id, animation, fps, skin)

    @mcp.tool(annotations=write)
    def start_render(spec: RenderSpec) -> dict:
        """Snapshot a character and start independent CPU rendering; returns run_id immediately. Poll render_status; keep MCP session alive. PNG frames always saved. Optional transparent WebP/APNG, binary-alpha GIF, paged spritesheets. Share bounds across actions for fixed scale/pivot."""
        return ai.start(spec)

    @mcp.tool(annotations=read)
    def render_status(run_id: str) -> dict:
        """Get rendering progress, errors or final artifact paths and current visual-review coverage."""
        return ai.status(run_id)

    @mcp.tool(annotations=write, structured_output=False)
    def inspect_frames(run_id: str, frames: list[int], crop: tuple[int, int, int, int] | None = None):
        """Return 1–12 actual frames as a labeled sheet and frame hashes. Optional crop [x,y,width,height] in output pixels. Inspect every frame; zoom hands/joints. Does not approve anything."""
        result = ai.inspect_frames(run_id, frames, crop)
        return [json.dumps(result), MCPImage(path=str(inside(ai.workspace, result["sheet"])))]

    @mcp.tool(annotations=write)
    def record_frame_checks(run_id: str, checks: list[VisualCheck]) -> dict:
        """Record pass/fail/uncertain only for pixels you actually inspected. Notes must cover relevant seams, distortion and anatomy. Unseen frames or wrong hashes are rejected."""
        return ai.record_checks(run_id, checks)

    @mcp.tool(annotations=write)
    def export_animations(run_ids: list[str], require_reviewed: bool = True) -> dict:
        """Package exact source parts/data, animations and review evidence from one revision. Full review required by default; explicitly false exports a marked draft. No Spine required."""
        return ai.export(run_ids, require_reviewed)

    @mcp.tool(annotations=read)
    def read_artifact_bytes(
        path: str,
        offset: Annotated[int, Field(ge=0)] = 0,
        length: Annotated[int, Field(ge=1, le=262144)] = 262144,
    ) -> dict:
        """Transfer output to a remote AI client in base64 chunks. Local clients can read returned workspace paths directly. No shell execution or network fetch."""
        target = inside(ai.workspace, path)
        if not target.is_file():
            raise MotionError("Choose a file.")
        with target.open("rb") as f:
            f.seek(offset)
            content = f.read(length)
        return dict(
            path=path,
            offset=offset,
            next_offset=offset + len(content),
            size=target.stat().st_size,
            eof=offset + len(content) >= target.stat().st_size,
            sha256=digest(target),
            data_base64=base64.b64encode(content).decode(),
        )

    @mcp.resource("motionforge://workflow")
    def workflow() -> str:
        return WORKFLOW

    @mcp.prompt()
    def animate_character(image_path: str, actions: str = "idle, wave, think") -> str:
        return (
            WORKFLOW
            + f"\nInput: {image_path}\nRequested actions: {actions}\nProduce independent character art and verify all rendered frames before final export."
        )

    return mcp, ai


def duration_for(data, name):
    from .motion import duration

    return duration(data["animations"][name])


def main():
    parser = argparse.ArgumentParser(description="MotionForge AI-only animation MCP; no Spine required")
    parser.add_argument("--workspace", default=str(Path.cwd() / "motionforge-workspace"))
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--port", type=int, default=8776)
    args = parser.parse_args()
    mcp, _ = build_ai_server(Path(args.workspace), args.port)
    mcp.run(transport="stdio" if args.transport == "stdio" else "streamable-http")


if __name__ == "__main__":
    main()
