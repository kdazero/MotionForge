"""Exercise the AI-only server through real MCP transports, without an editor."""

import asyncio
import base64
import io
import json
import os
import socket
import subprocess
import sys
import time
import zipfile

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from PIL import Image


def payload(result):
    assert not result.isError, result.content
    return result.structuredContent or json.loads(next(c.text for c in result.content if c.type == "text"))


async def exercise(session, workspace):
    init = await session.initialize()
    assert init.serverInfo.name == "MotionForge"
    names = {t.name for t in (await session.list_tools()).tools}
    assert {"create_character", "bind_mesh", "set_animation", "start_render", "inspect_frames"} <= names
    assert not {"open_spine", "export_project", "desktop_action", "render_native_review"} & names
    caps = payload(await session.call_tool("get_capabilities", {}))
    assert caps["requires_spine"] is False and caps["requires_display"] is False
    assert (await session.read_resource("motionforge://workflow")).contents
    stream = io.BytesIO()
    Image.new("RGBA", (32, 64), "#62b4ed").save(stream, "PNG")
    uploaded = payload(
        await session.call_tool(
            "upload_asset",
            {"filename": "part.png", "data_base64": base64.b64encode(stream.getvalue()).decode()},
        )
    )
    viewed = await session.call_tool("inspect_image", {"path": uploaded["path"]})
    assert not viewed.isError and any(c.type == "image" for c in viewed.content)
    payload(
        await session.call_tool(
            "create_character",
            {
                "project_id": "client",
                "bones": [{"name": "root"}, {"name": "body", "parent": "root", "y": 32}],
                "layers": [{"name": "body", "bone": "body", "image": uploaded["path"]}],
                "roles": {"body": "body"},
            },
        )
    )
    payload(
        await session.call_tool(
            "set_animation",
            {
                "project_id": "client",
                "name": "nod",
                "animation": {
                    "bones": {"body": {"rotate": [{"time": 0}, {"time": 0.5, "angle": 15}, {"time": 1}]}}
                },
            },
        )
    )
    character = payload(await session.call_tool("inspect_character", {"project_id": "client"}))
    stale = await session.call_tool(
        "update_character", {"project_id": "client", "expected_revision": "old", "data": character["data"]}
    )
    assert stale.isError
    job = payload(
        await session.call_tool(
            "start_render",
            {
                "spec": {
                    "project_id": "client",
                    "animation": "nod",
                    "fps": 6,
                    "size": 128,
                    "formats": ["webp", "apng", "gif", "spritesheet"],
                }
            },
        )
    )
    for _ in range(200):
        job = payload(await session.call_tool("render_status", {"run_id": job["run_id"]}))
        if job["status"] in ("complete", "failed"):
            break
        await asyncio.sleep(0.05)
    assert job["status"] == "complete", job
    assert job["frame_count"] == 7 and job["seconds"] == 1
    blocked = await session.call_tool("export_animations", {"run_ids": [job["run_id"]]})
    assert blocked.isError
    inspected = await session.call_tool("inspect_frames", {"run_id": job["run_id"], "frames": [0, 3, 6]})
    assert any(c.type == "image" for c in inspected.content)
    evidence = payload(inspected)
    # Keep real evidence honestly unapproved: this test exercises API data, not visual quality.
    recorded = payload(
        await session.call_tool(
            "record_frame_checks",
            {
                "run_id": job["run_id"],
                "checks": [
                    {
                        "frame": f["frame"],
                        "sha256": f["sha256"],
                        "result": "uncertain",
                        "notes": "Transport test only; no visual assessment performed.",
                    }
                    for f in evidence["frames"]
                ],
            },
        )
    )
    assert recorded["reviewed_frames"] == 3 and not recorded["visual_review_passed"]
    draft = payload(
        await session.call_tool("export_animations", {"run_ids": [job["run_id"]], "require_reviewed": False})
    )
    with zipfile.ZipFile(workspace / draft["bundle"]) as z:
        assert z.testzip() is None
        assert json.loads(z.read("manifest.json"))["visual_review_passed"] is False
    chunk = payload(await session.call_tool("read_artifact_bytes", {"path": draft["bundle"], "length": 4}))
    assert base64.b64decode(chunk["data_base64"]) == b"PK\x03\x04"
    assert (await session.call_tool("read_artifact_bytes", {"path": "../../outside"})).isError


def test_ai_stdio(tmp_path):
    async def run():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "motionforge.ai_server", "--workspace", str(tmp_path)],
            env={**os.environ, "PYTHONUTF8": "1", "SPINE_EXECUTABLE": "DOES_NOT_EXIST.exe"},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await exercise(session, tmp_path)

    asyncio.run(run())


def test_ai_http_has_no_gui(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "motionforge.ai_server",
            "--transport",
            "http",
            "--port",
            str(port),
            "--workspace",
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env={**os.environ, "SPINE_EXECUTABLE": "DOES_NOT_EXIST.exe"},
    )
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/", timeout=0.5).status_code == 404:
                    break
            except httpx.HTTPError:
                pass
            if process.poll() is not None:
                raise AssertionError(process.stderr.read().decode())
            time.sleep(0.1)
        else:
            raise AssertionError("AI HTTP server did not start")
        assert httpx.get(url + "/studio").status_code == 404
        assert httpx.get(url + "/api/state").status_code == 404

        async def run():
            async with httpx.AsyncClient(timeout=60) as client:
                async with streamable_http_client(url + "/mcp", http_client=client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await exercise(session, tmp_path)

        asyncio.run(run())
    finally:
        process.terminate()
        process.wait(timeout=10)
        process.stderr.close()
