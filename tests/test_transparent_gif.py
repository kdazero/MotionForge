from PIL import Image

from motionforge.gif_export import transparent_gif


def test_gif_retains_transparency_and_timing(tmp_path):
    frames = []
    for x in [3, 9]:
        image = Image.new("RGBA", (16, 16))
        for y in range(3, 9):
            for xx in range(x, x + 3):
                image.putpixel((xx, y), (220, 40, 80, 255))
        frames.append(image)
    out = tmp_path / "test.gif"
    transparent_gif(frames, [80, 120], out)
    im = Image.open(out)
    total = 0
    assert im.n_frames == 2
    for i in range(im.n_frames):
        im.seek(i)
        total += im.info["duration"]
        rgba = im.convert("RGBA")
        assert rgba.getpixel((0, 0))[3] == 0
        assert rgba.getpixel(([3, 9][i], 5))[3] == 255
    assert total == 200
