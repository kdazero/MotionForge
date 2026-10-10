import math

import pytest

from motionforge.render import transform
from motionforge.rigid_skinning import rigid_blend_point
from motionforge.storage import MotionError


def test_bent_elbow_preserves_cross_section_width():
    transforms = [(transform(), 0.5), (transform(rotation=120), 0.5)]
    a = rigid_blend_point((-10, 0), transforms)
    b = rigid_blend_point((10, 0), transforms)
    assert math.dist(a, b) == pytest.approx(20)
    assert a == pytest.approx((-5, -math.sqrt(75)))


def test_single_bone_rotation_and_translation():
    assert rigid_blend_point((10, 20), [(transform(3, 5, 90), 1)]) == pytest.approx((-17, 15))


def test_rejects_character_scaling():
    with pytest.raises(MotionError, match="unscaled"):
        rigid_blend_point((1, 2), [(transform(sx=1.1), 1)])


def test_angles_crossing_pi_take_short_path():
    p = rigid_blend_point((10, 0), [(transform(rotation=179), 0.5), (transform(rotation=-179), 0.5)])
    assert p == pytest.approx((-10, 0), abs=1e-6)
