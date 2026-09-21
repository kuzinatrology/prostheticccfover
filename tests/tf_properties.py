"""The transfemoral cover's invariants, checked on what was built.

Each check reads the finished bodies: vertices, rays fired through the meshes,
volumes of intersections. The generator's fields and plans are used only to
say where to look (which point is a magnet, which body is the back half), never
as the answer.
"""

from __future__ import annotations

import math

import numpy as np
from manifold3d import Manifold, OpType

from backend import measure
from backend import mesh_build as mb
from backend.printer_profile import DEFAULT_PROFILE as PROFILE
from backend.transfemoral import config as cfg
from backend.transfemoral import mounts as mt
from backend.transfemoral.generator import DRAFT, TFCover, audit, generate
from backend.transfemoral.params import TFParams


def _crossings(hits, length: float) -> list[float]:
    """Hit distances in mm, with crossings counted twice dropped.

    A ray through the exact edge two triangles share is reported by each of
    them, a hundredth of a millimetre apart; that is one crossing, not a wall
    a hundredth thick."""
    d = sorted(h.distance * length for h in hits)
    out: list[float] = []
    for x in d:
        if out and x - out[-1] < 0.05:
            out.pop()
            continue
        out.append(x)
    return out


RAY_TOLERANCE = 0.93
"""Rays land between mesh vertices, where a facetted wall reads a touch thin."""

TOUCH = 1.0
"""mm^3 of overlap below which two bodies are touching, not intersecting."""


def build(params: TFParams) -> TFCover:
    return generate(params.clamped(), quality=DRAFT)


def check(params: TFParams, cover: TFCover | None = None) -> list[str]:
    cover = cover or build(params)
    faults: list[str] = []
    faults += closed(cover)
    faults += outside_sector(cover)
    faults += thigh_clears(cover)
    faults += walls(cover)
    faults += sockets_coaxial(cover)
    faults += parts_apart(cover)
    faults += edge_struts(cover)
    return faults


# --- 1. every body is closed ----------------------------------------------------


def closed(cover: TFCover) -> list[str]:
    faults = audit(cover)
    for name, mesh in cover.bodies.items():
        man = mb.to_manifold(mesh)
        if man.status().name != "NoError" or man.is_empty():
            faults.append(f"{name}: manifold status {man.status().name}")
    return faults


# --- 2. nothing of the cover in the sector ----------------------------------------


def _shell_vertices(cover: TFCover, name: str) -> np.ndarray:
    """A half's vertices, without the clamp parts fused inside it."""
    v = cover.bodies[name].vertices
    depth, _ = mt._depth(cover.layout.surface, v)
    return v[depth <= cover.spec.shelf_bottom + 1.0]


def outside_sector(cover: TFCover) -> list[str]:
    knee = cover.layout.knee
    faults = []
    for name in ("front", "back"):
        v = _shell_vertices(cover, name)
        inside = knee.in_sector(v)
        if inside.any():
            faults.append(f"{name}: {int(inside.sum())} vertices inside the notch sector")
    lower = cover.bodies.get("lower_clamp_back")
    if lower is not None and knee.in_sector(lower.vertices).any():
        faults.append("lower clamp back part reaches into the sector")
    return faults


# --- 3. the thigh turns through without touching -----------------------------------


def thigh_clears(cover: TFCover, step_deg: float = 0.25) -> list[str]:
    """Turn the thigh from 0 to the flexion angle and look for any contact.

    A leg-radius cylinder standing on top_z, turned about the knee axis. The
    points are turned back instead, finely, and tested against the cylinder
    directly, with none of the notch's own sampling or clearance in it.
    """
    thigh = cover.layout.thigh
    knee = thigh.knee
    faults = []
    for name in ("front", "back"):
        v = _shell_vertices(cover, name)
        v = v[v[:, 2] <= cfg.top_z - 1e-6]
        dy = v[:, 1] - knee.axis_y
        dz = v[:, 2] - knee.axis_z
        dx = v[:, 0] - thigh.centre_x
        worst = -np.inf
        for a in np.radians(np.arange(0.0, knee.flexion + 1e-9, step_deg)):
            qy = dy * math.cos(a) + dz * math.sin(a) + knee.axis_y
            qz = -dy * math.sin(a) + dz * math.cos(a) + knee.axis_z
            inside = (qz > thigh.bottom + 0.05) & (np.hypot(dx, qy - thigh.centre_y) < thigh.radius)
            if inside.any():
                depth = np.minimum(qz - thigh.bottom, thigh.radius - np.hypot(dx, qy - thigh.centre_y))
                worst = max(worst, float(depth[inside].max()))
        if worst > 0:
            faults.append(f"{name}: thigh passes {worst:.2f} mm into it during flexion")
    return faults


# --- 4. walls, behind the sockets too ----------------------------------------------


