"""The seam: where the cover parts, and what holds it shut there.

The cut is one plane, the frontal one, so the cover comes apart into a front
and a back the way a cosmetic cover normally does.  Three things are built on
it:

*   a **land** -- a rib along the inside of each seam.  The wall is 3 mm on one
    cover and 5 on the other and a magnet is 6 across, so the seam face as cut
    has nowhere to put one; the land widens that face.
*   a **tongue and groove** down the middle of the land.  Magnets are strong in
    tension and weak in shear, and nothing else stops the two halves sliding
    across each other.  The step takes the shear so the magnets only ever pull.
*   **magnet pockets**, facing each other across the cut, blind on both sides.
    Their axis is the direction the halves actually separate, which is the
    direction a magnet is strongest in.

The old attachment put its magnets on the surface normal instead, which needed
a shelf reaching under the other half, a thickening over the shelf, and a
fitting gap between the two; this needs none of that, and the seam is symmetric.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from manifold3d import Manifold

from . import config as cfg
from . import solids as S


@dataclass
class SeamPlan:
    z_curve: np.ndarray
    y_curve: np.ndarray
    """The cut, as a curve of y against height in the cover's own frame."""

    depth_v: np.ndarray
    """Land depth per row of a grid over v, mm.

    One number would be the smallest room anywhere along the seam, and on the
    anatomic cover that is 5.7 mm at a single height near the knee -- which
    would leave the whole seam too shallow to hold a magnet.  It varies
    instead, and is smoothed over height so the rib has no steps in it."""

    z_of_v: np.ndarray
    """Height of each row, so a magnet can ask how deep the land is there."""

    z_lo: float
    z_hi: float
    magnets: list[float] = field(default_factory=list)
    """Heights of the magnet pairs, shared by both sides of the cover."""

    notes: list[str] = field(default_factory=list)

    def depth_at(self, z) -> np.ndarray:
        return np.interp(np.asarray(z, dtype=float), self.z_of_v, self.depth_v)

    def y_at(self, z) -> np.ndarray:
        return np.interp(np.asarray(z, dtype=float), self.z_curve, self.y_curve)

    def lean_at(self, z) -> np.ndarray:
        """The seam's slope, dy/dz, so a pocket sunk in its face can be sunk
        square to that face rather than square to the world."""
        dz = np.gradient(self.z_curve)
        dy = np.gradient(self.y_curve)
        return np.interp(np.asarray(z, dtype=float), self.z_curve, dy / np.maximum(dz, 1e-9))

    @property
    def y(self) -> float:
        """One number for the seam, for anything that only wants a report."""
        return float(np.mean(self.y_curve))

    @property
    def max_depth(self) -> float:
        return float(self.depth_v.max())


def seam_curve(surface, amplitude: float | None = None, rows: int = 80):
    """The cut, as (heights, y).

    An S about the cover's own centre line: most posterior at the bottom rim,
    forward through the calf, back to the centre at the top.  The amplitude is
    held to whatever keeps the cut from overhanging -- past that the halves no
    longer come apart by pulling them apart.
    """
    from scipy.interpolate import PchipInterpolator

    lo, hi = _height_range(surface)
    z = np.linspace(lo, hi, rows)
    # One number for the base, not the centre line itself.  The centre line
    # wanders nearly 30 mm over this cover's height and it wanders unevenly;
    # a seam that followed it would be a wobble with an S somewhere inside it,
    # and its slope -- which is what decides whether the halves come apart at
    # all -- would be the scan's, not the design's.
    base = float(np.mean(S.centre_of(surface, z)[:, 1]))
    t = (z - lo) / max(hi - lo, 1e-9)
    a = cfg.SEAM_CURVE if amplitude is None else float(amplitude)
    knots = np.array(cfg.SEAM_SHAPE, dtype=float)
    shape = PchipInterpolator(knots[:, 0], knots[:, 1])(t)
    y = base + a * shape
    slope = np.max(np.abs(np.gradient(y) / np.maximum(np.gradient(z), 1e-9)))
    if slope > cfg.MAX_SEAM_SLOPE:
        y = base + a * shape * (cfg.MAX_SEAM_SLOPE / slope)
    return z, y


