import math

import pytest
from pydantic import ValidationError

from motionforge.mesh import MeshSpec, MeshVertex, bind_region
from motionforge.motion import Track, build_tracks
from motionforge.render import point, sample, worlds
from motionforge.storage import MotionError


def rig():
    return {
        "skeleton": {"spine": "3.8.75"},
        "bones": [
            {"name": "root"},
            {"name": "arm", "parent": "root", "x": 12, "y": 30, "rotation": -60},
            {"name": "forearm", "parent": "arm", "x": 80, "rotation": 20},
        ],
        "slots": [{"name": "sleeve", "bone": "arm", "attachment": "sleeve"}],
        "skins": [
            {
                "name": "default",
                "attachments": {"sleeve": {"sleeve": {"width": 100, "height": 40, "x": 50, "y": 0}}},
            }
        ],
    }


def mesh():
    return MeshSpec(
        slot="sleeve",
        attachment="sleeve",
        hull=4,
        triangles=[(0, 1, 2), (0, 2, 3)],
        vertices=[
            {"u": u, "v": v, "weights": {"arm": 0.4, "forearm": 0.6}}
            for u, v in [(0, 0), (1, 0), (1, 1), (0, 1)]
        ],
    )


def test_weighted_mesh_preserves_setup_coordinates_with_rotated_parent():
    data = rig()
    result = bind_region(data, mesh())
    matrices = worlds(data, {}, 0)
    encoded = result["skins"][0]["attachments"]["sleeve"]["sleeve"]["vertices"]
    # Independent setup-pose reconstruction: every bound vertex must coincide
    # with the region corner, even though the two influences have different axes.
    offset = 0
    for x, y in [(0, 20), (100, 20), (100, -20), (0, -20)]:
        expected = point(matrices["arm"], x, y)
        count = encoded[offset]
        offset += 1
        actual = [0.0, 0.0]
        for _ in range(count):
            index, lx, ly, weight = encoded[offset : offset + 4]
            offset += 4
            world = point(matrices[data["bones"][index]["name"]], lx, ly)
            actual = [a + b * weight for a, b in zip(actual, world)]
        assert all(math.isclose(a, b, abs_tol=1e-5) for a, b in zip(actual, expected))
    assert "vertices" not in data["skins"][0]["attachments"]["sleeve"]["sleeve"]


def test_invalid_weight_and_degenerate_mesh_are_rejected():
    with pytest.raises(ValidationError, match="sum to 1"):
        MeshVertex(u=0, v=0, weights={"arm": 0.4})
    spec = mesh().model_dump()
    spec["triangles"] = [(0, 0, 2)]
    with pytest.raises(ValidationError, match="indices"):
        MeshSpec(**spec)
    data = rig()
    data["ik"] = [{"name": "unsupported-setup-constraint"}]
    with pytest.raises(MotionError, match="not supported"):
        bind_region(data, mesh())


def test_bezier_uses_native_38_format_and_has_no_terminal_curve():
    keys = [
        {"time": 0, "angle": 0, "curve": [0.2, 0, 0.8, 1]},
        {"time": 1, "angle": 90, "curve": [0.2, 0, 0.8, 1]},
    ]
    animation = build_tracks(rig(), [Track(bone="arm", channel="rotate", keys=keys)])
    actual = animation["bones"]["arm"]["rotate"]
    assert actual[0] == {"time": 0.0, "angle": 0.0, "curve": 0.2, "c2": 0.0, "c3": 0.8, "c4": 1.0}
    assert actual[1] == {"time": 1.0, "angle": 90.0}
    assert math.isclose(sample(actual, 0.5, {"angle": 0})["angle"], 45, abs_tol=1e-4)
