"""Turn the leg scan into the surface the cover is built on. Run once per scan.

    python -m tools.prepare_scan                       # every step
    python -m tools.prepare_scan --no-decimate --mirror
    python -m tools.prepare_scan --render renders/stage_1

In:  data/оболочка.stl
Out: backend/assets/leg_surface.npz   radius over (angle, height) + centreline
     backend/assets/leg_surface.json  what was found, and what each step did

Every step has a flag and every flag is on by default, except mirroring, which
is off for this file because it is already the mirrored copy (see config).

KNOWN LIMITATION OF THIS PROTOTYPE. From z ~ 20 up to top_z the scan is the
knee captured bent to 114 degrees: the kneecap has moved, the front of the knee
is stretched and the outline differs from a straight knee. That stretch is the
most visible part of the cover. No data here can correct it, and turning the
scan straight by rotation gives a worse result. It is recorded as a known
discrepancy, to be revisited with a new scan.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

import numpy as np
import trimesh

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.transfemoral import config as cfg
from backend.transfemoral.knee import Knee
from backend.transfemoral.scan_surface import (
    ScanData,
    ScanSurface,
    smooth_radius,
)

KNOWN_LIMITATION = (
    "z from ~20 to top_z is the knee scanned bent to 114 degrees: the kneecap is "
    "displaced, the front is stretched and the outline differs from a straight "
    "knee. This is the most visible part of the cover. It cannot be fixed from "
    "this data and straightening by rotation is worse. Known discrepancy; revisit "
    "with a new scan."
)

BENT_KNEE_DEG = 114.0
FLAT_SECTIONS = 720


# --- ray casting in a horizontal section ------------------------------------


def section_segments(mesh: trimesh.Trimesh, z: float) -> np.ndarray:
    """(n, 2, 2) segments where the plane at height z cuts the mesh."""
    lines = trimesh.intersections.mesh_plane(mesh, [0.0, 0.0, 1.0], [0.0, 0.0, z])
    return np.asarray(lines)[:, :, :2] if len(lines) else np.zeros((0, 2, 2))


def cast(segments: np.ndarray, origin: np.ndarray, theta: np.ndarray):
    """Distance along each ray to the first and the last crossing, and the count.

    A star-shaped section is crossed exactly once by every ray from inside it,
    so the count is the star test and the first distance is the radius.
    """
    d = np.stack([np.cos(theta), np.sin(theta)], axis=1)
    if len(segments) == 0:
        inf = np.full(len(theta), np.inf)
        return inf, inf, np.zeros(len(theta), dtype=int)
    a = segments[:, 0] - origin
    e = segments[:, 1] - segments[:, 0]
    den = d[:, None, 0] * e[None, :, 1] - d[:, None, 1] * e[None, :, 0]
    safe = np.where(np.abs(den) < 1e-12, 1e-12, den)
    t = (a[None, :, 0] * e[None, :, 1] - a[None, :, 1] * e[None, :, 0]) / safe
    s = (a[None, :, 0] * d[:, None, 1] - a[None, :, 1] * d[:, None, 0]) / safe
    ok = (np.abs(den) >= 1e-12) & (s >= 0.0) & (s < 1.0) & (t > 1e-9)
    first = np.where(ok, t, np.inf).min(axis=1)
    last = np.where(ok, t, -np.inf).max(axis=1)
    return first, np.where(np.isfinite(last), last, np.inf), ok.sum(axis=1)


def polygon_centroid(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    cross = x * np.roll(y, -1) - np.roll(x, -1) * y
    area = cross.sum() / 2.0
    return np.array(
        [
            ((x + np.roll(x, -1)) * cross).sum() / (6.0 * area),
            ((y + np.roll(y, -1)) * cross).sum() / (6.0 * area),
        ]
    )


def section_centre(mesh: trimesh.Trimesh, z: float, start: np.ndarray | None = None):
    """Area centroid and mean radius of the section, or None if it is open."""
    segs = section_segments(mesh, z)
    if len(segs) < 3:
        return None
    o = segs.reshape(-1, 2).mean(axis=0) if start is None else start
    theta = np.linspace(0.0, 2.0 * math.pi, FLAT_SECTIONS, endpoint=False)
    for _ in range(2):
        r, _, _ = cast(segs, o, theta)
        if not np.all(np.isfinite(r)):
            return None
        o = polygon_centroid(o[0] + r * np.cos(theta), o[1] + r * np.sin(theta))
    r, _, _ = cast(segs, o, theta)
    return o, r


# --- steps -------------------------------------------------------------------


def step_units(mesh: trimesh.Trimesh, report: dict) -> trimesh.Trimesh:
    """Millimetres, centimetres or inches, read off the length of the leg."""
    v = mesh.vertices - mesh.vertices.mean(axis=0)
    _, vecs = np.linalg.eigh(np.cov(v.T))
    length = float(np.ptp(v @ vecs[:, -1]))
    # A shin with its knee is about half a metre. Nothing in between is a leg.
    candidates = {"mm": (500.0, 1.0), "cm": (50.0, 10.0), "in": (20.0, 25.4)}
    unit, (_, factor) = min(
        candidates.items(), key=lambda kv: abs(math.log(length / kv[1][0]))
    )
    mesh = mesh.copy()
    mesh.apply_scale(factor)
    report["units"] = {"detected": unit, "scale_to_mm": factor, "length_along_axis": round(length * factor, 1)}
    return mesh


def step_align(mesh: trimesh.Trimesh, report: dict) -> trimesh.Trimesh:
    """Origin at the centroid, main axis vertical, ankle at the bottom."""
    centroid = mesh.vertices.mean(axis=0)
    v = mesh.vertices - centroid
    _, vecs = np.linalg.eigh(np.cov(v.T))
    axis = vecs[:, -1]
    h = v @ axis
    lo, hi = h.min(), h.max()
    span = hi - lo
    # The ankle end is the slender one: compare the spread across the axis in
    # the bottom and top tenths.
    across = np.linalg.norm(v - np.outer(h, axis), axis=1)
    thin_low = np.median(across[h < lo + 0.1 * span])
    thin_high = np.median(across[h > hi - 0.1 * span])
    if thin_high < thin_low:
        axis = -axis
    a = np.cross(axis, [1.0, 0.0, 0.0])
    if np.linalg.norm(a) < 0.1:
        a = np.cross(axis, [0.0, 1.0, 0.0])
    a /= np.linalg.norm(a)
    b = np.cross(axis, a)
    rotation = np.stack([a, b, axis])
    out = trimesh.Trimesh((mesh.vertices - centroid) @ rotation.T, mesh.faces, process=False)
    report["align"] = {
        "centroid": np.round(centroid, 3).tolist(),
        "main_axis": np.round(axis, 4).tolist(),
        "z_range": [round(float(out.vertices[:, 2].min()), 1), round(float(out.vertices[:, 2].max()), 1)],
    }
    return out


def _calf_and_drift(mesh: trimesh.Trimesh) -> tuple[float, float, list]:
    """The two indicators the brief names, measured from the main axis.

    Direction of the largest radius over the calf, and direction in which the
    section centres drift off the axis. Both find the front-back line of the
    shin and agree with each other to a few degrees. Neither can tell which end
    of that line is the back: a shin section is long front to back, the tibial
    crest reaches about as far from the axis as the calf does, and on this scan
    both indicators land on the crest. The sign comes from `_back_sign`.
    """
    z_lo = float(mesh.vertices[:, 2].min())
    theta = np.linspace(0.0, 2.0 * math.pi, FLAT_SECTIONS, endpoint=False)
    kernel = np.exp(-0.5 * (np.arange(-40, 41) / 12.0) ** 2)
    kernel /= kernel.sum()
    rows = []
    for z in np.arange(z_lo + 20.0, cfg.TRUST_CENTRES_BELOW_Z, 10.0):
        found = section_centre(mesh, z)
        if found is None:
            continue
        r, _, _ = cast(section_segments(mesh, z), np.zeros(2), theta)
        if not np.all(np.isfinite(r)):
            continue
        rows.append((z, found[0], found[1], r))
    # The calf is the widest stretch of the shin.
    calf = int(np.argmax([row[2].mean() for row in rows]))
    window = [k for k, row in enumerate(rows) if abs(row[0] - rows[calf][0]) <= 60.0]
    bulge = []
    for k in window:
        r = rows[k][3]
        smooth = np.convolve(np.concatenate([r[-40:], r, r[:40]]), kernel, "valid")
        bulge.append(np.exp(1j * theta[int(np.argmax(smooth))]))
    calf_dir = float(np.angle(np.mean(bulge)))
    drift = np.mean([rows[k][1] for k in window], axis=0)
    drift_dir = float(math.atan2(drift[1], drift[0]))
    return calf_dir, drift_dir, rows


def _back_sign(mesh: trimesh.Trimesh, line: np.ndarray, rows: list) -> tuple[float, float]:
    """Which way along `line` the back is, by two cues that do not share a cause.

    Mass: a calf section carries its bulk behind the middle of its own
    front-back extent, so its area centroid sits on the calf side of it.

    Knee: the scan was taken with the knee bent, so what it holds above the
    knee axis is thigh, and the thigh runs backward.

    Each returns a signed number along `line`; positive means the back is at
    +line. Both are returned so the caller can insist they agree.
    """
    theta = np.linspace(0.0, 2.0 * math.pi, FLAT_SECTIONS, endpoint=False)
    mass = []
    for z, centre, radius, _ in rows:
        pts = np.stack([centre[0] + radius * np.cos(theta), centre[1] + radius * np.sin(theta)], 1)
        along = pts @ line
        mass.append(float(centre @ line - (along.max() + along.min()) / 2.0))
    top = rows[-1]
    above = mesh.vertices[mesh.vertices[:, 2] > cfg.knee_axis_z + 20.0]
    knee = float((above[:, :2].mean(axis=0) - top[1]) @ line) if len(above) else 0.0
    return float(np.mean(mass)), knee


def step_orient(mesh: trimesh.Trimesh, report: dict) -> trimesh.Trimesh:
    """Turn about z until the back of the leg faces -y."""
    calf_dir, drift_dir, rows = _calf_and_drift(mesh)
    disagreement = abs(math.degrees((calf_dir - drift_dir + math.pi) % (2 * math.pi) - math.pi))
    report["orient"] = {
        "calf_max_radius_deg": round(math.degrees(calf_dir), 1),
        "centre_drift_deg": round(math.degrees(drift_dir), 1),
        "disagreement_deg": round(disagreement, 1),
    }
    if disagreement > cfg.MAX_ORIENTATION_DISAGREEMENT:
        raise SystemExit(
            f"front and back disagree by {disagreement:.0f} degrees "
            f"(calf bulge {math.degrees(calf_dir):.0f}, centre drift "
            f"{math.degrees(drift_dir):.0f}); limit is "
            f"{cfg.MAX_ORIENTATION_DISAGREEMENT:.0f}. Check the scan."
        )
    ap = math.atan2(
        math.sin(calf_dir) + math.sin(drift_dir), math.cos(calf_dir) + math.cos(drift_dir)
    )
    line = np.array([math.cos(ap), math.sin(ap)])
    mass, knee = _back_sign(mesh, line, rows)
    report["orient"]["back_by_section_mass_mm"] = round(mass, 2)
    report["orient"]["back_by_thigh_mm"] = round(knee, 1)
    if mass == 0.0 or knee == 0.0 or (mass > 0) != (knee > 0):
        raise SystemExit(
            f"cannot tell the back from the front: section mass says {mass:+.2f} mm, "
            f"thigh says {knee:+.1f} mm along {math.degrees(ap):.0f} degrees. Check the scan."
        )
    back = ap if mass > 0 else ap + math.pi
    report["orient"]["indicators_point"] = "back" if mass > 0 else "front"
    report["orient"]["back_deg"] = round(math.degrees(math.atan2(math.sin(back), math.cos(back))), 1)
    # Rotate so that `back` lands on -pi/2.
    turn = -math.pi / 2.0 - back
    c, s = math.cos(turn), math.sin(turn)
    rot = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    report["orient"]["rotated_about_z_deg"] = round(math.degrees(turn), 1)
    return trimesh.Trimesh(mesh.vertices @ rot.T, mesh.faces, process=False)


def step_mirror(mesh: trimesh.Trimesh, report: dict) -> trimesh.Trimesh:
    """Carry the healthy leg across to the prosthetic side: x -> -x."""
    v = mesh.vertices.copy()
    v[:, 0] *= -1.0
    report["mirror"] = {"applied": True}
    return trimesh.Trimesh(v, mesh.faces[:, ::-1], process=False)


def step_axis(mesh: trimesh.Trimesh, report: dict) -> dict:
    """Centreline through section centres, straight above the trusted part."""
    z_lo = float(mesh.vertices[:, 2].min())
    trust = cfg.TRUST_CENTRES_BELOW_Z
    zs, cs, rs = [], [], []
    for z in np.arange(z_lo + 3.0, trust + 1e-6, cfg.CENTRE_STEP):
        found = section_centre(mesh, z)
        if found is None:
            continue
        zs.append(z)
        cs.append(found[0])
        rs.append(found[1].mean())
    zs, cs, rs = np.array(zs), np.array(cs), np.array(rs)
    px = np.polyfit(zs, cs[:, 0], cfg.CENTRE_SMOOTHING)
    py = np.polyfit(zs, cs[:, 1], cfg.CENTRE_SMOOTHING)
    run = zs >= trust - cfg.TANGENT_RUN
    tx = float(np.polyfit(zs[run], cs[run, 0], 1)[0])
    ty = float(np.polyfit(zs[run], cs[run, 1], 1)[0])
    at_trust = np.array([np.polyval(px, trust), np.polyval(py, trust)])

    def centre(z):
        z = np.asarray(z, dtype=float)
        below = np.stack([np.polyval(px, z), np.polyval(py, z)], axis=-1)
        above = at_trust + np.stack([tx * (z - trust), ty * (z - trust)], axis=-1)
        return np.where((z <= trust)[..., None], below, above)

    # How far the section centres wander off one straight line through the shin.
    line = np.polyfit(zs, cs, 1)
    straight = np.stack([np.polyval(line[:, 0], zs), np.polyval(line[:, 1], zs)], axis=1)
    report["axis"] = {
        "sections": len(zs),
        "trusted_below_z": trust,
        "tangent_fitted_over": [round(trust - cfg.TANGENT_RUN, 1), trust],
        "tangent_dxdz_dydz": [round(tx, 4), round(ty, 4)],
        "drift_from_straight_axis_mm": round(float(np.ptp(np.hypot(*(cs - straight).T))), 1),
        "drift_from_z_axis_mm": round(float(np.hypot(*cs.T).max()), 1),
        "mean_section_radius_mm": round(float(rs.mean()), 1),
        "residual_to_fit_mm": round(float(np.abs(centre(zs) - cs).max()), 2),
    }
    return {"centre": centre, "radius_z": zs, "radius": rs}


def step_top(mesh: trimesh.Trimesh, report: dict) -> trimesh.Trimesh:
    cut = trimesh.intersections.slice_mesh_plane(
        mesh, plane_normal=[0.0, 0.0, -1.0], plane_origin=[0.0, 0.0, cfg.top_z]
    )
    report["top"] = {
        "top_z": cfg.top_z,
        "knee_axis_z": cfg.knee_axis_z,
        "faces_before": len(mesh.faces),
        "faces_after": len(cut.faces),
    }
    return cut


def _local_shin_radius(axis: dict, z: np.ndarray) -> np.ndarray:
    """Shin radius at height z; above the trusted part, the value at its top."""
    return np.interp(np.minimum(z, axis["radius_z"][-1]), axis["radius_z"], axis["radius"])


def step_thigh(mesh: trimesh.Trimesh, axis: dict, report: dict) -> trimesh.Trimesh:
    """Drop what is left of the thigh below top_z."""
    v = mesh.vertices
    c = axis["centre"](v[:, 2])
    dist = np.hypot(v[:, 0] - c[:, 0], v[:, 1] - c[:, 1])
    far = dist > cfg.THIGH_RADIUS_FACTOR * _local_shin_radius(axis, v[:, 2])
    keep_faces = ~far[mesh.faces].any(axis=1)
    trimmed = trimesh.Trimesh(v, mesh.faces[keep_faces], process=False)
    trimmed.remove_unreferenced_vertices()
    parts = trimmed.split(only_watertight=False)
    main = max(parts, key=lambda p: p.area) if len(parts) else trimmed
    dropped_parts = [p for p in parts if p is not main]
    report["thigh"] = {
        "radius_factor": cfg.THIGH_RADIUS_FACTOR,
        "vertices_beyond_radius": int(far.sum()),
        "faces_removed_by_radius": int((~keep_faces).sum()),
        "components_removed": len(dropped_parts),
        "faces_in_removed_components": int(sum(len(p.faces) for p in dropped_parts)),
    }
    return main


def step_decimate(mesh: trimesh.Trimesh, report: dict) -> trimesh.Trimesh:
    """Down to the working triangle count by vertex clustering, if above it."""
    n = len(mesh.faces)
    if n <= cfg.WORK_TRIANGLES:
        report["decimate"] = {"faces": n, "target": cfg.WORK_TRIANGLES, "applied": False}
        return mesh
    cell = math.sqrt(mesh.area / cfg.WORK_TRIANGLES * 2.0)
    for _ in range(12):
        key = np.floor(mesh.vertices / cell).astype(np.int64)
        _, inverse = np.unique(key, axis=0, return_inverse=True)
        inverse = inverse.ravel()
        faces = inverse[mesh.faces]
        faces = faces[(faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])]
        if len(faces) <= cfg.WORK_TRIANGLES:
            break
        cell *= 1.1
    sums = np.zeros((inverse.max() + 1, 3))
    np.add.at(sums, inverse, mesh.vertices)
    counts = np.bincount(inverse)[:, None]
    out = trimesh.Trimesh(sums / counts, faces, process=True)
    report["decimate"] = {"faces": n, "target": cfg.WORK_TRIANGLES, "applied": True, "faces_after": len(out.faces)}
    return out


def step_sample(
    mesh: trimesh.Trimesh, axis: dict, report: dict, untrimmed: trimesh.Trimesh | None = None
) -> dict:
    """Radius over (angle, height), and where the scan actually was.

    `untrimmed` is the scan before the thigh was taken off; the plain ray hit
    rate is read from it, so it compares with the coverage the brief quotes.
    """
    z_lo = float(mesh.vertices[:, 2].min())
    theta = np.linspace(0.0, 2.0 * math.pi, cfg.GRID_THETA, endpoint=False)
    heights = np.arange(math.ceil(z_lo), cfg.top_z + 1e-6, 1.0)
    rows = {}
    multi = 0
    probes = 0
    for z in heights:
        zz = min(z, cfg.top_z - 1e-3)
        segs = section_segments(mesh, zz)
        o = axis["centre"](zz)
        first, _, hits = cast(segs, o, theta)
        limit = cfg.THIGH_RADIUS_FACTOR * _local_shin_radius(axis, np.array(zz))
        known = np.isfinite(first) & (first <= limit)
        raw_first = cast(section_segments(untrimmed, zz), o, theta)[0] if untrimmed is not None else first
        rows[z] = (first, known, np.isfinite(raw_first))
        probes += int(known.sum())
        multi += int((hits[known] > 1).sum())
    full = [z for z in heights if rows[z][1].all()]
    bottom = float(min(full))
    grid_z = np.arange(bottom, cfg.top_z - 1e-6, cfg.GRID_DZ)
    grid_z = np.append(grid_z, cfg.top_z)
    R = np.zeros((len(grid_z), len(theta)))
    known = np.zeros_like(R, dtype=bool)
    centre = np.zeros((len(grid_z), 2))
    for j, z in enumerate(grid_z):
        zz = min(max(z, bottom + 1e-3), cfg.top_z - 1e-3)
        segs = section_segments(mesh, zz)
        o = axis["centre"](zz)
        first, _, _ = cast(segs, o, theta)
        limit = cfg.THIGH_RADIUS_FACTOR * _local_shin_radius(axis, np.array(zz))
        ok = np.isfinite(first) & (first <= limit)
        R[j] = np.where(ok, first, np.nan)
        known[j] = ok
        centre[j] = o
    shown = [z for z in heights if z in (60, 70, 75, 80, 90, 100, 104)]
    coverage = {str(int(z)): round(float(rows[z][1].mean()) * 100.0, 1) for z in shown}
    raw = {str(int(z)): round(float(rows[z][2].mean()) * 100.0, 1) for z in shown}
    report["sample"] = {
        "grid": [len(grid_z), len(theta)],
        "dz_mm": cfg.GRID_DZ,
        "bottom_z": bottom,
        "ray_hits_pct_by_z": raw,
        "kept_after_thigh_pct_by_z": coverage,
        "full_coverage_up_to_z": float(max(z for z in heights if rows[z][1].all() and all(rows[w][1].all() for w in heights if bottom <= w <= z))),
        "star_probes": probes,
        "star_problems": multi,
    }
    return {"theta": theta, "z": grid_z, "R": R, "known": known, "centre": centre}


def _intervals(mask: np.ndarray) -> list[tuple[int, int]]:
    """Runs of True in a periodic boolean row, as (start, length)."""
    n = len(mask)
    if mask.all():
        return [(0, n)]
    start = int(np.argmin(mask))
    rolled = np.roll(mask, -start)
    runs, k = [], 0
    while k < n:
        if rolled[k]:
            j = k
            while j < n and rolled[j]:
                j += 1
            runs.append(((k + start) % n, j - k))
            k = j
        else:
            k += 1
    return runs


def step_fill(grid: dict, knee: Knee, report: dict) -> dict:
    """Close the scanner's blind spot by interpolating round each section."""
    from scipy.interpolate import PchipInterpolator

    theta, R, known = grid["theta"], grid["R"].copy(), grid["known"]
    n = len(theta)
    widest, widest_outside, rows_with_gaps = 0.0, 0.0, 0
    step = 360.0 / n
    for j in range(len(R)):
        row_known = known[j]
        if row_known.all():
            continue
        rows_with_gaps += 1
        t = theta[row_known]
        r = R[j, row_known]
        tt = np.concatenate([t - 2 * math.pi, t, t + 2 * math.pi])
        rr = np.concatenate([r, r, r])
        R[j, ~row_known] = PchipInterpolator(tt, rr)(theta[~row_known])
        z = grid["z"][j]
        c = grid["centre"][j]
        pts = np.stack(
            [c[0] + R[j] * np.cos(theta), c[1] + R[j] * np.sin(theta), np.full(n, z)], axis=1
        )
        outside = (~row_known) & (knee.notch_distance(pts) > 0.0)
        for _, length in _intervals(~row_known):
            widest = max(widest, length * step)
        for _, length in _intervals(outside):
            widest_outside = max(widest_outside, length * step)
    grid["R"] = R
    report["fill"] = {
        "rows_with_gaps": rows_with_gaps,
        "widest_gap_deg": round(widest, 1),
        "widest_gap_outside_notch_deg": round(widest_outside, 1),
        "unknown_share_pct": round(float((~known).mean()) * 100.0, 2),
    }
    return grid


