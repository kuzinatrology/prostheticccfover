"""Orthographic stills for the stage reports.

Painter's algorithm drawn by Pillow, same idea as tools/render.py but with a
three-quarter view, per-face colours and 3-D annotations, which the stage
reports need.  No GPU, no display, no browser.
"""

from __future__ import annotations

import pathlib

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import config

SUPERSAMPLE = 2
KEY = (0.45, 0.35, -0.8)
"""Key light in camera terms: right, up, toward the camera.  Fixed to the
camera, so every view is lit alike."""

# Named directions the camera looks along, in cover coordinates (z up, +y the
# direction the foot points).  Side is from the leg's left, so the toes point
# left, as in the reference renders.
VIEWS = {
    # The camera looks ALONG `forward`, so it stands on the opposite side: to
    # see the front of the leg it has to sit in front of it, at +y.
    "front": (0.0, -1.0, 0.0),
    "back": (0.0, 1.0, 0.0),
    "side": (1.0, 0.0, 0.0),
    "three_quarter": (0.72, 0.62, -0.18),
}


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        if pathlib.Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _basis(forward: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    f = np.asarray(forward, float)
    f = f / np.linalg.norm(f)
    up = np.array([0.0, 0.0, 1.0])
    up = up - f * (up @ f)
    up = up / np.linalg.norm(up)
    return f, up, np.cross(f, up)


def _shade(normals: np.ndarray, f, u, r, colour: np.ndarray) -> np.ndarray:
    light = KEY[0] * r + KEY[1] * u + KEY[2] * f
    light = light / np.linalg.norm(light)
    # Two-sided: an inner wall seen through a gap is lit like an outer one.
    facing = np.sign(-(normals @ f))[:, None]
    n = normals * np.where(facing == 0, 1, facing)
    lambert = np.clip(n @ light, 0.0, 1.0)
    rim = np.clip(1.0 - np.abs(n @ f), 0.0, 1.0) ** 3
    level = 0.33 + 0.60 * lambert + 0.11 * rim
    return np.clip(colour * level[:, None], 0, 255)


def render(
    parts: list[tuple[np.ndarray, np.ndarray, tuple | np.ndarray]],
    view: str | tuple,
    path: pathlib.Path,
    height: int = config.RENDER_HEIGHT,
    bounds: tuple[np.ndarray, np.ndarray] | None = None,
    labels: list[tuple[tuple, str, tuple]] | None = None,
    rules: list[tuple[float, str]] | None = None,
    title: str | None = None,
) -> Image.Image:
    """Draw `parts` (vertices, faces, colour) down `view` and save a PNG.

    `labels` are (point, text, colour) pinned in 3-D; `rules` are horizontal
    lines at a height z with a caption, for marking axes and section planes.
    """
    forward = VIEWS[view] if isinstance(view, str) else view
    f, u, r = _basis(np.asarray(forward, float))

    all_v = np.vstack([p[0] for p in parts])
    lo, hi = bounds if bounds is not None else (all_v.min(0), all_v.max(0))
    corners = np.array(np.meshgrid(*zip(lo, hi))).reshape(3, -1).T
    sx, sy = corners @ r, corners @ u

    margin = 0.07
    span_x, span_y = np.ptp(sx), np.ptp(sy)
    H = height * SUPERSAMPLE
    scale = H * (1 - 2 * margin) / max(span_y, 1e-9)
    W = max(int(np.ceil(span_x * scale / (1 - 2 * margin))) + 1, int(H * 0.42))
    ox = W / 2 - (sx.min() + span_x / 2) * scale
    oy = H / 2 + (sy.min() + span_y / 2) * scale

    def project(points: np.ndarray) -> np.ndarray:
        p = np.atleast_2d(np.asarray(points, float))
        return np.stack([p @ r * scale + ox, oy - p @ u * scale], axis=-1)

    tris, depth, fill = [], [], []
    for verts, faces, colour in parts:
        tri = verts[faces]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        length = np.linalg.norm(n, axis=1)
        n = n / np.where(length == 0, 1, length)[:, None]
        c = np.asarray(colour, float)
        if c.ndim == 1:
            c = np.repeat(c[None, :], len(tri), axis=0)
        fill.append(_shade(n, f, u, r, c))
        tris.append(np.stack([tri @ r * scale + ox, oy - tri @ u * scale], axis=-1))
        depth.append((tri @ f).mean(axis=1))

    tris = np.vstack(tris)
    depth = np.concatenate(depth)
    fill = np.vstack(fill).astype(np.uint8)

    img = Image.new("RGB", (W, H), config.RENDER_BACKGROUND)
    draw = ImageDraw.Draw(img)
    for i in np.argsort(-depth):
        t = tris[i]
        draw.polygon([tuple(t[0]), tuple(t[1]), tuple(t[2])], fill=tuple(fill[i]))

    img = img.resize((W // SUPERSAMPLE, H // SUPERSAMPLE), Image.LANCZOS)
    draw = ImageDraw.Draw(img)
    small, big = _font(15), _font(19)

    for z, text in rules or []:
        y = (oy - z * (u @ [0, 0, 1]) * scale) / SUPERSAMPLE
        if 0 < y < img.height:
            draw.line([(0, y), (img.width, y)], fill=(150, 90, 80), width=1)
            draw.text((6, y - 17), text, font=small, fill=(150, 90, 80))

    for point, text, colour in labels or []:
        p = project(point)[0] / SUPERSAMPLE
        draw.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=colour)
        draw.text((p[0] + 8, p[1] - 9), text, font=big, fill=colour)

    if title:
        draw.text((10, 8), title, font=big, fill=(70, 70, 70))

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return img


def contact_sheet(paths: list[pathlib.Path], out: pathlib.Path, columns: int = 2) -> None:
    images = [Image.open(p) for p in paths]
    w = max(i.width for i in images)
    h = max(i.height for i in images)
    rows = int(np.ceil(len(images) / columns))
    sheet = Image.new("RGB", (w * columns, h * rows), config.RENDER_BACKGROUND)
    for i, im in enumerate(images):
        sheet.paste(im, ((i % columns) * w, (i // columns) * h))
    sheet.save(out)
