"""Reproduce the packaged final wave and thinking through MCP, from an installed wheel."""

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def payload(result):
    if result.isError:
        raise RuntimeError(str(result.content))
    return result.structuredContent or json.loads(next(c.text for c in result.content if c.type == "text"))


async def replay(workspace):
    workspace = workspace.resolve()
    project = "gestures-" + uuid.uuid4().hex[:8]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "motionforge.ai_server", "--workspace", str(workspace)],
        env={**os.environ, "PYTHONUTF8": "1", "SPINE_EXECUTABLE": "NOT_INSTALLED.exe"},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            caps = payload(await session.call_tool("get_capabilities", {}))
            assert caps["requires_spine"] is False
            created = payload(
                await session.call_tool(
                    "instantiate_motion_recipe",
                    {
                        "recipe_id": "female_gestures_v1",
                        "project_id": project,
                    },
                )
            )
            assert created["compatible"] and all(created["exact_actions"].values())
            runs = {}
            for spec in created["render_requests"]:
                name = spec["animation"]
                job = payload(await session.call_tool("start_render", {"spec": spec}))
                deadline = time.monotonic() + 1200
                while job["status"] not in ("complete", "failed"):
                    if time.monotonic() > deadline:
                        raise TimeoutError("Render exceeded 20 minutes; inspect render_status.")
                    await asyncio.sleep(0.5)
                    job = payload(await session.call_tool("render_status", {"run_id": job["run_id"]}))
                if job["status"] != "complete":
                    raise RuntimeError(str(job))
                assert job["frame_count"] == {"wave": 111, "think": 145}[name]
                assert not job["visual_review_passed"]
                runs[name] = job
                print(f"{name}: {job['frame_count']} frames rendered", flush=True)
            bundle = payload(
                await session.call_tool(
                    "export_animations",
                    {
                        "run_ids": [r["run_id"] for r in runs.values()],
                        "require_reviewed": False,
                    },
                )
            )
            result = dict(
                project=project,
                version=caps["version"],
                recipe=created,
                runs=runs,
                bundle=bundle,
                note="Exact source reproduced; this automated example does not approve artwork.",
            )
            output = workspace / (project + "-replay.json")
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(output)
            print(workspace / bundle["bundle"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path("workspace"))
    asyncio.run(replay(parser.parse_args().workspace))
