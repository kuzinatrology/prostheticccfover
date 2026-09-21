"""Still renders for the stage reports: side, front and back.

Orthographic, painter's algorithm, drawn by Pillow. No display, no GPU and no
browser, so it runs anywhere the geometry does. Supersampled and scaled down,
which is enough to judge a silhouette and an edge against the reference.

    python -m tools.render mesh.stl --out renders/stage_1
"""

from __future__ import annotations

import argparse
import pathlib

import numpy as np
import trimesh
from PIL import Image, ImageDraw

BACKGROUND = (233, 234, 230)
SUPERSAMPLE = 2
KEY = (0.45, 0.35, -0.8)
"""Key light in camera terms: right, up, toward the camera. Fixed to the camera
so every view is lit alike."""

# Camera looks along `forward`; `right` is screen right, z is always up.
# The side view is from -x so the front of the leg is on the left, as in the
# reference.
VIEWS = {
    "side": (np.array([1.0, 0.0, 0.0]), np.array([0.0, -1.0, 0.0])),
    "front": (np.array([0.0, -1.0, 0.0]), np.array([-1.0, 0.0, 0.0])),
    "back": (np.array([0.0, 1.0, 0.0]), np.array([1.0, 0.0, 0.0])),
}


def _shade(
    normals: np.ndarray, forward: np.ndarray, right: np.ndarray, colour: np.ndarray
) -> np.ndarray:
    up = np.array([0.0, 0.0, 1.0])
    light = KEY[0] * right + KEY[1] * up + KEY[2] * forward
    light = light / np.linalg.norm(light)
    # Two-sided: an inner wall seen through a gap is lit like an outer one.
    facing = np.sign(-(normals @ forward))[:, None]
    n = normals * np.where(facing == 0, 1, facing)
    lambert = np.clip(n @ light, 0.0, 1.0)
    rim = np.clip(1.0 - np.abs(n @ forward), 0.0, 1.0) ** 3
    level = 0.32 + 0.62 * lambert + 0.12 * rim
    return np.clip(colour[None, :] * level[:, None], 0, 255)


def render(
    parts: list[tuple[trimesh.Trimesh, tuple[int, int, int]]],
    view: str,
    path: pathlib.Path,
    height: int = 1100,
    bounds: np.ndarray | None = None,
) -> None:
    forward, right = VIEWS[view]
    up = np.array([0.0, 0.0, 1.0])
    all_v = np.vstack([m.vertices for m, _ in parts])
    lo, hi = (bounds if bounds is not None else np.array([all_v.min(0), all_v.max(0)]))
    corners = np.array(np.meshgrid(*zip(lo, hi))).reshape(3, -1).T
    sx, sy = corners @ right, corners @ up
    margin = 0.06
    span_x, span_y = np.ptp(sx), np.ptp(sy)
    scale = (height * SUPERSAMPLE) * (1 - 2 * margin) / span_y
    width = int(np.ceil(span_x * scale / (1 - 2 * margin))) + 1
    H = height * SUPERSAMPLE
    W = max(width, int(H * 0.5))
    ox = W / 2 - (sx.min() + span_x / 2) * scale
    oy = H / 2 + (sy.min() + span_y / 2) * scale

    tris, depth, fill = [], [], []
    for mesh, colour in parts:
        tri = mesh.vertices[mesh.faces]
        normals = mesh.face_normals
        px = tri @ right * scale + ox
        py = oy - tri @ up * scale
        tris.append(np.stack([px, py], axis=-1))
        depth.append((tri @ forward).mean(axis=1))
        fill.append(_shade(normals, forward, right, np.array(colour, dtype=float)))
    tris = np.concatenate(tris)
    depth = np.concatenate(depth)
    fill = np.concatenate(fill).astype(np.uint8)

    image = Image.new("RGB", (W, H), BACKGROUND)
    draw = ImageDraw.Draw(image)
    # Furthest first, so nearer faces paint over them.
    for k in np.argsort(-depth):
        t = tris[k]
        draw.polygon([(t[0, 0], t[0, 1]), (t[1, 0], t[1, 1]), (t[2, 0], t[2, 1])], fill=tuple(fill[k]))
    image = image.resize((W // SUPERSAMPLE, H // SUPERSAMPLE), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def render_views(
    parts: list[tuple[trimesh.Trimesh, tuple[int, int, int]]],
    stem: pathlib.Path,
    views: tuple[str, ...] = ("side", "front", "back"),
) -> list[pathlib.Path]:
    all_v = np.vstack([m.vertices for m, _ in parts])
    bounds = np.array([all_v.min(0), all_v.max(0)])
    out = []
    for view in views:
        path = stem.parent / f"{stem.name}_{view}.png"
        render(parts, view, path, bounds=bounds)
        out.append(path)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mesh", nargs="+")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    palette = [(150, 170, 182), (112, 136, 150), (190, 160, 120), (160, 120, 110)]
    parts = [(trimesh.load(p, force="mesh"), palette[i % len(palette)]) for i, p in enumerate(args.mesh)]
    for path in render_views(parts, pathlib.Path(args.out)):
        print(path)


if __name__ == "__main__":
    main()
