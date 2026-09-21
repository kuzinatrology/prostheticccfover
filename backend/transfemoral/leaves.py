"""A few large leaves cut into the back half, mirrored about its middle.

Small motifs scattered by the cell field disappear at arm's length; these are
meant to be seen. A leaf this size cannot be one hole, though: the wall can
carry a hole only so wide (`a_max`). So a leaf is cut the way it grows. The
outline is the hole, the midrib and the side veins stay as struts, and every
panel between two veins is small enough to carry. The veins are what make it
read as a leaf rather than a blot.

Leaves are laid out in rows down the back midline, one leaf on the midline or
a mirrored pair either side of it, and each is fitted into the room the back
half has: shrunk where it does not fit, and dropped with its twin where even a
small one does not.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.affinity import rotate, scale, translate
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import polylabel, unary_union

from ..printer_profile import PrinterProfile

BACK_MIDLINE_U = 0.75
"""u of the back of the leg: theta = 3 pi / 2, the -y direction."""

ROWS = {1: [1], 2: [2], 3: [1, 2], 4: [2, 2], 5: [1, 2, 2], 6: [2, 2, 2], 7: [1, 2, 2, 2]}
"""How many leaves sit in each row, top row first."""

WIDTH_RATIO = 0.62
"""Leaf width over leaf length."""

SHRINK_STEPS = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.45)


@dataclass(frozen=True)
class LeafSpec:
    count: int
    length: float
    tilt: float
    strut: float
    a_max: float
    profile: PrinterProfile

    @property
    def vein(self) -> float:
        """Veins a little heavier than the pattern's struts, so they draw."""
        return max(self.strut * 1.3, 2.0)


def outline(length: float) -> Polygon:
    """A serrated, pointed leaf in millimetres, stalk end at the origin, tip up."""
    y = np.linspace(-1.0, 1.0, 161)
    # Round at the stalk, drawn to a point at the tip.
    half = (1.0 + y) ** 0.45 * (1.0 - y) ** 0.9
    half /= half.max()
    # Teeth on the upper two thirds of the margin, as on the drawing.
    teeth = 1.0 + 0.07 * np.where(y > -0.45, ((y * 7.0) % 1.0), 0.0)
    w = half * teeth * WIDTH_RATIO * length / 2.0
    ys = (y + 1.0) * length / 2.0
    right = np.stack([w, ys], axis=1)
    left = np.stack([-w[::-1], ys[::-1]], axis=1)
    return Polygon(np.vstack([right, left])).buffer(0)


def veins(length: float, count: int) -> list[LineString]:
    """Midrib and `count` pairs of side veins leaning toward the tip."""
    lines = [LineString([(0.0, -length * 0.1), (0.0, length * 0.92)])]
    for k in range(1, count + 1):
        y0 = length * (0.08 + 0.78 * k / (count + 1))
        reach = WIDTH_RATIO * length * 0.6
        for side in (-1.0, 1.0):
            lines.append(LineString([(0.0, y0), (side * reach, y0 + reach * 1.1)]))
    return lines


def leaf_holes(spec: LeafSpec, length: float) -> list[Polygon]:
    """The panels of one leaf: outline less its veins, every panel carriable.

    More side veins go in until the widest panel fits the wall; panels too
    small to be a hole are left solid, as a cell of that size would be.
    """
    shape = outline(length)
    for pairs in range(3, 14):
        struts = unary_union([v.buffer(spec.vein / 2.0, cap_style=2) for v in veins(length, pairs)])
        panels = shape.difference(struts)
        parts = [g for g in getattr(panels, "geoms", [panels]) if isinstance(g, Polygon) and g.area > 0]
        widest = 0.0
        kept = []
        for part in parts:
            try:
                centre = polylabel(part, tolerance=0.05)
            except Exception:
                continue
            span = 2.0 * part.exterior.distance(centre)
            if span < spec.profile.MIN_HOLE:
                continue
            widest = max(widest, span)
            kept.append(part)
        if widest <= spec.a_max:
            return kept
    return []


