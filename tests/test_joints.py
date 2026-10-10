import hashlib

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from motionforge.ai_assets import PartMask, extract_part
from motionforge.fidelity import lock_fidelity, validate_fidelity
from motionforge.joints import (
    JointRegistration,
    JointStrip,
    joint_strip,
    ordered_slots,
    register_joint,
    texture_effects,
)
from motionforge.render import point, transform
from motionforge.software_renderer import SoftwareRenderer
from motionforge.storage import MotionError


@pytest.mark.parametrize("edges", [[[-12, 5], [18, 5]], [[20, -8], [20, 22]], [[18, 5], [-12, 5]]])
def test_wrist_edges_register_despite_padding_rotation_and_hand_orientation(edges):
    image = Image.new("RGBA", (230, 370), "#ecd0bb")
    spec = JointRegistration(source_edges=((93, 45), (153, 45)), target_edges=edges)
    region, result = register_joint(dict(width=230, height=370), image, spec)
    matrix = transform(region["x"], region["y"], region["rotation"], region["scaleX"], region["scaleY"])
    for source, target in zip(spec.source_edges, edges):
        actual = point(matrix, source[0] - image.width / 2, image.height / 2 - source[1])
        np.testing.assert_allclose(actual, target, atol=1e-8)
    assert result["anchor_error"] == 0


def test_skin_sampling_calibrates_rendered_rgb_without_editing_source_or_alpha():
    source = Image.new("RGBA", (16, 16), (250, 214, 180, 255))
    reference = Image.new("RGBA", (16, 16), (228, 196, 173, 255))
    before = hashlib.sha256(source.tobytes()).hexdigest()
    spec = JointRegistration(
        source_edges=((3, 5), (13, 5)),
        target_edges=((-5, 0), (5, 0)),
        source_sample=(4, 4, 8, 8),
        reference_slot="arm",
        reference_attachment="arm",
        reference_sample=(4, 4, 8, 8),
    )
    region, report = register_joint({}, source, spec, reference)
    corrected = texture_effects(np.asarray(source, dtype=np.float32) / 255, region)
    np.testing.assert_allclose(corrected[5, 5, :3] * 255, [228, 196, 173], atol=0.001)
    assert corrected[5, 5, 3] == 1 and report["median_error_before"] > 20
    assert hashlib.sha256(source.tobytes()).hexdigest() == before


@pytest.mark.parametrize("color", [(240, 200, 160, 0), (0, 0, 0, 255)])
def test_bad_color_reference_fails_instead_of_guessing(color):
    image = Image.new("RGBA", (16, 16), "#f0c8a0")
    spec = JointRegistration(
        source_edges=((3, 5), (13, 5)),
        target_edges=((-5, 0), (5, 0)),
        source_sample=(4, 4, 8, 8),
        reference_slot="arm",
        reference_attachment="arm",
        reference_sample=(4, 4, 8, 8),
    )
    with pytest.raises(MotionError, match="opaque|dark"):
        register_joint({}, image, spec, Image.new("RGBA", (16, 16), color))


def test_root_feather_has_no_black_fringe_and_preserves_tip():
    texture = np.ones((40, 12, 4), dtype=np.float32)
    texture[:, :, :3] = [0.9, 0.7, 0.6]
    result = texture_effects(texture, {"rootFade": {"origin": [6, 10], "direction": [0, 1], "width": 12}})
    assert result[0, 6, 3] == 0 and result[30, 6, 3] == 1
    assert 0.4 < result[10, 6, 3] < 0.6
    np.testing.assert_array_equal(result[:, :, :3], texture[:, :, :3])
    np.testing.assert_array_equal(texture[:, :, 3], 1)


def test_semantic_layers_are_stable_and_reject_cycles():
    slots = [{"name": n} for n in ("body", "hand", "head", "hat")]
    assert [s["name"] for s in ordered_slots(slots, [("head", "hand")])] == ["body", "head", "hand", "hat"]
    with pytest.raises(MotionError, match="cycle"):
        ordered_slots(slots, [("head", "hand"), ("hand", "head")])
    with pytest.raises(MotionError, match="existing"):
        ordered_slots(slots, [("face", "hand")])


