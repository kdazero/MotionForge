import copy

import numpy as np
import pytest
from PIL import Image

from motionforge.software_renderer import SoftwareRenderer, draw_order, timeline
from motionforge.storage import MotionError


def character(tmp_path, alpha=255):
    (tmp_path / "images").mkdir(exist_ok=True)
    Image.new("RGBA", (16, 16), (255, 0, 0, alpha)).save(tmp_path / "images/red.png")
    return dict(
        skeleton={"spine": "3.8.75"},
        bones=[{"name": "root"}],
        slots=[{"name": "s", "bone": "root", "attachment": "a"}],
        skins=[
            {
                "name": "default",
                "attachments": {
                    "s": {
                        "a": dict(
                            type="mesh",
                            path="red",
                            uvs=[0, 0, 1, 0, 1, 1, 0, 1],
                            vertices=[-1, 1, 1, 1, 1, -1, -1, -1],
                            triangles=[0, 1, 2, 0, 2, 3],
                        )
                    }
                },
            }
        ],
        animations={"move": {"bones": {"root": {"translate": [{"time": 0, "x": 0}, {"time": 1, "x": 1}]}}}},
    )


def test_mesh_shared_edge_and_premultiplied_alpha(tmp_path):
    data = character(tmp_path, 128)
    r = SoftwareRenderer(data, tmp_path, "move")
    im = np.array(r.frame(0, 128, r.camera([-2, -2, 2, 2], 128), 2))
    # A shared triangle diagonal must not create a crack or double-composite alpha.
    assert np.all(im[45:85, 45:85, 3] == 128)
    assert np.all(im[45:85, 45:85, 0] == 255)
    assert np.all(im[:8, :, 3] == 0)


def test_transparent_folded_mesh_surface_does_not_erase_lower_surface(tmp_path):
    data = character(tmp_path)
    pixels = np.zeros((16, 32, 4), dtype=np.uint8)
    pixels[:, :16] = (255, 0, 0, 255)
    Image.fromarray(pixels).save(tmp_path / "images/red.png")
    a = data["skins"][0]["attachments"]["s"]["a"]
    a.update(
        uvs=[0, 0, 0.45, 0, 0, 1, 0.55, 0, 1, 0, 0.55, 1],
        vertices=[-1, 1, 1, 1, -1, -1] * 2,
        triangles=[0, 1, 2, 3, 4, 5],
    )
    r = SoftwareRenderer(data, tmp_path, "move")
    frame = r.frame(0, 128, r.camera([-2, -2, 2, 2], 128), 2)
    assert frame.getpixel((50, 50)) == (255, 0, 0, 255)


def test_folded_translucent_surface_blends_in_triangle_order(tmp_path):
    data = character(tmp_path)
    pixels = np.zeros((16, 32, 4), dtype=np.uint8)
    pixels[:, :16] = (255, 0, 0, 255)
    pixels[:, 16:] = (0, 0, 255, 128)
    Image.fromarray(pixels).save(tmp_path / "images/red.png")
    a = data["skins"][0]["attachments"]["s"]["a"]
    a.update(
        uvs=[0, 0, 0.45, 0, 0, 1, 0.55, 0, 1, 0, 0.55, 1],
        vertices=[-1, 1, 1, 1, -1, -1] * 2,
        triangles=[0, 1, 2, 3, 4, 5],
    )
    r = SoftwareRenderer(data, tmp_path, "move")
    assert r.frame(0, 128, r.camera([-2, -2, 2, 2], 128), 2).getpixel((50, 50)) == (127, 0, 128, 255)


def test_weighted_skinning_and_deform(tmp_path):
    data = character(tmp_path)
    data["bones"].append({"name": "child", "parent": "root", "x": 10})
    a = data["skins"][0]["attachments"]["s"]["a"]
    a["vertices"] = [
        value for x, y in [(-1, 1), (1, 1), (1, -1), (-1, -1)] for value in [2, 0, x, y, 0.5, 1, x, y, 0.5]
    ]
    data["animations"]["move"] = {
        "bones": {"child": {"translate": [{"time": 0, "y": 0}, {"time": 1, "y": 10}]}},
        "deform": {"default": {"s": {"a": [{"time": 0}, {"time": 1, "vertices": [2, 0] * 8}]}}},
    }
    r = SoftwareRenderer(data, tmp_path, "move")
    np.testing.assert_allclose(r.pose(1)[0][3], [[6, 6], [8, 6], [8, 4], [6, 4]])
    np.testing.assert_allclose(r.pose(0.5)[0][3][0], [5, 3.5])


def test_draw_order_attachment_and_color(tmp_path):
    data = character(tmp_path)
    Image.new("RGBA", (16, 16), "blue").save(tmp_path / "images/blue.png")
    data["slots"].append({"name": "over", "bone": "root", "attachment": "b"})
    data["skins"][0]["attachments"]["over"] = {"b": dict(path="blue", width=2, height=2)}
    data["animations"]["move"] = {
        "drawOrder": [{"time": 0}, {"time": 0.5, "offsets": [{"slot": "over", "offset": -1}]}],
        "slots": {"s": {"color": [{"time": 0, "color": "ffffffff"}, {"time": 1, "color": "ffffff00"}]}},
    }
    r = SoftwareRenderer(data, tmp_path, "move")
    cam = r.camera([-2, -2, 2, 2], 128)
    assert r.frame(0, 128, cam).getpixel((64, 64)) == (0, 0, 255, 255)
    px = r.frame(0.5, 128, cam).getpixel((64, 64))
    assert px[0] in (127, 128) and px[2] in (127, 128)
    assert r.frame(1, 128, cam).getpixel((64, 64)) == (0, 0, 255, 255)
    assert [s["name"] for s in draw_order(data["slots"], [])] == ["s", "over"]


def test_reject_unsupported_and_malformed(tmp_path):
    data = character(tmp_path)
    bad = copy.deepcopy(data)
    bad["ik"] = [{"name": "leg"}]
    with pytest.raises(MotionError, match="does not support"):
        SoftwareRenderer(bad, tmp_path, "move")
    bad = copy.deepcopy(data)
    bad["skins"][0]["attachments"]["s"]["a"]["triangles"] = [0, 1, 50]
    with pytest.raises(MotionError, match="triangle"):
        SoftwareRenderer(bad, tmp_path, "move")
    bad = copy.deepcopy(data)
    bad["animations"]["move"]["slots"] = {"s": {"attachment": [{"time": 0.4, "name": "missing"}]}}
    with pytest.raises(MotionError, match="Missing attachment"):
        SoftwareRenderer(bad, tmp_path, "move")
    assert timeline({"bones": {"root": {"rotate": [{"time": 0.11}]}}}, 30) == [0, 1 / 30, 2 / 30, 0.1, 0.11]
