"""Measure the prosthesis once, so the fastener code never opens the scan.

    .venv/bin/python -m tools.prepare_hardware

The clamps grip real hardware, and until now its size was a guess: the
transfemoral tab carried a 30 mm tube and a 60 x 65 mm module, of which one was
scaled off a photograph and one not measured at all.  The prosthesis scan has
the real thing, so this reads it off and stores it.

Two different things come out of it, because the scan is trustworthy for two
different things:

*   **Where.**  The tube's line, fitted through twenty-five cross-sections.
    That is what the scan is good for: position, to a tenth of a millimetre.
*   **How big.**  The tube is a catalogue part and the fit agrees with the
    catalogue to 0.35 mm, so the bore of a clamp is the catalogue's 34 mm and
    not the fit.  It has to be: a third of the tube's circumference is missing
    from the scan (the section outlines are 75 mm long where a 34 mm tube
    measures 107), so anything read straight off it comes out small, and a
    clamp with a small bore does not go on.

Also solved here: where the hardware sits inside each cover.  The anatomic
cover is already built in the knee-axis frame, so for it the answer is nothing.
The Rhino cover has its own frame, and the shift between the two is found by
fitting the scan inside the cover's inner skin.
"""

from __future__ import annotations

import json

import numpy as np
import trimesh
from scipy.optimize import least_squares, minimize

from anatomic import config as anat
from backend.iteration1 import config as itercfg

OUT_NPZ = anat.ROOT.parent / "backend" / "assets" / "hardware.npz"
OUT_JSON = anat.ROOT.parent / "backend" / "assets" / "hardware.json"

SOURCE = anat.WORK / "stage2_prosthesis.stl"
"""Stage 2's output: the limb, in the knee-axis frame."""

Z_LO, Z_HI, Z_STEP = -380.0, 80.0, 2.0
"""The stretch any cover can reach.  Below is shoe, above is socket."""

BINS = 360
"""One radius per degree."""

PYLON_FIT_RANGE = (-330.0, -210.0)
"""Heights the tube's line is fitted over: tube and nothing else.

Stage 1 puts the tube at -328..-213 in this frame.  The two ends are left out
of the fit by a couple of millimetres, since the section there is half tube and
half the clamp that holds it."""

PYLON_CATALOGUE_RADIUS = anat.PYLON_DIAMETER / 2.0
"""17 mm.  College Park Capital's 34 mm pylon receiver, from the manual."""

SAMPLE_MM = 0.3
"""Spacing of the points laid along a cross-section outline."""


def outlines(mesh: trimesh.Trimesh, zs: np.ndarray) -> list[np.ndarray]:
    """Points along the mesh's cross-section at each height.

    Real sections, not the scan's vertices: at the pylon the decimated scan
    leaves a few hundred vertices per centimetre of height, which is a third of
    the angular bins empty and a section that comes out scalloped.
    """
    lines, _, _ = trimesh.intersections.mesh_multiplane(
        mesh, np.zeros(3), np.array([0.0, 0.0, 1.0]), zs
    )
    out = []
    for seg in lines:
        if len(seg) == 0:
            out.append(np.zeros((0, 2)))
            continue
        a, b = seg[:, 0, :], seg[:, 1, :]
        steps = np.maximum(np.ceil(np.linalg.norm(b - a, axis=1) / SAMPLE_MM).astype(int), 1)
        out.append(np.vstack([
            a[k] + (b[k] - a[k]) * np.linspace(0.0, 1.0, steps[k] + 1)[:, None]
            for k in range(len(seg))
        ]))
    return out


