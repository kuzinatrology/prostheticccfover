"""Stage 4 — the cover surface.

A stack of sections along the prosthesis, lofted into one smooth skin.  Each
section has the shape of a human shank at that relative height (stage 3) and is
scaled until it clears the prosthesis at that height by the clearance (stage 2).
Where the anatomical silhouette is already wider than it needs to be, it is
left alone; where it is narrower, it inflates by exactly the shortfall.

The rim is a smooth periodic spline in (angle, height).  The grid is built so
that every column ends on that curve, so the edge is the curve itself and not a
staircase of triangle edges.

    .venv/bin/python -m anatomic.stage4_surface
"""

from __future__ import annotations

import json
from functools import lru_cache

import numpy as np
import trimesh
from scipy.interpolate import CubicSpline, RegularGridInterpolator
from scipy.ndimage import gaussian_filter, gaussian_filter1d, maximum_filter, maximum_filter1d

from . import config, render

ANGLES = np.linspace(-np.pi, np.pi, config.CONTOUR_BINS, endpoint=False) + np.pi / config.CONTOUR_BINS


def envelope(vertices: np.ndarray, z: float, centre: np.ndarray, slab: float) -> np.ndarray | None:
    """Largest radius of the prosthesis at each angle around `centre`."""
    band = vertices[np.abs(vertices[:, 2] - z) <= slab]
    if len(band) < 20:
        return None
    offset = band[:, :2] - centre
    angle = np.arctan2(offset[:, 1], offset[:, 0])
    index = np.clip(((angle + np.pi) / (2 * np.pi) * config.CONTOUR_BINS).astype(int), 0, config.CONTOUR_BINS - 1)
    out = np.full(config.CONTOUR_BINS, -np.inf)
    np.maximum.at(out, index, np.linalg.norm(offset, axis=1))
    out[np.isneginf(out)] = np.nan
    known = np.flatnonzero(~np.isnan(out))
    if len(known) < config.CONTOUR_BINS // 4:
        return None
    if len(known) < config.CONTOUR_BINS:
        out = np.interp(
            ANGLES,
            np.concatenate([ANGLES[known] - 2 * np.pi, ANGLES[known], ANGLES[known] + 2 * np.pi]),
            np.tile(out[known], 3),
        )
    # Spread each bin's reading onto its neighbours. A bin is a 2 degree slice,
    # and a point sitting at the edge of one is nearer the surface than the
    # bin's own maximum says; without this the clearance comes out a millimetre
    # and a half short of what it was asked for.
    return maximum_filter1d(out, 3, mode="wrap")


def periodic_spline(control: list[tuple[float, float]]) -> CubicSpline:
    """A smooth closed curve through a handful of (angle, value) points."""
    angles = np.array([np.radians(a) for a, _ in control])
    values = np.array([v for _, v in control])
    order = np.argsort(angles)
    angles, values = angles[order], values[order]
    angles = np.append(angles, angles[0] + 2 * np.pi)
    values = np.append(values, values[0])
    return CubicSpline(angles, values, bc_type="periodic")


