"""Transparent GIF encoding for chat previews; PNG/WebP retain smooth alpha."""

import numpy as np
from PIL import Image


def transparent_gif(frames, durations, path, colors=128):
    if not frames or len(frames) != len(durations):
        raise ValueError("GIF frames and durations must be paired.")
    # One palette avoids color flicker. The transparent index is the entry right after the
    # opaque colors, so it always lies inside the written color table.
    sample = Image.new("RGB", (frames[0].width * 3, frames[0].height))
    for i, index in enumerate([0, len(frames) // 2, len(frames) - 1]):
        sample.paste(frames[index].convert("RGB"), (i * frames[0].width, 0))
    palette = sample.quantize(colors=min(colors, 255), method=Image.Quantize.MEDIANCUT)
    rgb = palette.getpalette()[: 3 * (max(index for _, index in palette.getcolors()) + 1)]
    clear = len(rgb) // 3
    table = rgb + [0, 0, 0]
    output = []
    for frame in frames:
        q = frame.convert("RGB").quantize(palette=palette, dither=Image.Dither.NONE)
        indices = np.array(q)
        indices[np.array(frame.getchannel("A")) < 128] = clear
        im = Image.fromarray(indices, "P")
        im.putpalette(table)
        im.info["transparency"] = clear
        output.append(im)
    output[0].save(
        path,
        save_all=True,
        append_images=output[1:],
        duration=durations,
        loop=0,
        disposal=2,
        transparency=clear,
        optimize=False,
    )