def step_smoothing_check(grid: dict, report: dict) -> None:
    """The smoothing slider can never move the surface more than it may."""
    out = {}
    for strength in (cfg.SMOOTH_DEFAULT, 1.0):
        smooth, shift = smooth_radius(grid["R"], cfg.GRID_DZ, strength)
        # Along the normal: the radial move times the cosine to the normal.
        R = smooth
        theta = grid["theta"]
        dR_dth = (np.roll(R, -1, axis=1) - np.roll(R, 1, axis=1)) / (2 * (theta[1] - theta[0]))
        dR_dz = np.gradient(R, grid["z"], axis=0)
        cosine = R / np.sqrt(R**2 + dR_dth**2 + (R * dR_dz) ** 2)
        normal = float(np.max(np.abs(smooth - grid["R"]) * cosine))
        out[f"strength_{strength:g}"] = {
            "max_radial_shift_mm": round(shift, 3),
            "max_normal_shift_mm": round(normal, 3),
            "limit_mm": cfg.SMOOTH_MAX_SHIFT,
            "ok": bool(normal <= cfg.SMOOTH_MAX_SHIFT + 1e-9),
        }
    report["smoothing"] = out


def surface_mesh(surface: ScanSurface, nu: int = 360, nv: int = 240) -> trimesh.Trimesh:
    """The stored surface as an open tube, for looking at."""
    pts, _ = surface.grid(nu, nv)
    j, i = np.meshgrid(np.arange(nv - 1), np.arange(nu), indexing="ij")
    j, i = j.ravel(), i.ravel()
    i1 = (i + 1) % nu
    a, b, c, d = j * nu + i, j * nu + i1, (j + 1) * nu + i1, (j + 1) * nu + i
    faces = np.vstack([np.stack([a, b, c], 1), np.stack([a, c, d], 1)])
    return trimesh.Trimesh(pts.reshape(-1, 3), faces, process=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", default=str(cfg.SCAN_FILE))
    ap.add_argument("--out", default=str(cfg.SURFACE_FILE))
    ap.add_argument("--render", default="", help="write side/front/back renders to this stem")
    for name in ("units", "align", "orient", "axis", "top", "thigh", "decimate", "fill"):
        ap.add_argument(f"--no-{name}", dest=name, action="store_false", default=True)
    ap.add_argument("--mirror", dest="mirror", action="store_true", default=cfg.MIRROR_SCAN)
    ap.add_argument("--no-mirror", dest="mirror", action="store_false")
    args = ap.parse_args(argv)

    report: dict = {
        "scan": pathlib.Path(args.scan).name,
        "knee_module": cfg.KNEE_MODULE,
        "known_limitation": KNOWN_LIMITATION,
        "scan_knee_flexion_deg": BENT_KNEE_DEG,
    }
    mesh = trimesh.load(args.scan, force="mesh", process=True)
    report["input"] = {
        "faces": len(mesh.faces),
        "vertices": len(mesh.vertices),
        "bodies": int(mesh.body_count),
        "winding_consistent": bool(mesh.is_winding_consistent),
    }
    if args.units:
        mesh = step_units(mesh, report)
    if args.align:
        mesh = step_align(mesh, report)
    if args.orient:
        mesh = step_orient(mesh, report)
    if args.mirror:
        mesh = step_mirror(mesh, report)
    else:
        report["mirror"] = {"applied": False, "why": "file is already the mirrored copy"}
    if not args.axis:
        raise SystemExit("the axis step cannot be skipped: everything after it stands on it")
    axis = step_axis(mesh, report)
    if args.top:
        mesh = step_top(mesh, report)
    untrimmed = mesh
    if args.thigh:
        mesh = step_thigh(mesh, axis, report)
    if args.decimate:
        mesh = step_decimate(mesh, report)
    grid = step_sample(mesh, axis, report, untrimmed)

    # The knee axis sits over the last section the centres can be trusted at,
    # not on the tangent carried up past it: that tangent is the calf's forward
    # drift into the knee, and fifty millimetres up it puts the axis a
    # centimetre in front of the joint.
    centre_at_knee = axis["centre"](cfg.TRUST_CENTRES_BELOW_Z)
    knee = Knee.from_config(float(centre_at_knee[1]))
    if args.fill:
        grid = step_fill(grid, knee, report)
    elif not grid["known"].all():
        raise SystemExit("without filling, the blind spot leaves holes in the surface")
    step_smoothing_check(grid, report)

    # The section at the knee, and how far behind the axis its back is.
    j = int(np.argmin(np.abs(grid["z"] - cfg.knee_axis_z)))
    c = grid["centre"][j]
    xs = c[0] + grid["R"][j] * np.cos(grid["theta"])
    ys = c[1] + grid["R"][j] * np.sin(grid["theta"])
    report["knee"] = {
        "axis_y": round(knee.axis_y, 2),
        "axis_z": knee.axis_z,
        "top_z": cfg.top_z,
        "flexion_angle": cfg.flexion_angle,
        "notch_split": cfg.notch_split,
        "section_at_axis_front_back_mm": round(float(np.ptp(ys)), 1),
        "section_at_axis_across_mm": round(float(np.ptp(xs)), 1),
        "back_behind_axis_mm": round(float(knee.axis_y - ys.min()), 1),
    }
    behind = report["knee"]["back_behind_axis_mm"]
    lo, hi = knee.back_height_range(behind)
    report["knee"]["notch_height_range_on_back"] = [
        round(lo, 1) if math.isfinite(lo) else None,
        round(hi, 1) if math.isfinite(hi) else "above the top",
    ]

    meta = {
        "bottom_z": float(grid["z"][0]),
        "top_z": float(grid["z"][-1]),
        "knee_axis_y": knee.axis_y,
        "mirrored": bool(args.mirror),
    }
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tangent = np.array(report["axis"]["tangent_dxdz_dydz"], dtype=float)
    np.savez_compressed(
        out,
        theta=grid["theta"],
        z=grid["z"],
        R=grid["R"].astype(np.float32),
        known=grid["known"],
        centre=grid["centre"],
        tangent=tangent,
        meta=json.dumps(meta),
    )
    report["output"] = {"surface": str(out.relative_to(ROOT)), **meta}
    out.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.render:
        from tools.render import render_views

        surface = ScanSurface(ScanData.load(out), cfg.SMOOTH_DEFAULT)
        tube = surface_mesh(surface)
        for path in render_views([(tube, (150, 170, 182))], pathlib.Path(args.render)):
            print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
