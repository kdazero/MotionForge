"""Matrix transforms and keyframe interpolation for the CPU renderer."""

import math

from .storage import MotionError

IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)


def multiply(a, b):
    return (
        a[0] * b[0] + a[1] * b[3],
        a[0] * b[1] + a[1] * b[4],
        a[0] * b[2] + a[1] * b[5] + a[2],
        a[3] * b[0] + a[4] * b[3],
        a[3] * b[1] + a[4] * b[4],
        a[3] * b[2] + a[4] * b[5] + a[5],
    )


def inverse(m):
    det = m[0] * m[4] - m[1] * m[3]
    if abs(det) < 1e-10:
        raise MotionError("Cannot preview a zero-scale transform.")
    return (
        m[4] / det,
        -m[1] / det,
        (m[1] * m[5] - m[4] * m[2]) / det,
        -m[3] / det,
        m[0] / det,
        (m[3] * m[2] - m[0] * m[5]) / det,
    )


def transform(x=0.0, y=0.0, rotation=0.0, sx=1.0, sy=1.0, shear_x=0.0, shear_y=0.0):
    r1, r2 = math.radians(rotation + shear_x), math.radians(rotation + 90 + shear_y)
    return (math.cos(r1) * sx, math.cos(r2) * sy, x, math.sin(r1) * sx, math.sin(r2) * sy, y)


def point(m, x, y):
    return (m[0] * x + m[1] * y + m[2], m[3] * x + m[4] * y + m[5])


def easing(curve, alpha):
    if curve == "stepped":
        return 0
    if not isinstance(curve, list):
        return alpha
    if len(curve) != 4:
        raise MotionError("Unsupported Bezier curve.")
    x1, y1, x2, y2 = curve

    def bezier(t, a, b):
        return 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t * t * b + t**3

    lo, hi = 0.0, 1.0
    for _ in range(24):
        mid = (lo + hi) / 2
        if bezier(mid, x1, x2) < alpha:
            lo = mid
        else:
            hi = mid
    return bezier((lo + hi) / 2, y1, y2)


def sample(keys, t, defaults):
    if not keys or t < keys[0].get("time", 0):
        return defaults
    left = keys[0]
    for right in keys[1:]:
        end, start = right.get("time", 0), left.get("time", 0)
        if t < end:
            curve = left.get("curve")
            if isinstance(curve, (float, int)):
                curve = [curve, left.get("c2", 0), left.get("c3", 1), left.get("c4", 1)]
            a = easing(curve, (t - start) / (end - start))
            return {k: left.get(k, v) + (right.get(k, v) - left.get(k, v)) * a for k, v in defaults.items()}
        left = right
    return {k: left.get(k, v) for k, v in defaults.items()}


def worlds(data, animation, t):
    result = {}
    for bone in data["bones"]:
        track = animation.get("bones", {}).get(bone["name"], {})
        rot = sample(track.get("rotate"), t, {"angle": 0})["angle"]
        pos = sample(track.get("translate"), t, {"x": 0, "y": 0})
        scale = sample(track.get("scale"), t, {"x": 1, "y": 1})
        shear = sample(track.get("shear"), t, {"x": 0, "y": 0})
        local = transform(
            bone.get("x", 0) + pos["x"],
            bone.get("y", 0) + pos["y"],
            bone.get("rotation", 0) + rot,
            bone.get("scaleX", 1) * scale["x"],
            bone.get("scaleY", 1) * scale["y"],
            bone.get("shearX", 0) + shear["x"],
            bone.get("shearY", 0) + shear["y"],
        )
        result[bone["name"]] = multiply(result.get(bone.get("parent"), IDENTITY), local)
    return result
