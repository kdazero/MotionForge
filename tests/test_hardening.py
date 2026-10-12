import struct
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from motionforge.ai_server import build_ai_server
from motionforge.ai_service import AIService
from motionforge.gif_export import transparent_gif
from motionforge.motion import Bone, Layer
from motionforge.storage import MotionError


def rig(tmp_path, project="locked", lock=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (20, 20), "red").save(tmp_path / "source.png")
    ai = AIService(tmp_path)
    ai.service.create_rig(
        project,
        [Bone(name="root"), Bone(name="arm", parent="root", x=10)],
        [Layer(name="art", image="source.png", bone="arm")],
    )
    if lock:
        ai.lock_identity(project, [-30, -30, 30, 30])
    return ai


def tool(mcp, name):
    return mcp._tool_manager.get_tool(name).fn


def test_update_character_cannot_remove_or_bypass_identity_lock(tmp_path):
    ai = rig(tmp_path)
    mcp, _ = build_ai_server(tmp_path)
    current = ai.inspect("locked")
    stripped = dict(current["data"])
    stripped.pop("fidelity")
    stripped["bones"] = [dict(b) for b in stripped["bones"]]
    stripped["bones"][1]["x"] = 40
    with pytest.raises(MotionError, match="identity-locked"):
        tool(mcp, "update_character")("locked", current["revision"], stripped)
    stretched = dict(current["data"], bones=stripped["bones"])
    with pytest.raises(MotionError, match="Fidelity lock"):
        tool(mcp, "update_character")("locked", current["revision"], stretched)
    assert ai.inspect("locked")["revision"] == current["revision"]


def test_setup_edits_after_lock_are_rejected_before_creating_a_broken_revision(tmp_path):
    ai = rig(tmp_path)
    before = ai.inspect("locked")["revision"]
    images = sorted((tmp_path / "projects/locked/images").iterdir())
    with pytest.raises(MotionError, match="lock_identity again"):
        ai.register_attachment("locked", "art", "extra", "source.png")
    assert ai.inspect("locked")["revision"] == before
    assert sorted((tmp_path / "projects/locked/images").iterdir()) == images
    # Re-locking is an explicit decision and remains possible.
    unlocked = rig(tmp_path / "second", "open", lock=False)
    unlocked.register_attachment("open", "art", "extra", "source.png")
    unlocked.lock_identity("open", [-30, -30, 30, 30])


def test_identical_layer_constraints_survive_lock(tmp_path):
    ai = rig(tmp_path, lock=False)
    folder, manifest, data = ai.service._load("locked")
    data["slots"].append({"name": "front", "bone": "arm", "attachment": "art"})
    data["skins"][0]["attachments"]["front"] = {"art": dict(data["skins"][0]["attachments"]["art"]["art"])}
    revision = ai.service._commit(folder, manifest, data, "second slot")["revision"]
    revision = ai.set_layer_constraints("locked", revision, [("art", "front")])["revision"]
    revision = ai.lock_identity("locked", [-30, -30, 30, 30])["revision"]
    ai.set_layer_constraints("locked", revision, [("art", "front")])
    with pytest.raises(MotionError, match="layer constraints changed"):
        ai.set_layer_constraints("locked", ai.inspect("locked")["revision"], [("front", "art")])


def test_layer_names_differing_only_by_case_are_rejected(tmp_path):
    Image.new("RGBA", (8, 8), "red").save(tmp_path / "a.png")
    ai = AIService(tmp_path)
    with pytest.raises(MotionError, match="letter case"):
        ai.service.create_rig(
            "casey",
            [Bone(name="root")],
            [Layer(name="Hand", image="a.png", bone="root"), Layer(name="hand", image="a.png", bone="root")],
        )
    with pytest.raises(MotionError, match="reserved"):
        ai.service.create_rig("dev", [Bone(name="root")], [Layer(name="NUL", image="a.png", bone="root")])


def test_malformed_input_raises_actionable_errors(tmp_path):
    ai = rig(tmp_path, lock=False)
    mcp, _ = build_ai_server(tmp_path)
    with pytest.raises(MotionError):
        ai.put_animation("locked", "bad", {"bones": []})
    with pytest.raises(MotionError):
        ai.put_animation("locked", "bad", {"bones": {"arm": {"rotate": [5]}}})
    current = ai.inspect("locked")
    with pytest.raises(MotionError):
        tool(mcp, "update_character")("locked", current["revision"], {**current["data"], "skeleton": []})
    (tmp_path / "fake.png").write_bytes(b"not an image")
    (tmp_path / "folder.png").mkdir()
    for path in ("fake.png", "folder.png"):
        with pytest.raises(MotionError):
            tool(mcp, "inspect_image")(path)
    with pytest.raises(MotionError):
        ai.service.add_preset("locked", "idle", name="Wave 1")


def test_artifact_chunks_hash_the_file_once(tmp_path, monkeypatch):
    from motionforge import ai_server

    (tmp_path / "big.bin").write_bytes(bytes(600_000))
    mcp, _ = build_ai_server(tmp_path)
    calls = []
    real = ai_server.digest
    monkeypatch.setattr(ai_server, "digest", lambda p: calls.append(p) or real(p))
    read = tool(mcp, "read_artifact_bytes")
    offset, hashes = 0, set()
    while True:
        chunk = read("big.bin", offset)
        hashes.add(chunk["sha256"])
        offset = chunk["next_offset"]
        if chunk["eof"]:
            break
    assert len(calls) == 1 and len(hashes) == 1


def test_gif_transparent_index_is_inside_color_table(tmp_path):
    frames = []
    for i in range(3):
        im = Image.new("RGBA", (32, 32))
        ImageDraw.Draw(im).ellipse((4 + i, 4, 20 + i, 20), fill=(200, 50, 50, 255))
        frames.append(im)
    path = tmp_path / "a.gif"
    transparent_gif(frames, [100, 100, 100], path)
    data = path.read_bytes()
    table = 2 ** ((data[10] & 7) + 1)
    control = data.index(b"\x21\xf9\x04")
    assert struct.unpack("B", data[control + 6 : control + 7])[0] < table
    with Image.open(path) as gif:
        assert gif.convert("RGBA").getchannel("A").getextrema() == (0, 255)


def test_staging_folders_are_not_listed_as_characters(tmp_path):
    ai = rig(tmp_path, lock=False)
    ghost = Path(tmp_path / "projects" / "_staging_deadbeef")
    ghost.mkdir()
    (ghost / "project.json").write_text("{}", encoding="utf-8")
    assert [p["project_id"] for p in ai.service.list_projects()] == ["locked"]
