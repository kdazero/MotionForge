"""Geometric rig fixture. All parts are drawn locally; no external artwork."""

from pathlib import Path

from PIL import Image, ImageDraw

from .motion import Bone, Layer


def make_demo(inbox: Path, theme: str = "mint") -> tuple[list[Bone], list[Layer], dict[str, str]]:
    inbox.mkdir(parents=True, exist_ok=True)
    specs = {
        "body": (112, 132, "#28bda7"),
        "head": (124, 102, "#e7eee9"),
        "arm_left": (34, 96, "#21a58f"),
        "arm_right": (34, 96, "#28bda7"),
        "hand": (42, 42, "#f6bf63"),
        "leg_left": (42, 94, "#405474"),
        "leg_right": (42, 94, "#526986"),
    }
    if theme == "coral":
        palette = {
            "body": "#e6936e",
            "head": "#f8e1c2",
            "arm_left": "#c47b62",
            "arm_right": "#e6936e",
            "hand": "#ffdb97",
            "leg_left": "#556a61",
            "leg_right": "#678276",
        }
        specs = {name: (w, h, palette[name]) for name, (w, h, _) in specs.items()}
    for name, (w, h, color) in specs.items():
        scale = 3
        image = Image.new("RGBA", (w * scale, h * scale))
        draw = ImageDraw.Draw(image)
        box = (3 * scale, 3 * scale, (w - 3) * scale, (h - 3) * scale)
        draw.rounded_rectangle(box, radius=16 * scale, fill=color, outline="#183146", width=3 * scale)
        if name == "head":
            draw.rounded_rectangle(
                (16 * scale, 24 * scale, 108 * scale, 72 * scale), radius=15 * scale, fill="#183146"
            )
            for x in (40, 83):
                draw.ellipse(((x - 5) * scale, 39 * scale, (x + 5) * scale, 52 * scale), fill="#7ce6d1")
            draw.arc(
                (49 * scale, 45 * scale, 74 * scale, 65 * scale), 10, 170, fill="#7ce6d1", width=3 * scale
            )
        if name == "body":
            draw.rounded_rectangle(
                (24 * scale, 27 * scale, 88 * scale, 73 * scale), radius=10 * scale, fill="#183146"
            )
            draw.line(
                (
                    38 * scale,
                    50 * scale,
                    48 * scale,
                    50 * scale,
                    55 * scale,
                    39 * scale,
                    63 * scale,
                    59 * scale,
                    73 * scale,
                    46 * scale,
                ),
                fill="#f6bf63",
                width=4 * scale,
            )
            for x in (39, 56, 73):
                draw.ellipse(((x - 3) * scale, 92 * scale, (x + 3) * scale, 98 * scale), fill="#183146")
        image.resize((w, h), Image.Resampling.LANCZOS).save(inbox / f"{name}.png")
    bones = [
        Bone(name="root"),
        Bone(name="body", parent="root", y=96),
        Bone(name="leg_left", parent="body", x=-28),
        Bone(name="leg_right", parent="body", x=28),
        Bone(name="arm_left", parent="body", x=-63, y=108),
        Bone(name="arm_right", parent="body", x=63, y=108),
        Bone(name="hand", parent="arm_right", y=-77),
        Bone(name="head", parent="body", y=126),
    ]
    offsets = {
        "body": (0, 61),
        "head": (0, 49),
        "arm_left": (0, -37),
        "arm_right": (0, -37),
        "hand": (0, -9),
        "leg_left": (0, -43),
        "leg_right": (0, -43),
    }
    order = ["leg_left", "leg_right", "arm_left", "body", "arm_right", "hand", "head"]
    layers = [
        Layer(name=n, image=f"inbox/demo-parts/{n}.png", bone=n, x=offsets[n][0], y=offsets[n][1])
        for n in order
    ]
    roles = {n: n for n in ("root", "body", "head", "hand", "leg_left", "leg_right", "arm_left", "arm_right")}
    roles["arm"] = "arm_right"
    return bones, layers, roles