def walls(cover: TFCover, count: int = 160) -> list[str]:
    faults = []
    surface = cover.layout.surface
    floor = PROFILE.MIN_STRUT * RAY_TOLERANCE
    rng = np.random.default_rng(11)
    spec = cover.spec
    from scipy.spatial import cKDTree

    edges = _ring_points(surface, cover.rings["front"] + cover.rings["back"])
    near_edge = cKDTree(edges) if len(edges) else None
    for name in ("front", "back"):
        body = mb.to_manifold(cover.bodies[name])
        u = rng.random(count)
        v = rng.uniform(0.05, 0.95, count)
        p, n = surface.frame(u, v)
        if near_edge is not None:
            # A ray an instant from the rim of a hole only grazes it.
            clear = near_edge.query(p)[0] > 1.0
            p, n, u, v = p[clear], n[clear], u[clear], v[clear]
        # Nor near the edge of a shelf, a pad or the seam's gap: a probe laid
        # along the surface normal crosses the corner of a part obliquely, and
        # a chord through a corner can be as short as it likes. Those corners
        # are walls between two faces, not walls along the probe.
        seam = np.abs(cover.layout.interpolator(cover.layout.seam)(u, v))
        spec = cover.spec
        edges = np.array([cover.layout.clearance / 2.0, spec.inner_edge, spec.inner_edge + spec.width])
        away = np.min(np.abs(seam[:, None] - edges[None, :]), axis=1) > 3.0
        pads = [m.point for ms in cover.magnets.values() for m in ms]
        if pads:
            gap = np.min(np.linalg.norm(p[:, None, :] - np.array(pads)[None, :, :], axis=-1), axis=1)
            away &= np.abs(gap - spec.width / 2.0) > 3.0
        z = p[:, 2]
        for lo, hi in mt.shelf_gaps(cover.plans.values(), PROFILE.CLEARANCE):
            away &= (np.abs(z - lo) > 3.0) & (np.abs(z - hi) > 3.0)
        p, n = p[away], n[away]
        thin = []
        for start, direction in zip(p + n * 6.0, -n):
            hits = body.ray_cast(start.tolist(), (start + direction * 40.0).tolist())
            d = _crossings(hits, 40.0)
            for enter, leave in zip(d[0::2], d[1::2]):
                # The shell: every part of it starts no deeper than a shelf.
                # Past that a probe is in the hardware's rings and ribs, whose
                # thickness is a construction and whose corners it only grazes.
                if enter - 6.0 > spec.shelf_top + 1.0:
                    continue
                if leave - enter < floor:
                    thin.append(leave - enter)
        if thin:
            faults.append(f"{name}: wall down to {min(thin):.2f} mm on a probe")
    spec = cover.spec
    back = mb.to_manifold(cover.bodies["back"])
    front = mb.to_manifold(cover.bodies["front"])
    for magnets in cover.magnets.values():
        for m in magnets:
            # From outside, through the back half to its socket floor.
            start = m.point + m.normal * 5.0
            hits = _crossings(back.ray_cast(start.tolist(), (start - m.normal * 20.0).tolist()), 20.0)
            if len(hits) >= 2:
                skin = hits[1] - hits[0]
                if skin < floor:
                    faults.append(f"back half only {skin:.2f} mm over a magnet")
            else:
                faults.append("no socket found behind a magnet in the back half")
            # From inside, through the shelf to its socket floor.
            start = m.point - m.normal * (spec.shelf_bottom + 5.0)
            hits = _crossings(front.ray_cast(start.tolist(), (start + m.normal * 20.0).tolist()), 20.0)
            if len(hits) >= 2:
                skin = hits[1] - hits[0]
                if skin < floor:
                    faults.append(f"shelf only {skin:.2f} mm under a magnet")
            else:
                faults.append("no socket found in the shelf under a magnet")
    return faults


# --- 5. sockets face each other ----------------------------------------------------


def sockets_coaxial(cover: TFCover) -> list[str]:
    """Each pair of sockets is one hole: a thin rod down the shared axis, from
    the back half's socket floor to the shelf's, meets no material, and one
    moved off the axis by the socket's radius does."""
    faults = []
    spec = cover.spec
    halves = Manifold.batch_boolean(
        [mb.to_manifold(cover.bodies["front"]), mb.to_manifold(cover.bodies["back"])], OpType.Add
    )
    for magnets in cover.magnets.values():
        for m in magnets:
            lo = spec.pad - spec.socket_depth + 0.15
            hi = spec.shelf_top + spec.socket_depth - 0.15
            rod = mt.along_normal(m.point, m.normal, 0.05, lo, hi)
            if (rod ^ halves).volume() > 1e-3:
                faults.append("socket pair not on one axis (a rod down it hits material)")
                continue
            side = np.cross(m.normal, [0.0, 0.0, 1.0])
            side /= np.linalg.norm(side)
            off = m.point + side * (spec.socket_radius + 0.4)
            probe = mt.along_normal(off, m.normal, 0.05, lo, hi)
            if (probe ^ halves).volume() <= 1e-4:
                faults.append("socket wider than drawn: no wall beside the axis")
    return faults


