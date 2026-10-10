import json
import time
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from motionforge.ai_service import AIService, RenderSpec, VisualCheck
from motionforge.motion import Bone, Layer
from motionforge.storage import MotionError, read_json


def test_progress_read_retries_sharing_violation_but_not_permanent_access_denial(tmp_path, monkeypatch):
    from motionforge import storage

    path = tmp_path / "job.json"
    path.write_text('{"status": "complete"}', encoding="utf-8")
    original = Path.read_text
    attempts = []

    def briefly_locked(file, *args, **kwargs):
        attempts.append(1)
        if len(attempts) <= 2:
            raise PermissionError("Sharing violation during replacement")
        return original(file, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", briefly_locked)
    monkeypatch.setattr(storage.time, "sleep", lambda _: None)
    assert read_json(path) == {"status": "complete"}
    assert len(attempts) == 3

    def inaccessible(*args, **kwargs):
        attempts.append(1)
        raise PermissionError("Persistent access denial")

    attempts.clear()
    monkeypatch.setattr(Path, "read_text", inaccessible)
    with pytest.raises(PermissionError, match="Persistent"):
        read_json(path)
    assert len(attempts) == 8


def test_atomic_progress_update_survives_brief_reader_lock(tmp_path, monkeypatch):
    from motionforge import storage

    path = tmp_path / "job.json"
    storage.write_json(path, {"status": "queued"})
    replace = storage.os.replace
    attempts = []

    def temporary_lock(source, destination):
        attempts.append(1)
        if len(attempts) <= 2:
            assert storage.read_json(path) == {"status": "queued"}
            raise PermissionError("Windows reader still has file open")
        replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", temporary_lock)
    storage.write_json(path, {"status": "complete"})
    assert storage.read_json(path) == {"status": "complete"}


def wait(ai, ident):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        r = ai.status(ident)
        if r["status"] in ("failed", "complete"):
            assert r["status"] == "complete", r
            return r
        time.sleep(0.02)
    pytest.fail("Renderer did not finish")


def test_headless_create_retime_render_review_export(tmp_path, monkeypatch):
    ai = AIService(tmp_path)
    img = tmp_path / "inbox/part.png"
    Image.new("RGBA", (48, 80), "#4dcca8").save(img)
    ai.service.create_rig(
        "ai", [Bone(name="root")], [Layer(name="body", image="inbox/part.png", bone="root")]
    )
    animation = {
        "bones": {
            "root": {"rotate": [{"time": 0, "angle": 0}, {"time": 0.5, "angle": 15}, {"time": 1, "angle": 0}]}
        },
        "slots": {"body": {"attachment": [{"time": 0, "name": "body"}, {"time": 1, "name": "body"}]}},
        "drawOrder": [{"time": 0.6}],
    }
    ai.put_animation("ai", "nod", animation)
    before = ai.inspect("ai")["revision"]
    ai.retime("ai", "nod", 2, "nod_fast")
    after = ai.inspect("ai")
    assert after["revision"] != before and after["actions"]["nod_fast"] == 0.5
    assert after["data"]["animations"]["nod_fast"]["drawOrder"][0]["time"] == 0.3
    assert after["data"]["animations"]["nod_fast"]["slots"]["body"]["attachment"][1]["time"] == 0.5
    job = ai.start(
        RenderSpec(
            project_id="ai", animation="nod", size=128, fps=8, formats=["webp", "apng", "gif", "spritesheet"]
        )
    )
    r = wait(ai, job["run_id"])
    assert r["frame_count"] == 9 and not r["visual_review_passed"]
    with pytest.raises(MotionError, match="unreviewed"):
        ai.export([job["run_id"]])
    folder = ai._folder(job["run_id"])
    report = read_json(folder / "render.json")
    first = VisualCheck(
        frame=0,
        sha256=report["frames"][0]["sha256"],
        result="pass",
        notes="Synthetic test fixture assessment",
    )
    with pytest.raises(MotionError, match="Inspect"):
        ai.record_checks(job["run_id"], [first])
    ai.inspect_frames(job["run_id"], [0], (0, 0, 32, 32))
    with pytest.raises(MotionError, match="Inspect"):
        ai.record_checks(job["run_id"], [first])
    frames = ai.inspect_frames(job["run_id"], list(range(9)))["frames"]
    # Synthetic fixture only: test review-state transitions, not production art approval.
    result = ai.record_checks(
        job["run_id"],
        [
            VisualCheck(
                frame=f["frame"], sha256=f["sha256"], result="pass", notes="Synthetic test fixture assessment"
            )
            for f in frames
        ],
    )
    assert result["visual_review_passed"]
    exported = ai.export([job["run_id"]])
    assert not exported["requires_spine"]
    with zipfile.ZipFile(tmp_path / exported["bundle"]) as z:
        assert z.testzip() is None
        assert json.loads(z.read("manifest.json"))["visual_review_passed"]
        assert "source/character.json" in z.namelist()
    with Image.open(folder / "animation.png") as im:
        total = 0
        for i in range(im.n_frames):
            im.seek(i)
            total += im.info["duration"]
        assert total == 1000
    with Image.open(folder / "animation.webp") as im:
        assert im.getpixel((0, 0))[3] == 0
    (folder / "animation.webp").write_bytes(b"tampered")
    with pytest.raises(MotionError, match="artifact changed"):
        ai.export([job["run_id"]])


def test_snapshot_is_immutable_when_project_is_edited(tmp_path):
    ai = AIService(tmp_path)
    ai.service.create_demo("robot")
    ai.service.add_preset("robot", "idle")
    job = ai.start(RenderSpec(project_id="robot", animation="idle", size=128, fps=4))
    wait(ai, job["run_id"])
    ai.retime("robot", "idle", 2)
    report = read_json(ai._folder(job["run_id"]) / "render.json")
    assert report["seconds"] == 2.4 and ai.inspect("robot")["actions"]["idle"] == 1.2
    draft = ai.export([job["run_id"]], False)
    assert not draft["visual_review_passed"]
    with pytest.raises(MotionError):
        ai._folder("../../outside")