def limb(tmp_path):
    (tmp_path / "images").mkdir(exist_ok=True)
    image = Image.new("RGBA", (40, 180))
    ImageDraw.Draw(image).rounded_rectangle((9, 2, 30, 177), radius=10, fill=(232, 198, 170, 255))
    image.save(tmp_path / "images/skin.png")
    return dict(
        skeleton={"spine": "3.8.75"},
        bones=[{"name": "upper"}, {"name": "lower", "parent": "upper", "y": -90}],
        slots=[{"name": "skin", "bone": "upper", "attachment": "skin"}],
        skins=[
            {
                "name": "default",
                "attachments": {"skin": {"skin": {"path": "skin", "width": 40, "height": 180, "y": -90}}},
            }
        ],
        animations={"bend": {"bones": {"lower": {"rotate": [{"time": 0}, {"time": 1, "angle": 150}]}}}},
    )


def test_continuous_joint_renders_connected_skin_through_deep_bend(tmp_path):
    data = limb(tmp_path)
    updated = joint_strip(
        data,
        tmp_path,
        JointStrip(
            slot="skin",
            attachment="skin",
            parent_bone="upper",
            child_bone="lower",
            start=(20, 0),
            end=(20, 179),
            blend_width=50,
        ),
    )
    assert data["skins"][0]["attachments"]["skin"]["skin"].get("type", "region") == "region"
    renderer = SoftwareRenderer(updated, tmp_path, "bend")
    camera = renderer.camera([-110, -190, 110, 30], 256)
    for t in (0, 0.25, 0.5, 0.75, 1):
        alpha = np.array(renderer.frame(t, 256, camera))[:, :, 3]
        count, labels, stats, centers = cv2.connectedComponentsWithStats((alpha > 200).astype(np.uint8))
        assert sum(area > 3 for area in stats[1:, cv2.CC_STAT_AREA]) == 1
        assert alpha.max() == 255
        count, holes, stats, centers = cv2.connectedComponentsWithStats((alpha < 20).astype(np.uint8))
        outside = set(holes[0]) | set(holes[-1]) | set(holes[:, 0]) | set(holes[:, -1])
        assert not [i for i in range(1, count) if i not in outside and stats[i, cv2.CC_STAT_AREA] > 1]


def test_layer_rule_overrides_animated_face_occlusion_at_all_keys(tmp_path):
    data = limb(tmp_path)
    Image.new("RGBA", (40, 180), (20, 30, 180, 255)).save(tmp_path / "images/face.png")
    data["slots"].append({"name": "face", "bone": "upper", "attachment": "face"})
    data["skins"][0]["attachments"]["face"] = {"face": {"path": "face", "width": 40, "height": 180, "y": -90}}
    data["layerConstraints"] = [["face", "skin"]]
    data["animations"]["bend"]["drawOrder"] = [
        {"time": 0, "offsets": []},
        {"time": 0.5, "offsets": [{"slot": "skin", "offset": 1}]},
    ]
    renderer = SoftwareRenderer(data, tmp_path, "bend")
    for t in (0, 0.49, 0.5, 1):
        assert [p[0] for p in renderer.pose(t)] == ["face", "skin"]
        image = renderer.frame(t, 128, renderer.camera([-60, -190, 60, 10], 128))
        assert image.getpixel((64, 64))[:3] == (232, 198, 170)


def test_same_texture_different_calibration_does_not_leak_between_attachments(tmp_path):
    data = limb(tmp_path)
    data["slots"].append({"name": "second", "bone": "upper", "attachment": "second"})
    base = data["skins"][0]["attachments"]["skin"]["skin"]
    data["skins"][0]["attachments"]["second"] = {"second": {**base, "rgbGain": [0.8, 0.8, 0.8]}}
    renderer = SoftwareRenderer(data, tmp_path, "bend")
    a = renderer.parts[("skin", "skin")]["texture"][90, 20]
    b = renderer.parts[("second", "second")]["texture"][90, 20]
    np.testing.assert_allclose(b[:3], a[:3] * 0.8)
    assert b[3] == a[3] == 1


