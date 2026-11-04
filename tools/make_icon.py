from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

SIZE = 256
SCALE = 4
image = Image.new("RGBA", (SIZE * SCALE, SIZE * SCALE), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
margin = 22 * SCALE
draw.rounded_rectangle(
    [margin, margin, SIZE * SCALE - margin, SIZE * SCALE - margin],
    radius=52 * SCALE,
    fill="#c9f56a",
)

points = []
for index in range(241):
    x = index / 240 * (SIZE - 80) * SCALE + 40 * SCALE
    y = (128 + 46 * math.sin(index / 240 * math.pi * 3) * math.sin(index / 240 * math.pi)) * SCALE
    points.append((x, y))
draw.line(points, fill="#101400", width=16 * SCALE, joint="curve")

image = image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
image.save(ASSETS / "cadence.png")
image.save(
    ASSETS / "cadence.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("Wrote assets/cadence.png and assets/cadence.ico")