@lru_cache(maxsize=4)
def prosthesis_envelope(step: float) -> dict:
    """The prosthesis, measured once: where its centre line runs and how far
    its surface reaches at every angle, section by section.

    None of this depends on a cover parameter, so it is cached — a slider move
    then costs a scale and a loft rather than another pass over the scan.
    """
    prosthesis = trimesh.load(config.WORK / "stage2_prosthesis.stl", process=False)
    pv = np.asarray(prosthesis.vertices)
    sections = json.loads((config.WORK / "stage2.json").read_text())["sections"]

    pylon_width = min(r["width_mm"] for r in sections if r["z"] > -400)
    adapter_top = max(
        r["z"] for r in sections
        if r["z"] < -250 and r["width_mm"] > pylon_width + 4
    )

    zs = np.arange(adapter_top, config.COVER_TOP_LIMIT + step, step)
    raw = []
    for z in zs:
        band = pv[np.abs(pv[:, 2] - z) <= step * 2]
        # Mid-point of the section's extent, not its median: the cover has to
        # enclose the section, and this is the centre that needs the least
        # radius to do it.
        raw.append(
            (band[:, :2].min(axis=0) + band[:, :2].max(axis=0)) / 2
            if len(band) > 20 else [np.nan, np.nan]
        )
    raw = np.array(raw)
    for i in range(2):
        column = raw[:, i]
        good = ~np.isnan(column)
        raw[:, i] = np.interp(zs, zs[good], column[good])
    sigma = config.CENTRELINE_SMOOTH_MM / step / 3
    centre = np.stack([gaussian_filter1d(raw[:, i], sigma, mode="nearest") for i in range(2)], -1)
    # ...and brought back onto the knee axis as it reaches the joint.
    w = np.clip(1.0 + zs / config.CENTRE_BLEND_MM, 0.0, 1.0)
    centre *= (1.0 - (w * w * (3.0 - 2.0 * w)))[:, None]

    reach = np.zeros((len(zs), config.CONTOUR_BINS))
    for i, z in enumerate(zs):
        # Only below the knee axis is the prosthesis part of the shank and so
        # something the cover has to contain. Above it sits the socket, which
        # turns with the thigh: the cover must miss it, not wrap it, and that
        # is what the flexion sweep tests.
        if z > 0.0:
            break
        env = envelope(pv, z, centre[i], step * 2)
        reach[i] = env if env is not None else (reach[i - 1] if i else np.zeros(config.CONTOUR_BINS))

    return {"zs": zs, "centre": centre, "reach": reach, "adapter_top": float(adapter_top),
            "prosthesis": prosthesis}