def test_clothing_cutout_rejects_missing_required_edge_before_rigging(tmp_path):
    image = Image.new("RGBA", (100, 100), (20, 85, 93, 255))
    image.save(tmp_path / "vest.png")
    spec = dict(name="vest", pivot=(50, 10), required_polygons=[[(30, 20), (80, 20), (80, 70), (30, 70)]])
    with pytest.raises(MotionError, match="required opaque pixels"):
        extract_part(tmp_path, "vest.png", PartMask(**spec, polygon=[(20, 10), (60, 10), (60, 80), (20, 80)]))
    result = extract_part(
        tmp_path, "vest.png", PartMask(**spec, polygon=[(20, 10), (90, 10), (90, 80), (20, 80)])
    )
    with Image.open(tmp_path / result["path"]) as cut:
        assert cut.getpixel((80 - result["crop_box"][0], 40 - result["crop_box"][1]))[3] == 255


def test_detached_skirt_fragment_is_rejected_for_hand_registration():
    image = Image.new("RGBA", (100, 100))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 40, 90), fill="#edd2bc")
    draw.rectangle((70, 70, 78, 78), fill="#242b41")
    spec = JointRegistration(source_edges=((10, 20), (40, 20)), target_edges=((-15, 0), (15, 0)))
    with pytest.raises(MotionError, match="detached"):
        register_joint({}, image, spec)


def test_occlusion_constraints_are_part_of_identity_lock(tmp_path):
    data = limb(tmp_path)
    locked = lock_fidelity(data, tmp_path, [-110, -190, 110, 30])
    locked["layerConstraints"] = [["skin", "another"]]
    with pytest.raises(MotionError, match="layer constraints"):
        validate_fidelity(locked, tmp_path, locked["animations"]["bend"])


def test_forbidden_owner_region_rejects_connected_sleeve_remnant(tmp_path):
    image = Image.new("RGBA", (100, 100))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 60, 90), fill="#15515a")
    draw.rectangle((61, 10, 68, 80), fill="#f4e2d0")
    image.save(tmp_path / "torso.png")
    fields = dict(
        name="torso",
        pivot=(40, 40),
        polygon=[(8, 8), (72, 8), (72, 94), (8, 94)],
        required_polygons=[[(15, 15), (59, 15), (59, 88), (15, 88)]],
        forbidden_polygons=[[(64, 15), (67, 15), (67, 78), (64, 78)]],
    )
    with pytest.raises(MotionError, match="forbidden pixels"):
        extract_part(tmp_path, "torso.png", PartMask(**fields))
    cut = extract_part(
        tmp_path,
        "torso.png",
        PartMask(**fields, excluded_polygons=[[(61, 0), (99, 0), (99, 99), (61, 99)]]),
    )
    assert cut["size"][0] <= 54


@pytest.mark.parametrize("reverse", [False, True])
def test_joint_mesh_preserves_slanted_cuff_hull_corners_in_setup_pose(tmp_path, reverse):
    data = limb(tmp_path)
    image = Image.new("RGBA", (40, 180))
    ImageDraw.Draw(image).polygon(
        [(29, 3), (31, 16), (34, 147), (27, 173), (11, 169), (7, 30), (12, 9)],
        fill="#e8c6aa",
    )
    image.save(tmp_path / "images/skin.png")
    ends = [(20, 0), (20, 179)]
    if reverse:
        ends.reverse()
    updated = joint_strip(
        data,
        tmp_path,
        JointStrip(
            slot="skin",
            attachment="skin",
            parent_bone="upper",
            child_bone="lower",
            start=ends[0],
            end=ends[1],
            blend_width=50,
            rows=8,
        ),
    )
    before = SoftwareRenderer(data, tmp_path, "bend")
    after = SoftwareRenderer(updated, tmp_path, "bend")
    camera = before.camera([-50, -190, 50, 10], 512)
    expected = np.array(before.frame(0, 512, camera))[:, :, 3]
    actual = np.array(after.frame(0, 512, camera))[:, :, 3]
    interior = cv2.erode((expected >= 250).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    assert actual[interior].min() >= 245
    # Subpixel endpoint rasterization may differ, but no opaque interior may
    # disappear and the total silhouette may lose at most 0.1% at its boundary.
    assert abs(int((actual > 128).sum()) - int((expected > 128).sum())) <= (expected > 128).sum() * 0.001
    mesh = updated["skins"][0]["attachments"]["skin"]["skin"]
    assert len(mesh["uvs"]) <= 480
