import hashlib

import pytest
from PIL import Image

from motionforge.ai_assets import PartMask, extract_part
from motionforge.storage import MotionError


def test_visible_part_excludes_other_parts_and_preserves_source(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGBA", (40, 60), (123, 89, 67, 255)).save(source)
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    result = extract_part(
        tmp_path,
        "source.png",
        PartMask(
            name="hand",
            polygon=[(4, 6), (36, 6), (36, 50), (4, 50)],
            excluded_polygons=[[(14, 16), (26, 16), (26, 30), (14, 30)]],
            pivot=(20, 8),
        ),
    )
    im = Image.open(tmp_path / result["path"])
    x, y = result["crop_box"][:2]
    assert im.getpixel((20 - x, 23 - y))[3] == 0
    assert im.getpixel((9 - x, 40 - y)) == (123, 89, 67, 255)
    cx, cy = (
        (result["crop_box"][0] + result["crop_box"][2]) / 2,
        (result["crop_box"][1] + result["crop_box"][3]) / 2,
    )
    assert result["attachment_center"] == {"x": cx - 20, "y": 8 - cy}
    assert not result["hidden_art_reconstructed"] and result["source_sha256"] == sha
    assert hashlib.sha256(source.read_bytes()).hexdigest() == sha
    with pytest.raises(MotionError, match="coordinates"):
        extract_part(
            tmp_path, "source.png", PartMask(name="bad", polygon=[(-1, 0), (4, 3), (4, 6)], pivot=(2, 3))
        )
