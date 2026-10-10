"""Transparent GIF encoding for chat previews; PNG/WebP retain smooth alpha."""

import numpy as np
from PIL import Image


def transparent_gif(frames, durations, path, colors=128):
    if not frames or len(frames) != len(durations):
        raise ValueError("GIF frames and durations must be paired.")
    # One palette avoids color flicker; index 255 is reserved for transparent pixels.
    sample = Image.new("RGB", (frames[0].width * 3, frames[0].height))
    for i, index in enumerate([0, len(frames) // 2, len(frames) - 1]):
        sample.paste(frames[index].convert("RGB"), (i * frames[0].width, 0))
    palette = sample.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    output = []
    for frame in frames:
        q = frame.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE)
        indices = np.array(q)
        indices[np.array(frame.getchannel("A")) < 128] = 255
        im = Image.fromarray(indices, "P")
        im.putpalette(q.getpalette())
        im.info["transparency"] = 255
        output.append(im)
    output[0].save(
        path,
        save_all=True,
        append_images=output[1:],
        duration=durations,
        loop=0,
        disposal=2,
        transparency=255,
        optimize=False,
    )