def sections(zs: np.ndarray, rings: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Outer radius about the knee axis, per angle and height, and coverage.

    Radii are taken about (0, 0) -- the knee axis -- and not about each
    section's own centre, because a clamp is placed in the cover's coordinates
    and a per-section centre would make the stored shape depend on where the
    section happened to be measured.

    `coverage` is the share of the 360 bins the scan actually reached.  It is
    stored rather than thresholded away: every consumer of this file has to
    know that a section is part guesswork before it trusts it, and the pylon's
    sections are all part guesswork.
    """
    radius = np.full((len(zs), BINS), np.nan)
    centre = np.full((len(zs), 2), np.nan)
    coverage = np.zeros(len(zs))
    for i, pts in enumerate(rings):
        if len(pts) < 50:
            continue
        ang = np.arctan2(pts[:, 1], pts[:, 0]) % (2.0 * np.pi)
        rho = np.hypot(pts[:, 0], pts[:, 1])
        bin_of = np.minimum((ang / (2.0 * np.pi) * BINS).astype(int), BINS - 1)
        acc = np.zeros(BINS)
        np.maximum.at(acc, bin_of, rho)
        seen = np.zeros(BINS, dtype=bool)
        seen[bin_of] = True
        coverage[i] = seen.mean()
        if coverage[i] < 0.35:
            continue
        idx = np.nonzero(seen)[0]
        radius[i] = np.interp(
            np.arange(BINS),
            np.concatenate([idx, idx[:1] + BINS]),
            np.concatenate([acc[idx], acc[idx[:1]]]),
            period=BINS,
        )
        centre[i] = pts.mean(axis=0)
    return radius, centre, coverage


def pylon(zs: np.ndarray, rings: list[np.ndarray]) -> dict:
    """The tube's line and radius, from a circle fitted to each section.

    `soft_l1` rather than least squares: the sections carry the scan's noise
    and, near the ends, a few points off the clamp that holds the tube, and a
    plain fit lets those pull the circle open.
    """
    lo, hi = PYLON_FIT_RANGE
    rows = []
    for z, pts in zip(zs, rings):
        if not (lo <= z <= hi) or len(pts) < 200:
            continue
        near = pts[np.hypot(pts[:, 0] + 14.0, pts[:, 1] + 7.0) < 40.0]
        if len(near) < 150:
            continue
        fit = least_squares(
            lambda p: np.hypot(near[:, 0] - p[0], near[:, 1] - p[1]) - p[2],
            [-14.0, -7.0, PYLON_CATALOGUE_RADIUS], loss="soft_l1", f_scale=1.0,
        )
        resid = np.abs(np.hypot(near[:, 0] - fit.x[0], near[:, 1] - fit.x[1]) - fit.x[2])
        rows.append([z, *fit.x, float(np.median(resid))])
    rows = np.array(rows)
    fx = np.polyfit(rows[:, 0], rows[:, 1], 1)
    fy = np.polyfit(rows[:, 0], rows[:, 2], 1)
    return {
        "fit_range": [lo, hi],
        "sections": len(rows),
        "x_of_z": [float(fx[0]), float(fx[1])],
        "y_of_z": [float(fy[0]), float(fy[1])],
        "tilt_deg": round(float(np.degrees(np.hypot(fx[0], fy[0]))), 2),
        "radius_fitted_mm": round(float(np.median(rows[:, 3])), 2),
        "radius_spread_mm": round(float(rows[:, 3].std()), 2),
        "radius_catalogue_mm": PYLON_CATALOGUE_RADIUS,
        "median_residual_mm": round(float(np.median(rows[:, 4])), 2),
        "outline_length_mm": round(float(np.median([
            len(p) * SAMPLE_MM for z, p in zip(zs, rings) if lo <= z <= hi
        ])), 0),
        "circumference_mm": round(2.0 * np.pi * PYLON_CATALOGUE_RADIUS, 0),
    }


def register_model(mesh: trimesh.Trimesh, model: str) -> dict:
    """Shift that carries the scan into one Rhino cover's own frame.

    The cover was modelled around this prosthesis, so the fit answers one
    question: which placement keeps the scan inside the cover's inner skin with
    the most room to spare.  A soft minimum is maximised rather than the hard
    one, so the search has a gradient and one stray scan vertex cannot decide
    the result.
    """
    from backend.iteration1.surface import IterSurface

    surf = IterSurface.default(smoothing=0.0, model=model)
    z_lo = float(np.atleast_1d(surf.z_of_v(np.array([0.0])))[0])
    z_hi = float(np.atleast_1d(surf.z_of_v(np.array([1.0])))[0])
    wall = float(json.loads(itercfg.model(model).report_file.read_text())["wall_mm"])
    pts = np.asarray(mesh.vertices, dtype=float)
    pts = pts[np.random.default_rng(0).choice(len(pts), 60_000, replace=False)]

    def gaps(par):
        p = pts + np.asarray(par)
        z = p[:, 2]
        inside = (z > z_lo + 2.0) & (z < z_hi - 2.0)
        p, z = p[inside], z[inside]
        c = surf.centre(z)
        a, b = p[:, 0] - c[:, 0], p[:, 1] - c[:, 1]
        return surf.radial(np.arctan2(b, a), z) - wall - np.hypot(a, b), z

    best, value = None, np.inf
    span = z_hi - z_lo
    for dz in (span - 55.0, span - 45.0, span - 35.0):
        r = minimize(lambda par: 0.5 * np.log(np.mean(np.exp(-gaps(par)[0] / 0.5))),
                     [10.0, 10.0, dz], method="Nelder-Mead",
                     options={"xatol": 0.05, "fatol": 0.01, "maxiter": 4000})
        if r.fun < value:
            best, value = r.x, r.fun
    g, _ = gaps(best)
    return {
        "model": model,
        "shift_mm": [round(float(x), 2) for x in best],
        "cover_zero_at_knee_z": round(-float(best[2]), 1),
        "min_gap_mm": round(float(g.min()), 2),
        "p1_gap_mm": round(float(np.percentile(g, 1)), 2),
        "median_gap_mm": round(float(np.median(g)), 2),
        "interfering_fraction": round(float((g < 0).mean()), 5),
        "cover_wall_mm": wall,
    }


def main() -> None:
    mesh = trimesh.load(SOURCE)
    zs = np.arange(Z_LO, Z_HI + Z_STEP, Z_STEP)
    rings = outlines(mesh, zs)
    radius, centre, coverage = sections(zs, rings)
    tube = pylon(zs, rings)
    registrations = {k: register_model(mesh, k) for k in itercfg.MODELS}

    OUT_NPZ.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT_NPZ, z=zs, radius=radius, centre=centre, coverage=coverage)
    report = {
        "source": str(SOURCE.relative_to(anat.ROOT.parent)),
        "frame": "knee axis at the origin, z up, y forward",
        "grid": [len(zs), BINS],
        "z_range": [float(zs[0]), float(zs[-1])],
        "z_step": Z_STEP,
        "rows_measured": int(np.isfinite(radius[:, 0]).sum()),
        "coverage_median": round(float(np.median(coverage[coverage > 0])), 3),
        "parts_z": json.loads((anat.WORK / "stage1.json").read_text())["parts_z_mm"],
        "pylon": tube,
        "registrations": registrations,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
