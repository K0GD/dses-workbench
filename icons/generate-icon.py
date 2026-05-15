"""Generate b210.ico (multi-resolution Windows icon) and a b210.png preview
for the B210 Spectrum Analyzer.

Design: pulsar lighthouse beam (cyan bowtie cones along NW-SE diagonal) with
a bright white core glowing yellow, over a deep-space navy background, with
a phosphor-green spectrum trace along the bottom.

Run with Radioconda's python (has Pillow):
    'C:\\ProgramData\\radioconda\\python.exe' icons\\generate-icon.py
"""
from pathlib import Path
import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZE   = 256
CENTER = (SIZE // 2, SIZE // 2)

BG       = (10, 14, 28, 255)      # deep-space navy
CONE     = (34, 211, 238, 180)    # cyan, semi-transparent
HALO     = (255, 224, 102, 110)   # yellow halo
CORE     = (255, 255, 255, 255)   # sharp white pulsar core
SPECTRUM = (16, 185, 129, 230)    # phosphor green


def make_icon():
    img = Image.new("RGBA", (SIZE, SIZE), BG)
    cx, cy = CENTER

    # --- Radiation cones (NW-SE bowtie, tight beams that fade to transparent at tips) ---
    cone_len  = 115
    cone_half = 12      # tight half-angle
    axis_deg  = 45      # diagonal axis

    # Cone-shape mask: 255 inside the bowtie, 0 outside.
    cone_mask = Image.new("L", (SIZE, SIZE), 0)
    md = ImageDraw.Draw(cone_mask)
    for direction in (0, 180):
        a1 = math.radians(axis_deg + direction - cone_half)
        a2 = math.radians(axis_deg + direction + cone_half)
        p1 = (cx + cone_len * math.cos(a1), cy + cone_len * math.sin(a1))
        p2 = (cx + cone_len * math.cos(a2), cy + cone_len * math.sin(a2))
        md.polygon([CENTER, p1, p2], fill=255)

    # Radial fade: opaque at the pulsar, transparent at the cone tips (gamma curve
    # so the beams stay bright most of the way out, then drop off fast).
    yy, xx = np.indices((SIZE, SIZE))
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    fade = np.clip(1.0 - dist / cone_len, 0.0, 1.0) ** 1.3
    fade_img = Image.fromarray((fade * 200).astype(np.uint8), mode="L")

    cone_alpha = ImageChops.multiply(cone_mask, fade_img)
    cones_rgb  = Image.new("RGB", (SIZE, SIZE), CONE[:3])
    cones      = cones_rgb.convert("RGBA")
    cones.putalpha(cone_alpha)
    cones = cones.filter(ImageFilter.GaussianBlur(radius=3))
    img = Image.alpha_composite(img, cones)

    # --- Faint cyan glow ring around the pulsar (subtle hint of structure) ---
    ring = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        [cx - 26, cy - 26, cx + 26, cy + 26],
        outline=(34, 211, 238, 70),
        width=2,
    )
    ring = ring.filter(ImageFilter.GaussianBlur(radius=4))
    img = Image.alpha_composite(img, ring)

    # --- Pulsar halo (soft yellow, slightly larger and more diffuse) ---
    halo = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse(
        [cx - 34, cy - 34, cx + 34, cy + 34], fill=HALO
    )
    halo = halo.filter(ImageFilter.GaussianBlur(radius=18))
    img = Image.alpha_composite(img, halo)

    # --- Pulsar core (sharp white) ---
    core = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(core).ellipse(
        [cx - 10, cy - 10, cx + 10, cy + 10], fill=CORE
    )
    core = core.filter(ImageFilter.GaussianBlur(radius=1.5))
    img = Image.alpha_composite(img, core)

    # --- Spectrum trace along the bottom (subtle, doesn't compete with the pulsar) ---
    spec = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    sd = ImageDraw.Draw(spec)
    baseline_y = 224
    margin_x   = 22
    peaks = [
        # (center_x_offset_from_margin, peak_height_px, sigma_px)
        (54,  20, 16),
        (120, 12, 12),
        (180, 28, 14),
    ]
    points = []
    n = 200
    for i in range(n + 1):
        x = margin_x + (SIZE - 2 * margin_x) * i / n
        y = baseline_y
        for (cx_off, h, sig) in peaks:
            px = margin_x + cx_off
            y -= h * math.exp(-((x - px) ** 2) / (2 * sig ** 2))
        points.append((x, y))
    sd.line(points, fill=SPECTRUM, width=2, joint="curve")
    img = Image.alpha_composite(img, spec)

    return img


def main():
    here = Path(__file__).parent
    here.mkdir(parents=True, exist_ok=True)

    img = make_icon()

    png_path = here / "b210.png"
    ico_path = here / "b210.ico"

    img.save(png_path, format="PNG")
    img.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    print(f"Generated: {ico_path}")
    print(f"Preview:   {png_path}")


if __name__ == "__main__":
    main()
