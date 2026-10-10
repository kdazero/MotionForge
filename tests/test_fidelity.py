import pytest
from PIL import Image

from motionforge.ai_service import AIService, RenderSpec
from motionforge.motion import Bone, Layer
from motionforge.storage import MotionError


@pytest.fixture
def locked(tmp_path):
    Image.new("RGBA", (20, 20), "red").save(tmp_path / "source.png")
    ai = AIService(tmp_path)
    ai.service.create_rig(
        "locked",
        [Bone(name="root"), Bone(name="arm", parent="root", x=10)],
        [Layer(name="art", image="source.png", bone="arm")],
    )
    ai.lock_identity("locked", [-30, -30, 30, 30])
    return ai


def test_proportion_lock_allows_rotation_but_rejects_scaling_and_bone_stretch(locked):
    locked.put_animation(
        "locked", "ok", {"bones": {"arm": {"rotate": [{"time": 0, "angle": 0}, {"time": 1, "angle": 50}]}}}
    )
    for channel, key in [("scale", {"x": 1.1, "y": 1}), ("translate", {"x": 4, "y": 0})]:
        with pytest.raises(MotionError, match="Fidelity lock"):
            locked.put_animation("locked", "bad", {"bones": {"arm": {channel: [{"time": 0, **key}]}}})


def test_camera_cannot_silently_refit_between_actions(locked):
    locked.put_animation(
        "locked", "ok", {"bones": {"arm": {"rotate": [{"time": 0}, {"time": 1, "angle": 20}]}}}
    )
    with pytest.raises(MotionError, match="camera bounds"):
        locked.start(RenderSpec(project_id="locked", animation="ok", bounds=[-40, -40, 40, 40]))


def test_changed_texture_rejected_before_animation_or_render(locked):
    folder, manifest, data = locked.service._load("locked")
    Image.new("RGBA", (20, 20), "blue").save(folder / "images/art.png")
    with pytest.raises(MotionError, match="source artwork changed"):
        locked.put_animation("locked", "bad", {})


def test_unknown_lock_exceptions_rejected(locked):
    with pytest.raises(MotionError, match="unknown bones"):
        locked.lock_identity("locked", [-30, -30, 30, 30], effect_bones=["anything"])