def seam_y(surface, rows: int = 60) -> float:
    """The frontal plane through the cover's own centre line.

    The centre line wanders fore and aft over the cover's height -- on the
    anatomic cover by nearly 30 mm, because the prosthesis it is built round
    does -- so there is no one plane through all of it.  This is the mean, and
    the mean is what leaves the two halves most nearly equal.
    """
    lo, hi = _height_range(surface)
    z = np.linspace(lo, hi, rows)
    return float(np.mean(S.centre_of(surface, z)[:, 1]))


def _height_range(surface) -> tuple[float, float]:
    grid = S.loft(surface, 0.0, rows=40)
    return float(grid[..., 2].min()), float(grid[..., 2].max())


def seam_crossings(surface, y, z: np.ndarray) -> np.ndarray:
    """Radius from the centre line to the seam, per height and side.

    Returns (n, 2): the distance out to the lateral crossing and to the medial
    one.  A height where the plane misses the section altogether -- which can
    only happen if the cover is narrower than its own centre line's wander --
    comes back NaN.
    """
    z = np.atleast_1d(np.asarray(z, dtype=float))
    y = np.broadcast_to(np.asarray(y, dtype=float), z.shape)
    c = S.centre_of(surface, z)
    out = np.full((len(z), 2), np.nan)
    for k, sign in enumerate((+1.0, -1.0)):
        theta = np.zeros(len(z))
        for _ in range(40):
            r = surface.radial(theta, z)
            f = c[:, 1] + r * np.sin(theta) - y
            # Walk the angle toward the plane; the section is star shaped, so
            # one crossing sits near 0 and the other near pi.
            theta = theta - 0.4 * f / np.maximum(r, 1.0)
            theta = np.clip(theta, -np.pi / 2.0, np.pi / 2.0) if sign > 0 else theta
        if sign < 0:
            theta = np.full(len(z), np.pi)
            for _ in range(40):
                r = surface.radial(theta, z)
                f = c[:, 1] + r * np.sin(theta) - y
                theta = theta + 0.4 * f / np.maximum(r, 1.0)
                theta = np.clip(theta, np.pi / 2.0, 3.0 * np.pi / 2.0)
        r = surface.radial(theta, z)
        ok = np.abs(c[:, 1] + r * np.sin(theta) - y) < 0.5
        out[ok, k] = r[ok]
    return out


def room_along_seam(surface, hardware, y: float, wall: float, rows: int = 80,
                    z: np.ndarray | None = None) -> np.ndarray:
    """Free depth inward from the wall at the seam, per height and side."""
    lo, hi = _height_range(surface)
    z = np.linspace(lo + 2.0, hi - 2.0, rows) if z is None else np.asarray(z, dtype=float)
    c = S.centre_of(surface, z)
    r = seam_crossings(surface, y, z)
    out = np.full_like(r, np.inf)
    for k, sign in enumerate((+1.0, -1.0)):
        good = np.isfinite(r[:, k])
        if not good.any():
            continue
        x = c[good, 0] + sign * np.sqrt(np.maximum(r[good, k] ** 2 - (y - c[good, 1]) ** 2, 0.0))
        pts = np.stack([x - sign * wall, np.full(good.sum(), y), z[good]], axis=1)
        out[good, k] = hardware.clearance(pts)
    return out