# --- 6. parts do not run into each other -------------------------------------------


def parts_apart(cover: TFCover) -> list[str]:
    faults = []
    b = {k: mb.to_manifold(v) for k, v in cover.bodies.items()}
    hardware = mt.hardware(cover.pylon, cover.layout.surface)
    pairs = [("front", "back"), ("lower_clamp_back", "upper_clamp_back")]
    for clamp in ("lower_clamp_back", "upper_clamp_back"):
        pairs += [(clamp, "front"), (clamp, "back")]
    for x, y in pairs:
        if x in b and y in b:
            overlap = (b[x] ^ b[y]).volume()
            if overlap > TOUCH:
                faults.append(f"{x} and {y} intersect by {overlap:.1f} mm^3")
    for name, man in b.items():
        overlap = (man ^ hardware).volume()
        if overlap > TOUCH:
            faults.append(f"{name} runs into the tube or the module by {overlap:.1f} mm^3")
    # The back half goes on over clamps already tightened.
    for name, plan in cover.plans.items():
        heads = mt.head_volumes(plan)
        key = f"{name}_clamp_back"
        if key not in b:
            continue
        gap = b[key].min_gap(b["back"], 5.0)
        if gap < PROFILE.CLEARANCE - 1e-3:
            faults.append(f"{key} {gap:.2f} mm from the back half")
        if heads is not None and heads.min_gap(b["back"], 5.0) < PROFILE.CLEARANCE - 1e-3:
            faults.append(f"{name} bolt heads within the fit gap of the back half")
    return faults


# --- 7. struts at the edges -----------------------------------------------------------


def edge_struts(cover: TFCover) -> list[str]:
    """Holes keep a strut from each other and from every edge of their half."""
    faults = []
    surface = cover.layout.surface
    rings = cover.rings["front"] + cover.rings["back"]
    if len(rings) >= 2:
        gap = _min_strut(surface, rings)
        if gap < PROFILE.MIN_STRUT * 0.95:
            faults.append(f"strut between holes {gap:.2f} mm")
    for owner in ("front", "back"):
        owned = cover.rings[owner]
        if not owned:
            continue
        # Every hole of this half against the outline of the half itself.
        pts = _ring_points(surface, owned)
        outline = _outline_points(cover, owner)
        if len(outline):
            from scipy.spatial import cKDTree

            d, _ = cKDTree(outline).query(pts)
            if d.min() < PROFILE.MIN_STRUT * 0.95:
                faults.append(f"{owner}: hole {d.min():.2f} mm from an edge")
    return faults


def _outline_points(cover: TFCover, owner: str) -> np.ndarray:
    layout = cover.layout
    field = layout.front_field() if owner == "front" else layout.back_field()
    region = layout.region(field, 0.25 if owner == "front" else 0.75)
    out = []
    for poly in region.geoms:
        ring = np.asarray(poly.exterior.coords)
        out.append(measure._densify(layout.surface, ring))
    return np.vstack(out) if out else np.zeros((0, 3))


def _ring_points(surface, rings: list[np.ndarray], step_mm: float = 0.4) -> np.ndarray:
    """Every hole outline resampled to about `step_mm`, on the surface, at once."""
    return _rings_sampled(surface, rings, step_mm)[0]


def _rings_sampled(surface, rings, step_mm: float = 0.4):
    if not rings:
        return np.zeros((0, 3)), np.zeros(0, dtype=int)
    uv, owner = [], []
    for k, ring in enumerate(rings):
        a, b = ring, np.roll(ring, -1, axis=0)
        # Hole outline edges come out a millimetre or two long; eight
        # samples an edge keeps them under the step on all of them.
        t = np.linspace(0.0, 1.0, 8, endpoint=False)[None, :, None]
        q = (a[:, None, :] * (1 - t) + b[:, None, :] * t).reshape(-1, 2)
        uv.append(q)
        owner.append(np.full(len(q), k))
    uv = np.vstack(uv)
    return surface.point(uv[:, 0], uv[:, 1]), np.concatenate(owner)


def _min_strut(surface, rings) -> float:
    """Narrowest bridge between two different holes, in mm, measured in 3D."""
    from scipy.spatial import cKDTree

    pts, owner = _rings_sampled(surface, rings)
    tree = cKDTree(pts)
    k = min(24, len(pts))
    d, idx = tree.query(pts, k=k)
    best = np.inf
    for col in range(1, k):
        other = owner[idx[:, col]] != owner
        if other.any():
            best = min(best, float(d[:, col][other].min()))
    return best
