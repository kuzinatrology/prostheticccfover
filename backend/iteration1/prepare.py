"""Measure the Rhino cover once, so the service never opens the STL.

    .venv/bin/python -m backend.iteration1.prepare

The file is a closed cover with a wall already on it, exported from Rhino as a
mesh in the scanner's coordinates.  What the configurator needs from it is not
the mesh but the shape: where its axis runs, how far its outer skin reaches at
every angle and height, how thick its wall is, and where its two rims are.  All
of that is stored as a radius over a grid of (angle, height), which is the
unwrapping the rest of the code already speaks.

The cover is star shaped about its own axis — every cell of the grid holds one
outer radius and one inner radius, a wall apart — so nothing is lost by storing
it this way, and a hole cut in the parameter square lands where it was drawn.
"""

from __future__ import annotations

import json

import numpy as np
import trimesh
from scipy.ndimage import gaussian_filter1d

from . import config as cfg

TWO_PI = 2.0 * np.pi


def load(source=None) -> trimesh.Trimesh:
    """The largest body in the export, welded and wound outward.

    Rhino left two stray two-triangle scraps and one tangle five millimetres
    across in this export.  The scraps are dropped by taking the largest body;
    the tangle is a hole in an otherwise closed cover and is left alone, since
    nothing downstream reads the mesh's topology — the grid below is measured
    from points scattered over its faces.
    """
    mesh = trimesh.load(source or cfg.SOURCE_FILE, process=True)
    mesh.merge_vertices()
    mesh = max(mesh.split(only_watertight=False), key=lambda part: len(part.faces))
    mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh)
    return mesh