def build(
    rim_control=None,
    clearance: float | None = None,
    wall: float | None = None,
    fullness: float | None = None,
    top_z: float | None = None,
    bottom_clearance: float | None = None,
    rows: int | None = None,
    rim: np.ndarray | None = None,
    girth: np.ndarray | None = None,
) -> dict:
    """One cover surface.  Everything left as None comes from config."""
    clearance = config.CLEARANCE_MM if clearance is None else clearance
    fullness_knob = config.COVER_FULLNESS if fullness is None else fullness
    top_z = config.COVER_TOP_Z if top_z is None else top_z
    bottom_clearance = (
        config.BOTTOM_CLEARANCE_MM if bottom_clearance is None else bottom_clearance
    )
    rows = config.COVER_ROWS if rows is None else rows
    wall = config.WALL_THICKNESS_MM if wall is None else wall
    rim_control = rim_control or config.rim_control()

    step = config.COVER_SECTION_STEP
    measured = prosthesis_envelope(step)
    stage3 = np.load(config.WORK / "stage3_profile.npz")

    bottom_z = measured["adapter_top"] + bottom_clearance
    # The skin is always computed over the whole height the scan supports, and
    # `top_z` only says where to cut it. Trimming first would let the
    # smoothing below run into the end of the array and give the rim solver a
    # different surface from the one the cover is finally built on.
    span = (measured["zs"] >= bottom_z - 1e-6) & (measured["zs"] <= config.COVER_TOP_LIMIT + 1e-6)
    zs = measured["zs"][span]
    centre = measured["centre"][span]
    # The clearance is to the INSIDE of the wall, which is what the hardware
    # actually meets, so the outer surface has to stand a wall further out.
    required = measured["reach"][span] + clearance + wall

    # Above the knee axis there is no prosthesis to contain — there is a
    # socket to miss. Same arithmetic, different reason: the cover has to
    # stand clear of the thigh rather than wrap the shank.
    above = zs > 0.0
    if above.any():
        from . import stage5_flexion

        heights, radii = stage5_flexion.thigh_body(measured["prosthesis"])
        required[above] = np.maximum(
            required[above],
            (np.interp(zs[above], heights, radii) + clearance + wall)[:, None],
        )

    shape_at = RegularGridInterpolator(
        (stage3["t"], np.append(stage3["angles"], stage3["angles"][0] + 2 * np.pi)),
        np.hstack([stage3["shape"], stage3["shape"][:, :1]]),
        bounds_error=False, fill_value=None,
    )
    # Where each height of the cover sits on the human leg. Anchored at two
    # landmarks, not stretched to fit: z = 0 is the knee joint on both, and
    # the bottom of the cover is ANATOMY_T_BOTTOM of the way up the shank.
    # Above the knee the same scale simply carries on up the thigh.
    knee_t = float(stage3["knee_t"])
    t = knee_t * (1.0 + (1.0 - config.ANATOMY_T_BOTTOM) * zs / (0.0 - bottom_z))
    shape = np.array([shape_at(np.stack([np.full_like(ANGLES, ti), ANGLES], -1)) for ti in t])
    # The section shape is read off sixty-one slices of the MakeHuman leg and
    # interpolated straight between them, which leaves a faint band every
    # seven millimetres up the cover. A light blur along the height takes the
    # bands out without touching the silhouette, which is carried by `scale`.
    shape = gaussian_filter1d(shape, config.SHAPE_SMOOTH_MM / step, axis=0, mode="nearest")

    # How full the leg is at each height, in millimetres. MakeHuman sets the
    # size; below the calf the reference renders set the taper.
    if girth is not None:
        anatomical = np.asarray(girth, dtype=float)
    elif config.GIRTH_FROM_REFERENCE:
        from . import reference

        anatomical = reference.leg_girth(zs, bottom_z, stage3["t"], stage3["mean_radius"], t)
    else:
        anatomical = np.interp(t, stage3["t"], stage3["mean_radius"])

    # The profile is already a leg's own girth in millimetres, so it is used at
    # its own size and the knob only nudges it.
    fullness_scale = fullness_knob
    scale = anatomical * fullness_scale
    needed_scale = (required / shape).max(axis=1)
    needed_scale[zs > 0.0] = 0.0

    # Where the hardware is wider than the leg, the surface swells in that
    # direction only — and only the swelling is smoothed, never the silhouette.
    # Blurring the whole surface with a rolling maximum smears the widest
    # section of the leg over its neighbours: it was costing three millimetres
    # of girth everywhere and flattening the calf into the knee, which is most
    # of what made the leg read as a post rather than a leg.
    leg = shape * scale[:, None]
    swell = np.maximum(required - leg, 0.0)

    # Dilate then blur the swelling: blurring alone would dip it back inside
    # the clearance at a local peak, and dilating first cannot.
    window = int(round(config.GIRTH_SMOOTH_MM / step)) | 1
    ring = int(round(config.CONTOUR_BINS * config.GIRTH_SMOOTH_ARC / 360.0)) | 1
    grown = maximum_filter(swell, size=(window, ring), mode="nearest")
    grown = np.concatenate([grown[:, -ring:], grown, grown[:, :ring]], axis=1)
    grown = gaussian_filter(grown, sigma=(window / 4.0, ring / 4.0), mode="nearest")
    radius = np.maximum(leg + grown[:, ring:-ring], required)

    # A rim traced off the reference comes in ready; otherwise it is splined
    # through the control points.
    rim = periodic_spline(rim_control)(ANGLES) if rim is None else np.asarray(rim, dtype=float)
    rim = np.clip(rim, bottom_z + 20.0, top_z)

    grid = np.empty((rows, config.CONTOUR_BINS, 3))
    for j in range(config.CONTOUR_BINS):
        column_z = np.linspace(bottom_z, rim[j], rows)
        r = np.interp(column_z, zs, radius[:, j])
        grid[:, j, 0] = np.interp(column_z, zs, centre[:, 0]) + r * np.cos(ANGLES[j])
        grid[:, j, 1] = np.interp(column_z, zs, centre[:, 1]) + r * np.sin(ANGLES[j])
        grid[:, j, 2] = column_z

    vertices, faces = loft(grid)
    mesh = trimesh.Trimesh(vertices, faces, process=False)

    report = {
        "bottom_z": round(float(bottom_z), 1),
        "top_z": round(float(top_z), 1),
        "adapter_top_z": round(measured["adapter_top"], 1),
        "clearance_mm": clearance,
        "wall_mm": wall,
        "sections": int(len(zs)),
        "fullness_scale": round(float(fullness_scale), 4),
        "swelling_over_leg_mm": round(float((radius - shape * scale[:, None]).max()), 1),
        "rim_control": [list(p) for p in rim_control],
        "rim_provisional": config.RIM_PROVISIONAL,
        "max_radius_mm": round(float(radius.max()), 1),
        "min_radius_mm": round(float(radius.min()), 1),
        "inflated_over_silhouette_mm": round(
            float((radius - shape * scale[:, None]).clip(0).max()), 1),
        "widest_at_z": round(float(zs[np.argmax(scale)]), 1),
        "faces": int(len(faces)),
    }
    return {
        "mesh": mesh, "grid": grid, "zs": zs, "scale": scale, "needed": needed_scale,
        "anatomical": anatomical * fullness_scale, "radius": radius, "centre": centre,
        "rim": rim, "report": report, "prosthesis": measured["prosthesis"],
    }


