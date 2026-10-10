"""Planar dual-quaternion skinning for artwork with fixed limb proportions.

Unlike a linear average of matrices, the blended rotation remains orthogonal.
The caller supplies bind-world points and current * inverse-bind transforms.
"""

import math

from .storage import MotionError


def rigid_blend_point(position, influences):
    rw = rz = dx = dy = 0.0
    reference = None
    total = 0.0
    for matrix, weight in influences:
        a, b, tx, c, d, ty = matrix
        if (
            abs(a * a + c * c - 1) > 1e-5
            or abs(b * b + d * d - 1) > 1e-5
            or abs(a * b + c * d) > 1e-5
            or a * d - b * c < 0
        ):
            raise MotionError("Rigid skinning requires unscaled, unsheared bones.")
        angle = math.atan2(c, a) / 2
        w, z = math.cos(angle), math.sin(angle)
        if reference is None:
            reference = (w, z)
        if reference[0] * w + reference[1] * z < 0:
            w, z = -w, -z
        rw += weight * w
        rz += weight * z
        dx += weight * (tx * w + ty * z) / 2
        dy += weight * (ty * w - tx * z) / 2
        total += weight
    norm = math.hypot(rw, rz)
    if norm < 1e-8 or abs(total - 1) > 1e-5:
        raise MotionError("Invalid rigid skinning weights.")
    w, z, dx, dy = rw / norm, rz / norm, dx / norm, dy / norm
    x, y = position
    return (
        (w * w - z * z) * x - 2 * w * z * y + 2 * (dx * w - dy * z),
        2 * w * z * x + (w * w - z * z) * y + 2 * (dy * w + dx * z),
    )
