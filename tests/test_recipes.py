import copy

import pytest

from motionforge.ai_service import AIService
from motionforge.recipes import (
    apply_recipe,
    get_recipe,
    instantiate_recipe,
    load_recipe,
    verify_recipe,
)
from motionforge.software_renderer import SoftwareRenderer, timeline
from motionforge.storage import MotionError

RECIPE = "female_gestures_v1"


def test_complete_offline_recipe_preserves_fingers_timing_and_pixels(tmp_path):
    ai = AIService(tmp_path)
    created = instantiate_recipe(ai, RECIPE, "copy")
    assert created["compatible"] and all(created["exact_actions"].values())
    assert not created["visual_review_passed"]
    source, manifest, original = load_recipe(RECIPE)
    folder, _, reproduced = ai.service._load("copy")
    assert len(list((folder / "images").glob("*.png"))) == manifest["part_count"] == 31
    assert (tmp_path / created["hand_reference_path"]).is_file()
    assert len(manifest["references"]) == 10
    wave = reproduced["animations"]["wave"]
    think = reproduced["animations"]["think"]
    assert len(timeline(wave, 30)) == 111 and len(timeline(think, 30)) == 145
    assert len(wave["slots"]["hand_right"]["attachment"]) == 13
    assert think["slots"]["hand_left"]["attachment"] == [
        {"name": "hand_left"},
        {"time": 0.5, "name": "hand_think_loose"},
        {"time": 1.12, "name": "hand_think_closed"},
        {"time": 3.49, "name": "hand_think_loose"},
        {"time": 4.06, "name": "hand_left"},
    ]
    for name, times in {"wave": [0.4, 0.5, 3.2, 3.4], "think": [0.5, 1.12, 3.49, 4.06]}.items():
        a = SoftwareRenderer(original, source, name)
        b = SoftwareRenderer(reproduced, folder, name)
        camera = a.camera(manifest["render_defaults"]["bounds"], 128)
        for t in times:
            assert a.frame(t, 128, camera).tobytes() == b.frame(t, 128, camera).tobytes()
    with pytest.raises(MotionError, match="already exists"):
        instantiate_recipe(ai, RECIPE, "copy")


def test_restore_revision_rejects_wrong_rig_missing_hand_and_stale_edit(tmp_path):
    ai = AIService(tmp_path)
    instantiate_recipe(ai, RECIPE, "actor")
    old = ai.inspect("actor")["revision"]
    ai.retime("actor", "wave", 2)
    assert not verify_recipe(ai, "actor", RECIPE)["exact_actions"]["wave"]
    with pytest.raises(MotionError, match="Character changed"):
        apply_recipe(ai, "actor", RECIPE, old, ["wave"], True)
    current = ai.inspect("actor")["revision"]
    with pytest.raises(MotionError, match="already exists"):
        apply_recipe(ai, "actor", RECIPE, current, ["wave"])
    apply_recipe(ai, "actor", RECIPE, current, ["wave"], True)
    assert all(verify_recipe(ai, "actor", RECIPE)["exact_actions"].values())
    folder, project, data = ai.service._load("actor")
    original = copy.deepcopy(data)
    data["bones"][1]["x"] += 1
    ai.service._commit(folder, project, data, "Different character proportions")
    current = ai.inspect("actor")["revision"]
    with pytest.raises(MotionError, match="requires the packaged rig"):
        apply_recipe(ai, "actor", RECIPE, current, ["think"], True)
    assert ai.inspect("actor")["revision"] == current
    folder, project, _ = ai.service._load("actor")
    ai.service._commit(folder, project, original, "Restore rig for missing-asset test")
    (folder / "images/hand_think_closed.png").unlink()
    current = ai.inspect("actor")["revision"]
    assert not verify_recipe(ai, "actor", RECIPE)["compatible"]
    with pytest.raises(MotionError, match="hand_think_closed"):
        apply_recipe(ai, "actor", RECIPE, current, ["think"], True)
    assert ai.inspect("actor")["revision"] == current


def test_recipe_input_paths_and_tamper_are_rejected(tmp_path, monkeypatch):
    import shutil

    from motionforge import recipes

    ai = AIService(tmp_path / "workspace")
    with pytest.raises(MotionError):
        get_recipe("../outside")
    with pytest.raises(MotionError):
        instantiate_recipe(ai, RECIPE, "../outside")
    local = tmp_path / "package"
    shutil.copytree(recipes.RECIPE_ROOT, local)
    monkeypatch.setattr(recipes, "RECIPE_ROOT", local)
    (local / RECIPE / "images/hand_turn_5.png").write_bytes(b"changed")
    with pytest.raises(MotionError, match="Recipe file changed"):
        instantiate_recipe(ai, RECIPE, "bad")
    assert not (ai.workspace / "projects/bad").exists()


def test_rounded_native_endpoint_does_not_add_a_held_frame():
    def animation(seconds):
        return {"bones": {"root": {"rotate": [{"time": seconds}]}}}

    times = timeline(animation(3.6667), 30)
    assert len(times) == 111 and times[-1] == 3.6667
    assert times[-1] - times[-2] > 0.033
    assert timeline(animation(0.1002), 30) == [0, 1 / 30, 2 / 30, 0.1, 0.1002]
    assert timeline(animation(0.00001), 30) == [0, 0.00001]