def loft(grid: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Turn the (rows x columns) grid into a surface, capped at the bottom."""
    rows, cols, _ = grid.shape
    vertices = grid.reshape(-1, 3)
    index = np.arange(rows * cols).reshape(rows, cols)
    a = index[:-1, :]
    b = index[:-1, (np.arange(cols) + 1) % cols]
    c = index[1:, (np.arange(cols) + 1) % cols]
    d = index[1:, :]
    faces = np.concatenate([
        np.stack([a, b, c], -1).reshape(-1, 3),
        np.stack([a, c, d], -1).reshape(-1, 3),
    ])

    centre = len(vertices)
    vertices = np.vstack([vertices, grid[0].mean(axis=0)])
    ring = index[0]
    cap = np.stack([np.full(cols, centre), ring[(np.arange(cols) + 1) % cols], ring], -1)
    return vertices, np.vstack([faces, cap])


def draw(built: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mesh = built["mesh"]
    v, f = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    pv = np.asarray(built["prosthesis"].vertices)
    pf = np.asarray(built["prosthesis"].faces)
    inside = pv[:, 2] <= built["report"]["top_z"] + 30
    pf = pf[inside[pf].all(axis=1)]

    paths = []
    for view in ("front", "side", "three_quarter"):
        path = config.RENDERS / f"stage4_{view}.png"
        render.render([(v, f, config.PART_COLOURS["socket"])], view, path,
                      title=f"stage 4 — cover, {view.replace('_', ' ')}")
        paths.append(path)
    render.contact_sheet(paths, config.RENDERS / "stage4_sheet.png", columns=3)

    render.render(
        [(pv, pf, config.PART_COLOURS["knee"]), (v, f, (206, 176, 96))],
        "side", config.RENDERS / "stage4_fit.png",
        title="stage 4 — cover over the prosthesis (cut away is the near half)",
    )

    grid = built["grid"]
    rim_v, rim_f = loft(grid[int(config.COVER_ROWS * 0.82):])
    render.render([(rim_v, rim_f, config.PART_COLOURS["socket"])],
                  (0.55, 0.72, -0.42), config.RENDERS / "stage4_rim.png", height=900,
                  title="stage 4 — the rim close up")

    fig, axes = plt.subplots(1, 2, figsize=(11, 5.4), constrained_layout=True)
    axes[0].plot(built["anatomical"], built["zs"], label="anatomical silhouette")
    axes[0].plot(built["needed"], built["zs"], label="prosthesis + clearance")
    axes[0].plot(built["scale"], built["zs"], lw=2, label="cover (smoothed max)")
    axes[0].set_xlabel("section scale"); axes[0].set_ylabel("z, mm (0 = knee axis)")
    axes[0].grid(alpha=0.3); axes[0].legend(); axes[0].set_title("where the silhouette had to inflate")
    axes[1].plot(np.degrees(ANGLES), built["rim"])
    axes[1].set_xlabel("angle around the section, deg  (90 front, 270 back)")
    axes[1].set_ylabel("rim height, mm"); axes[1].grid(alpha=0.3)
    axes[1].set_title("rim curve")
    fig.savefig(config.RENDERS / "stage4_profiles.png", dpi=130)


def main() -> None:
    built = build()
    (config.WORK / "stage4.json").write_text(json.dumps(built["report"], indent=2))
    built["mesh"].export(config.WORK / "stage4_surface.stl")
    draw(built)
    print(json.dumps(built["report"], indent=2))


if __name__ == "__main__":
    main()