def plan(surface, hardware, wall: float, count: int, clearance: float,
         magnet_d: float, magnet_h: float, rows: int = 240,
         avoid: list[tuple[float, float]] = (), curve=None) -> SeamPlan:
    """Settle the seam: its curve, how deep the land goes, where magnets sit."""
    z_curve, y_curve = curve if curve is not None else seam_curve(surface)
    lo, hi = _height_range(surface)
    notes: list[str] = []

    probe_z = np.linspace(lo, hi, 120)
    y = np.interp(probe_z, z_curve, y_curve)
    room = room_along_seam(surface, hardware, y, wall, rows=120, z=probe_z)
    free = np.nanmin(room, axis=1)
    # A height the scan never covered reads inf.  Carrying that through would
    # let the land go full depth exactly where nothing is known about what it
    # would go into, so an uncovered height takes the room of the nearest
    # covered one instead.
    known = np.isfinite(free)
    if known.any():
        free = np.interp(probe_z, probe_z[known], free[known])
    else:
        free = np.full_like(probe_z, cfg.LAND_DEPTH)

    # What has to fit across the land: a magnet with a strut either side, or
    # the tongue with the same.  The wall is part of that width already, so
    # only the rest is the land's to find, and it never exceeds the ceiling.
    across = max(magnet_d + clearance, cfg.STEP_WIDTH) + 2.0 * cfg.MAGNET_STRUT
    want = float(np.clip(across - wall, 0.0, cfg.LAND_DEPTH))
    depth = np.clip(free - clearance - 1.0, 0.0, want)
    # Smooth over height: the room is read off a scan and steps in it are the
    # scan's noise, not the prosthesis.
    win = max(int(round(12.0 / (probe_z[1] - probe_z[0]))), 1)
    kernel = np.ones(win) / win
    depth = np.convolve(np.pad(depth, win, mode="edge"), kernel, mode="same")[win:-win]
    depth = np.minimum(depth, want)

    v = np.linspace(0.0, 1.0, rows)
    z_of_v = np.linspace(lo, hi, rows)
    depth_v = np.interp(z_of_v, probe_z, depth)
    if depth_v.max() < want - 1e-6:
        notes.append(
            f"Land held to {depth_v.max():.1f} mm of {want:.1f}: "
            f"the prosthesis leaves {float(free.min()):.1f} mm at the tightest seam"
        )

    need = magnet_d + clearance + 2.0 * cfg.MAGNET_STRUT
    margin = cfg.MAGNET_END_MARGIN
    z_lo, z_hi = lo + margin, hi - margin
    heights: list[float] = []
    if count > 0 and z_hi > z_lo:
        wanted = [0.5 * (z_lo + z_hi)] if count == 1 else list(np.linspace(z_lo, z_hi, count))
        reach = magnet_d / 2.0 + cfg.MAGNET_STRUT
        deep = z_of_v[(depth_v + wall) >= need]
        for z in wanted:
            for a_, b_ in avoid:
                if a_ - reach < z < b_ + reach:
                    below, above = a_ - reach, b_ + reach
                    z = below if abs(z - below) <= abs(above - z) else above
            if len(deep):
                # Slide to the nearest height whose land is deep enough to hold
                # the magnet at all, rather than sinking a pocket through the
                # wall.
                z = float(deep[np.argmin(np.abs(deep - z))])
            if not (z_lo - 1.0 <= z <= z_hi + 1.0):
                continue
            if any(a_ - reach < z < b_ + reach for a_, b_ in avoid):
                continue
            if all(abs(z - w) >= cfg.MAGNET_MIN_PITCH for w in heights):
                heights.append(z)
        if len(heights) < count:
            notes.append(f"{len(heights)} magnet pairs placed of {count}")
    missed = ~np.isfinite(seam_crossings(surface, y, probe_z)).all(axis=1)
    if missed.any():
        notes.append(
            f"The seam leaves the cover at {int(missed.sum())} of {len(probe_z)} heights; "
            "the curve is too deep for this silhouette"
        )
    return SeamPlan(z_curve=z_curve, y_curve=y_curve, depth_v=depth_v, z_of_v=z_of_v,
                    z_lo=lo, z_hi=hi, magnets=sorted(heights), notes=notes)


# --- the solids -------------------------------------------------------------


def land(surface, wall: float, plan: SeamPlan) -> Manifold | None:
    """The rib along the inside of both seams."""
    if plan.max_depth <= 0.1:
        return None
    stock = S.band(surface, wall - cfg.OVERLAP, wall + plan.depth_v,
                   rows=len(plan.depth_v))
    return stock ^ S.curved_slab(plan.z_curve, plan.y_curve, cfg.LAND_HALF_WIDTH)