def centreline(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    """Where the cover's axis runs, section by section.

    The mid-point of each section's extent, not its median: the grid has to
    reach every part of the section, and this is the centre that needs the
    least radius to do it.  Smoothed over CENTRE_SMOOTH_MM, which is slower
    than the cover leans and faster than any single section wobbles.
    """
    v = np.asarray(mesh.vertices)
    z0, z1 = float(v[:, 2].min()), float(v[:, 2].max())
    zs = np.arange(z0, z1 + cfg.CENTRE_STEP, cfg.CENTRE_STEP)
    raw = np.full((len(zs), 2), np.nan)
    for i, z in enumerate(zs):
        band = v[np.abs(v[:, 2] - z) <= cfg.CENTRE_STEP]
        if len(band) > 20:
            raw[i] = (band[:, :2].min(axis=0) + band[:, :2].max(axis=0)) / 2.0
    for i in range(2):
        good = ~np.isnan(raw[:, i])
        raw[:, i] = np.interp(zs, zs[good], raw[good, i])
    sigma = cfg.CENTRE_SMOOTH_MM / cfg.CENTRE_STEP / 3.0
    return zs, np.stack([gaussian_filter1d(raw[:, i], sigma, mode="nearest") for i in range(2)], -1)


def _wrap_smooth(values: np.ndarray, sigma_deg: float) -> np.ndarray:
    return gaussian_filter1d(values, sigma_deg / (360.0 / len(values)), mode="wrap")


def measure(mesh: trimesh.Trimesh, zs: np.ndarray, centre: np.ndarray) -> dict:
    """The outer skin, the inner skin and the wall between them, cell by cell.

    Points are scattered over the faces rather than taken from the vertices:
    the export is a loft of long thin rows, and its vertices leave most of a
    one degree grid empty.  In each cell the farthest point is the outer skin
    and the nearest is the inner one, which is exactly what star shaped means.
    """
    points, faces = trimesh.sample.sample_surface(mesh, cfg.SAMPLES)
    normals = np.asarray(mesh.face_normals)[faces]

    z0 = float(np.asarray(mesh.vertices)[:, 2].min())
    cx = np.interp(points[:, 2], zs, centre[:, 0])
    cy = np.interp(points[:, 2], zs, centre[:, 1])
    dx, dy = points[:, 0] - cx, points[:, 1] - cy
    radius = np.hypot(dx, dy)
    angle = np.arctan2(dy, dx)

    cols = cfg.GRID_THETA
    rows = int(np.ceil((float(points[:, 2].max()) - z0) / cfg.GRID_DZ)) + 1
    # Angles run 0 to 2 pi, the convention the surface reads them back in:
    # anything else leaves half the turn outside the spline's knots, where it
    # is extrapolated rather than read, and half the cover comes out invented.
    ti = ((angle % TWO_PI) / TWO_PI * cols).astype(int) % cols
    zi = np.clip(((points[:, 2] - z0) / cfg.GRID_DZ).round().astype(int), 0, rows - 1)
    flat = zi * cols + ti

    # Two passes.  The first finds the two skins in each cell as the farthest
    # and nearest sample in it; the second averages the samples on each side
    # of the midpoint between them.  Taking the extremes alone would be the
    # obvious reading and it rings: the farthest of nine samples scattered
    # over a slanted triangle sits high by a fraction of that triangle, and
    # which fraction depends on how the export's rows happen to fall, so the
    # surface comes out banded.  The mean of a skin's own samples does not
    # care where the rows are.
    far = np.full(rows * cols, -np.inf)
    near = np.full(rows * cols, np.inf)
    hits = np.zeros(rows * cols, dtype=int)
    np.maximum.at(far, flat, radius)
    np.minimum.at(near, flat, radius)
    np.add.at(hits, flat, 1)

    outward = radius > (far[flat] + near[flat]) / 2.0
    outer = np.zeros(rows * cols)
    inner = np.zeros(rows * cols)
    out_hits = np.zeros(rows * cols, dtype=int)
    in_hits = np.zeros(rows * cols, dtype=int)
    np.add.at(outer, flat[outward], radius[outward])
    np.add.at(out_hits, flat[outward], 1)
    np.add.at(inner, flat[~outward], radius[~outward])
    np.add.at(in_hits, flat[~outward], 1)
    known = ((out_hits >= cfg.MIN_HITS) & (in_hits >= cfg.MIN_HITS)).reshape(rows, cols)
    outer = np.where(out_hits > 0, outer / np.maximum(out_hits, 1), far).reshape(rows, cols)
    inner = np.where(in_hits > 0, inner / np.maximum(in_hits, 1), near).reshape(rows, cols)

    # The rims, from the points themselves rather than from which cells came
    # out occupied.  Read off the grid they arrive quantised to its row
    # height, and a millimetre of staircase around the top rim is a
    # millimetre of sawtooth on the finished edge.
    rim_top = np.full(cols, -np.inf)
    rim_bottom = np.full(cols, np.inf)
    np.maximum.at(rim_top, ti, points[:, 2])
    np.minimum.at(rim_bottom, ti, points[:, 2])

    # How much of a radial step is wall: the outer skin leans, so the wall
    # measured along the radius is longer than the wall itself.
    lean = np.abs(np.einsum("ij,ij->i", normals, np.stack([dx / np.maximum(radius, 1e-9),
                                                           dy / np.maximum(radius, 1e-9),
                                                           np.zeros_like(radius)], axis=-1)))
    lean_mean = float(np.mean(lean[outward]))

    return {
        "rim_top": rim_top,
        "rim_bottom": rim_bottom,
        "z": z0 + np.arange(rows) * cfg.GRID_DZ,
        "theta": np.linspace(0.0, TWO_PI, cols, endpoint=False) + np.pi / cols,
        "outer": outer,
        "inner": inner,
        "known": known,
        "lean": lean_mean,
    }


def rims(grid: dict) -> tuple[np.ndarray, np.ndarray]:
    """Height of the bottom and top rim at every angle.

    The highest and lowest point measured at that angle: the cover is a tube,
    so where it exists at an angle it exists between them.  Smoothed by
    RIM_SMOOTH_DEG, which is a third of the finest thing either curve does and
    wider than the scatter of where a sample happened to land.
    """
    return (
        _wrap_smooth(grid["rim_bottom"], cfg.RIM_SMOOTH_DEG),
        _wrap_smooth(grid["rim_top"], cfg.RIM_SMOOTH_DEG),
    )


def fill(values: np.ndarray, known: np.ndarray) -> np.ndarray:
    """Carry each column's nearest measured value into the cells above and
    below it, so the surface is defined over the whole square.

    Nothing is ever built up there — the region stops at the rim — but the
    spline that reads the surface has to have something to read.
    """
    out = values.copy()
    rows = np.arange(len(values))
    for j in range(values.shape[1]):
        good = known[:, j]
        out[:, j] = np.interp(rows, rows[good], values[good, j])
    return out


def main(source=None, surface_file=None, report_file=None) -> dict:
    """Measure one modelled cover into a stored surface.

    The arguments are the only thing that differs between one Rhino model and
    the next: everything below -- how densely the mesh is sampled, how the
    centre line is fitted, how far the rims are smoothed -- is about reading an
    export, not about which export it is.
    """
    source = source or cfg.SOURCE_FILE
    surface_file = surface_file or cfg.SURFACE_FILE
    report_file = report_file or cfg.REPORT_FILE
    mesh = load(source)
    zs, centre = centreline(mesh)
    grid = measure(mesh, zs, centre)
    bottom, top = rims(grid)

    # Put the cover where a viewer expects it: its axis through the origin at
    # the bottom rim, z running up from zero.  The scan's own coordinates put
    # it a metre away from it.
    shift_xy = np.interp(bottom.min(), zs, centre[:, 0]), np.interp(bottom.min(), zs, centre[:, 1])
    shift_z = float(grid["z"][0])
    centre_on_grid = np.stack(
        [np.interp(grid["z"], zs, centre[:, i]) - shift_xy[i] for i in range(2)], axis=-1
    )

    radial_wall = (grid["outer"] - grid["inner"])[grid["known"]]
    wall = float(np.median(radial_wall) * grid["lean"])

    meta = {
        "source": str(source.name),
        "faces": len(mesh.faces),
        "samples": cfg.SAMPLES,
        "wall_mm": round(wall, 2),
        "wall_radial_median_mm": round(float(np.median(radial_wall)), 2),
        "wall_radial_p5_mm": round(float(np.percentile(radial_wall, 5)), 2),
        "wall_radial_p95_mm": round(float(np.percentile(radial_wall, 95)), 2),
        "lean_factor": round(grid["lean"], 4),
        "height_mm": round(float(top.max() - bottom.min()), 1),
        "bottom_rim_mm": [round(float(bottom.min()), 1), round(float(bottom.max()), 1)],
        "top_rim_mm": [round(float(top.min()), 1), round(float(top.max()), 1)],
        "radius_mm": [round(float(grid["outer"][grid["known"]].min()), 1),
                      round(float(grid["outer"][grid["known"]].max()), 1)],
        "coverage": round(float(grid["known"].mean()), 3),
        "shift_mm": [round(float(shift_xy[0]), 2), round(float(shift_xy[1]), 2), round(shift_z, 2)],
        "grid": [int(grid["known"].shape[0]), int(grid["known"].shape[1])],
    }

    surface_file.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        surface_file,
        theta=grid["theta"],
        z=grid["z"] - shift_z,
        R=fill(grid["outer"], grid["known"]).astype(np.float32),
        W=fill(grid["outer"] - grid["inner"], grid["known"]).astype(np.float32),
        known=grid["known"],
        centre=centre_on_grid,
        bottom=bottom - shift_z,
        top=top - shift_z,
        meta=json.dumps(meta),
    )
    report_file.write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    return meta


if __name__ == "__main__":
    main()