def place(spec: LeafSpec, layout, keep_at, back_at) -> tuple[list[np.ndarray], list[str]]:
    """Leaf panels as rings in (u, v), and what the fitting cost."""
    notes: list[str] = []
    surface = layout.surface
    # The run of the back midline the leaves may use.
    v = np.linspace(0.0, 1.0, 400)
    room = keep_at(np.full_like(v, BACK_MIDLINE_U), v)
    inside = back_at(np.full_like(v, BACK_MIDLINE_U), v) > 0.0
    usable = v[(room > spec.strut + 2.0) & inside]
    if len(usable) < 2:
        return [], ["No room on the back half for leaves"]
    z_lo, z_hi = float(surface.z_of_v(usable.min())), float(surface.z_of_v(usable.max()))
    rows = ROWS.get(spec.count, ROWS[3])
    pitch = (z_hi - z_lo) / len(rows)
    length = min(spec.length, pitch * 0.92)
    if length < spec.length - 0.5:
        notes.append(f"Leaves held at {length:.0f} mm to fit {len(rows)} rows")

    rings: list[np.ndarray] = []
    placed = 0
    for r, n in enumerate(rows):
        z_centre = z_hi - pitch * (r + 0.5)
        fitted = None
        for step in SHRINK_STEPS:
            size = length * step
            holes = leaf_holes(spec, size)
            if not holes:
                continue
            leaf = MultiPolygon(holes)
            candidate = []
            for side in ([0.0] if n == 1 else [-1.0, 1.0]):
                shape = translate(leaf, 0.0, -size / 2.0)
                if side:
                    shape = scale(shape, xfact=side, yfact=1.0, origin=(0, 0))
                    shape = rotate(shape, -side * spec.tilt, origin=(0, 0))
                candidate.append((side, size, shape))
            rings_here = _to_uv(candidate, layout, z_centre)
            if rings_here is not None and _fits(rings_here, keep_at, back_at, spec):
                fitted = rings_here
                if step < 1.0:
                    notes.append(f"Row {r + 1} of leaves shrunk to {size:.0f} mm")
                break
        if fitted is None:
            notes.append(f"Row {r + 1} of leaves left out: no room")
            continue
        rings.extend(fitted)
        placed += n
    if placed < spec.count:
        notes.append(f"{placed} leaves of {spec.count}")
    return rings, notes


def _to_uv(candidate, layout, z_centre: float) -> list[np.ndarray] | None:
    """Lay millimetre shapes on the surface around the back midline."""
    surface = layout.surface
    v0 = float(surface.v_of_z(z_centre))
    su, sv = layout.uv_mm(BACK_MIDLINE_U, v0)
    out = []
    for side, size, shape in candidate:
        # A pair sits a leaf's width apart, with a strut of room between.
        du = side * (WIDTH_RATIO * size * 0.5 + 2.0) / su
        for poly in shape.geoms:
            xy = np.asarray(poly.exterior.coords)[:-1]
            # The leaf is drawn looking at the back of the leg, where screen
            # right is +x; u runs the other way there.
            u = BACK_MIDLINE_U + du - xy[:, 0] / su
            v = v0 + xy[:, 1] / sv
            if v.min() < 0.0 or v.max() > 1.0:
                return None
            out.append(np.stack([u, v], axis=1))
    return out


def _fits(rings, keep_at, back_at, spec: LeafSpec) -> bool:
    for ring in rings:
        nxt = np.roll(ring, -1, axis=0)
        t = np.linspace(0.0, 1.0, 4, endpoint=False)[None, :, None]
        dense = (ring[:, None, :] * (1 - t) + nxt[:, None, :] * t).reshape(-1, 2)
        if np.min(keep_at(dense[:, 0], dense[:, 1])) < spec.strut + 1.0:
            return False
        if np.min(back_at(dense[:, 0], dense[:, 1])) <= spec.strut:
            return False
    return True