def _step_band(surface, wall: float, plan: SeamPlan, grow: float) -> tuple[float, float]:
    """Radial depths the tongue occupies, grown by `grow` on each side."""
    # Across the whole face the halves meet on -- the wall and the land
    # together -- not across the land alone.  The land used to be deep enough
    # that everything sat inside it; it is now cut to just what it has to add,
    # so its own middle is no longer the middle of anything.
    mid = (wall + plan.depth_v) / 2.0
    half = cfg.STEP_WIDTH / 2.0 + grow
    return mid - half, mid + half


def tongue(surface, wall: float, plan: SeamPlan, grow: float, gap: float,
           magnet_d: float) -> Manifold | None:
    """The rib that crosses the cut, or the pocket cut for it in the other half.

    `grow` = 0 builds the tongue itself, `grow` = the fitting gap builds the
    groove it drops into.  Both are interrupted at every magnet: the magnet
    pockets share the tongue's depth in the land -- there is no room in a 12 mm
    land for both at once -- so the step stops a magnet's width short of each
    one and picks up again above it.
    """
    if plan.max_depth <= cfg.STEP_WIDTH + 1.0:
        return None
    inner, outer = _step_band(surface, wall, plan, grow)
    # Where the land is too shallow for a step, the two depths meet and the
    # band closes on itself, which is the rib simply stopping.
    thin = plan.depth_v <= cfg.STEP_WIDTH + 2.0 * grow + 0.5
    outer = np.where(thin, inner + 0.01, outer)
    lo, hi = cfg.STEP_END_V, 1.0 - cfg.STEP_END_V
    keep = slice(int(lo * len(plan.depth_v)), int(hi * len(plan.depth_v)) or None)
    stock = S.band(surface, inner[keep], outer[keep], rows=len(inner[keep]),
                   v_range=(lo, hi))
    depth = cfg.STEP_DEPTH + grow
    # From the back half's side of the cut up into the front half, so the two
    # parts of the front half are one solid.
    rib = stock ^ S.curved_slab(
        plan.z_curve, plan.y_curve - depth / 2.0 + gap, depth / 2.0 + gap
    )
    cuts = [
        S.slab([0.0, 0.0, z], "z", magnet_d / 2.0 + cfg.LUG_STRUT + grow)
        for z in plan.magnets
    ]
    return S.sub(rib, cuts)


def magnet_pockets(surface, wall: float, plan: SeamPlan, magnet_d: float,
                   magnet_h: float, clearance: float, side: int) -> list[Manifold]:
    """Blind pockets in one half's mating face, one per magnet per seam.

    `side` is +1 for the front half, -1 for the back.  The pocket starts on
    that half's own face -- half the fitting gap off the cut -- so the two
    magnets meet in the middle with the gap between them and nothing to keep
    them apart but the gap.
    """
    if not plan.magnets:
        return []
    r = (magnet_d + clearance) / 2.0
    depth = magnet_h + clearance
    out = []
    z = np.array(plan.magnets, dtype=float)
    y_here = plan.y_at(z)
    face = y_here + side * clearance / 2.0
    lean = plan.lean_at(z)
    radius = seam_crossings(surface, y_here, z)
    c = S.centre_of(surface, z)
    for i, zi in enumerate(z):
        for k, sign in enumerate((+1.0, -1.0)):
            if not np.isfinite(radius[i, k]):
                continue
            rr = radius[i, k] - (wall + float(plan.depth_at(zi))) / 2.0
            x = c[i, 0] + sign * np.sqrt(max(rr**2 - (y_here[i] - c[i, 1]) ** 2, 0.0))
            # Square to the cut, not to the world: where the seam leans, a
            # pocket sunk along y would break out of the land's face on one
            # side and stop short of it on the other.
            tilt = math.degrees(math.atan(float(lean[i])))
            cyl = Manifold.cylinder(depth, r, r, 48).rotate([90.0 * side, 0.0, 0.0])
            cyl = cyl.rotate([tilt, 0.0, 0.0])
            out.append(cyl.translate([float(x), float(face[i]), float(zi)]))
    return out
