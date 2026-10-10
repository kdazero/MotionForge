"""Import, render and export the bundled robot through a real stdio MCP session."""

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def payload(result):
    if result.isError:
        raise RuntimeError(str(result.content))
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(next(c.text for c in result.content if c.type == "text"))


async def run(workspace):
    workspace.mkdir(parents=True, exist_ok=True)
    project_id = "robot-" + uuid.uuid4().hex[:10]
    relative = "inbox/" + project_id
    source = Path(__file__).parent / "robot"
    if not (source / "character.json").is_file():
        raise FileNotFoundError("Download the full source/user ZIP; the robot example is missing.")
    shutil.copytree(source, workspace / relative)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "motionforge", "--workspace", str(workspace)],
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            payload(await client.call_tool("get_capabilities", {}))
            payload(
                await client.call_tool(
                    "import_character",
                    {
                        "project_id": project_id,
                        "json_path": relative + "/character.json",
                        "images_dir": relative + "/images",
                    },
                )
            )
            roles = json.loads((source / "roles.json").read_text(encoding="utf-8"))
            payload(await client.call_tool("map_roles", {"project_id": project_id, "roles": roles}))
            job = payload(
                await client.call_tool(
                    "start_render",
                    {
                        "spec": {
                            "project_id": project_id,
                            "animation": "wave",
                            "fps": 12,
                            "size": 256,
                            "formats": ["webp", "apng", "gif", "spritesheet"],
                            "references": [
                                {
                                    "source": "Bundled geometric robot",
                                    "license": "MIT",
                                    "note": "Procedural preset demonstration; no video reference used.",
                                }
                            ],
                        }
                    },
                )
            )
            deadline = time.monotonic() + 180
            while True:
                status = payload(await client.call_tool("render_status", {"run_id": job["run_id"]}))
                if status["status"] == "failed":
                    raise RuntimeError(str(status))
                if status["status"] == "complete":
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Demo render exceeded 180 seconds.")
                await asyncio.sleep(0.2)
            # The script is not a visual reviewer. Always export a marked draft.
            exported = payload(
                await client.call_tool(
                    "export_animations",
                    {
                        "run_ids": [job["run_id"]],
                        "require_reviewed": False,
                    },
                )
            )
    result = {
        "project_id": project_id,
        "run_id": job["run_id"],
        "preview": str(workspace / status["artifacts"]["animation.webp"]),
        "bundle": str(workspace / exported["bundle"]),
        "frames": status["frame_count"],
        "visual_review_passed": False,
        "note": "Technical demo completed. Open the preview; visual approval has not been recorded.",
    }
    (workspace / "demo-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(run(args.workspace.resolve()))


if __name__ == "__main__":
    main()
