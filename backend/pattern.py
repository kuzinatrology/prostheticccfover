"""The cell field, and the holes cut from it.

Everything happens in a conformal ("Mercator") image of the cover:

    U = 2*pi*u                V = integral(L dv / r(v))

There the metric is r(v)^2 * (dU^2 + dV^2), so a round cell in the domain is a
round cell on the cover, and cells grow in step with the cover's girth.
Distances convert with a single local scale factor, which is what lets the
strut width be a construction step rather than a check.

Anisotropy adds one more layer. Seeds are laid out in a *lattice* space and
mapped into the domain by a linear warp, so cells come out stretched and
leaning. The warp keeps the seam periodic, and the cells are carried into the
domain before anything is measured, so every printability rule below is
untouched by it:

  * a strut is exactly `strut` wide because the cell is eroded by strut/2;
  * a cell too small to erode simply stays solid;
  * a hole below MIN_HOLE stays solid;
  * a hole above a_max causes its cell to be subdivided and rebuilt finer;
  * where the mask fades, the erosion deepens and the hole closes early.

A motif changes the shape of the hole and nothing else. The cell still says
where the hole is and how big; the picture only says what it looks like. So
every rule above still holds, applied to a different outline:

  * the motif is fitted inside the same eroded cell, so the strut is the same;
  * closing the motif by strut/2 leaves no gap inside it narrower than that;
  * opening it by MIN_HOLE/2 leaves nothing in it thinner than MIN_HOLE;
  * too wide for the wall shrinks the motif in that cell rather than splitting
    it, because half a leaf is not a leaf;
  * where the mask fades the motif shrinks and goes out, which reads better
    than a leaf with its edges eaten.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.spatial import Voronoi, cKDTree
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polylabel

from .fields import Field, Fields, as_array_field
from .printer_profile import PrinterProfile
from .surface import Surface, TWO_PI

MAX_SUBDIVISION_ROUNDS = 4
SPREAD_PASSES = 3
"""Passes that enforce the variable disk radius after jittering."""

SETTLE_PASSES = 2
MIN_SETTLE = 0.15
"""Below this the relaxation would not move a seed far enough to be worth a
pass, so a well jittered layout skips it."""

SPAN_VS_CURVATURE = 0.9
"""A hole may span at most this fraction of the surface's smallest radius of
curvature. Past that the cover is more hole than cover locally, and a hole
cannot be driven through the wall without reaching the far side."""

MAX_JITTER = 0.85
"""Jitter at irregularity = 1, as a fraction of the local seed spacing."""

MIN_SEPARATION = 0.55
"""Enforced seed separation, as a fraction of the spacing. Below the lattice
pitch, so a jittered layout stays genuinely scattered, but far enough above
(MIN_HOLE + strut) that cells never collapse."""

ROUND_FRACTION = 0.55
"""Corner rounding at corner_radius = 1, as a fraction of the hole's own
inscribed radius. Scaling it by the printer's minimum strut, as the brief
suggested, is invisible on a fifteen millimetre cell."""

MASK_CLOSE = 1.15
"""How hard a fully masked cell is eroded, as a multiple of its own inscribed
radius. Above one, so a cell the mask has turned off closes completely
whatever its size, and a cell the mask has half turned off loses half of
itself rather than a fixed number of millimetres."""

RIM_MM = 7.0
"""Solid band left at each opening so the cover has a rim to grip."""

MOTIF_ATTEMPTS = 3
"""Tries at shrinking a motif that came out wider than the wall can carry.

The motif scales linearly, so the first correction is nearly exact and the
rest are there to absorb what the closing and the clip give back."""

MOTIF_FLOOR = 0.2
"""A motif below this share of the cell it was asked to fill is not a motif
any more, and the cell is left solid."""


@dataclass
class PatternResult:
    holes: list[np.ndarray] = field(default_factory=list)
    """Rings in (u, v). u may run outside [0, 1); it wraps.

    A cell's own hole is convex and there is one per cell. A motif is whatever
    the picture was, and one cell can carry several of them."""

    cells: int = 0
    solid_cells: int = 0
    subdivided: int = 0
    rounds: int = 0
    strut: float = 0.0

    reduced: int = 0
    """Cells where the motif had to be shrunk to stay inside the wall's span."""

    least_fill: float = 1.0
    """The smallest share of its cell any motif ended up taking."""

    thinned: int = 0
    """Cells where opening the motif deleted something too thin to print."""

    merged: int = 0
    """Cells where closing the motif joined details too close to keep apart."""


# --- the anisotropic warp ----------------------------------------------


@dataclass(frozen=True)
class Warp:
    """Linear map from the lattice space seeds live in to the domain.

        U = sx * p + shear * q          V = sy * q

    Determinant is one, so cell areas and therefore cell counts survive the
    stretch. Adding a full turn to U is a pure shift in p at any height, which
    is why the seam still closes however far the pattern leans.
    """

    sx: float
    sy: float
    shear: float

    @classmethod
    def make(cls, ratio: float, angle_deg: float) -> "Warp":
        sx = math.sqrt(max(ratio, 1e-6))
        sy = 1.0 / sx
        return cls(sx=sx, sy=sy, shear=math.tan(math.radians(angle_deg)) * sy)

    @property
    def period(self) -> float:
        return TWO_PI / self.sx

    def to_domain(self, pq: np.ndarray) -> np.ndarray:
        p, q = pq[..., 0], pq[..., 1]
        return np.stack([p * self.sx + q * self.shear, q * self.sy], axis=-1)


# --- the domain ---------------------------------------------------------


class _Domain:
    """The Mercator rectangle and the scale factors that live on it.

    How many millimetres a step in the domain is worth changes around a
    section as well as up the cover, and on a superellipse it changes sharply:
    the curve races through the ends of its axes. Guessing that factor from
    the section's half-widths was right for an ellipse and wrong for anything
    squarer, so it is measured from the surface instead and kept as a table.
    """

    NU = 256
    NV = 192

    def __init__(self, surface: Surface, v_lo: float, v_hi: float):
        self.surface = surface
        v_grid, V_grid = surface.mercator()
        self.v_grid, self.V_grid = v_grid, V_grid
        self.V_lo = float(np.interp(v_lo, v_grid, V_grid))
        self.V_hi = float(np.interp(v_hi, v_grid, V_grid))

        self.V_axis = np.linspace(self.V_lo, self.V_hi, self.NV)
        v_axis = self.v_of_V(self.V_axis)
        u_axis = np.linspace(0.0, 1.0, self.NU, endpoint=False)
        uu, vv = np.meshgrid(u_axis, v_axis)

        du = dv = 1e-4
        d_u = (surface.point(uu + du, vv) - surface.point(uu - du, vv)) / (2 * du)
        vc = np.clip(vv, dv, 1.0 - dv)
        d_v = (surface.point(uu, vc + dv) - surface.point(uu, vc - dv)) / (2 * dv)

        # mm per unit U, and mm per unit V, at every sample.
        per_U = np.linalg.norm(d_u, axis=-1) / TWO_PI
        dV_dv = surface.length / surface.radius(np.clip(v_axis, 0.0, 1.0))
        per_V = np.linalg.norm(d_v, axis=-1) / dV_dv[:, None]

        self._lo_grid = np.minimum(per_U, per_V)
        self._hi_grid = np.maximum(per_U, per_V)
        self._mid_grid = np.sqrt(np.maximum(per_U * per_V, 1e-12))

    def v_of_V(self, V):
        return np.interp(V, self.V_grid, self.v_grid)

    def V_of_v(self, v):
        return np.interp(v, self.v_grid, self.V_grid)

    # --- reading the scale ------------------------------------------------
    def _rows(self, V) -> np.ndarray:
        t = (np.asarray(V, dtype=float) - self.V_lo) / max(self.V_hi - self.V_lo, 1e-12)
        return np.clip((t * (self.NV - 1)).astype(int), 0, self.NV - 1)

    def _cols(self, U) -> np.ndarray:
        return (np.asarray(U, dtype=float) / TWO_PI * self.NU).astype(int) % self.NU

    def mid(self, U, V) -> np.ndarray:
        """Typical mm per unit domain length, for sizing cells."""
        return self._mid_grid[self._rows(V), self._cols(U)]

    def box(self, U0: float, U1: float, V0: float, V1: float) -> tuple[float, float]:
        """Tightest and loosest scale anywhere in a patch of the domain.

        One is used wherever a measurement must not come out too small and the
        other wherever it must not come out too large, so both tests err
        toward leaving material.
        """
        j0, j1 = self._rows(min(V0, V1)), self._rows(max(V0, V1))
        rows = slice(max(int(j0) - 1, 0), min(int(j1) + 2, self.NV))
        width = U1 - U0
        if width >= TWO_PI:
            cols = np.arange(self.NU)
        else:
            i0 = int(np.floor(U0 / TWO_PI * self.NU)) - 1
            i1 = int(np.ceil(U1 / TWO_PI * self.NU)) + 1
            cols = np.arange(i0, i1 + 1) % self.NU
        return (
            float(self._lo_grid[rows][:, cols].min()),
            float(self._hi_grid[rows][:, cols].max()),
        )


class _SpacingTable:
    """Seed spacing in domain units, driven by the density field.

    The field is sampled once onto a grid and read back by bilinear
    interpolation, periodic in U. Density fields are smooth by nature, so this
    costs nothing in fidelity and keeps the inner loops out of Python.
    """

    NU = 128
    NV = 192

    def __init__(
        self,
        domain: _Domain,
        density: Field,
        profile: PrinterProfile,
        strut: float,
        wall: float,
        span_cap: float,
    ):
        a_max = min(profile.max_hole_span(wall), span_cap)
        fine = profile.MIN_HOLE + strut + profile.SPACING_SLACK
        coarse = max(a_max * profile.SPACING_HEADROOM + strut, fine * 1.05)

        self.domain = domain
        self.U = np.linspace(0.0, TWO_PI, self.NU, endpoint=False)
        self.V = np.linspace(domain.V_lo, domain.V_hi, self.NV)
        UU, VV = np.meshgrid(self.U, self.V)
        d = as_array_field(density)(UU / TWO_PI, domain.v_of_V(VV))
        self.table = (coarse + (fine - coarse) * d) / domain.mid(UU, VV)
        self.min = float(self.table.min())
        self.max = float(self.table.max())
        self.row_mean = self.table.mean(axis=1)

    def __call__(self, U, V):
        U = np.asarray(U, dtype=float) % TWO_PI
        V = np.asarray(V, dtype=float)
        fu = U / TWO_PI * self.NU
        i0 = np.floor(fu).astype(int) % self.NU
        i1 = (i0 + 1) % self.NU
        tu = fu - np.floor(fu)
        fv = np.clip(
            (V - self.V[0]) / (self.V[-1] - self.V[0]) * (self.NV - 1), 0, self.NV - 1
        )
        j0 = np.floor(fv).astype(int)
        j1 = np.minimum(j0 + 1, self.NV - 1)
        tv = fv - j0
        t = self.table
        top = t[j0, i0] * (1 - tu) + t[j0, i1] * tu
        bot = t[j1, i0] * (1 - tu) + t[j1, i1] * tu
        return top * (1 - tv) + bot * tv

    def mean_at(self, V: float) -> float:
        return float(np.interp(V, self.V, self.row_mean))


class _LatticeSpacing:
    """The same spacing, read in the lattice space seeds live in."""

    def __init__(self, table: _SpacingTable, warp: Warp):
        self.table = table
        self.warp = warp
        self.min = table.min
        self.max = table.max

    def __call__(self, p, q):
        p = np.asarray(p, dtype=float)
        q = np.asarray(q, dtype=float)
        return self.table(p * self.warp.sx + q * self.warp.shear, q * self.warp.sy)

    def mean_at(self, q: float) -> float:
        return self.table.mean_at(q * self.warp.sy)


# --- the cell field, shared by every operation --------------------------


@dataclass
class CellField:
    """Seeds and everything needed to read the pattern anywhere on the cover.

    Cutting holes, raising a relief and engraving grooves all start here; only
    the last step differs.
    """

    seeds: np.ndarray  # (N, 2) in lattice space
    warp: Warp
    domain: _Domain
    spacing: _LatticeSpacing
    band: float
    a_max: float
    strut: float


def build_cells(
    surface: Surface,
    density: Field,
    *,
    wall_thickness: float,
    strut: float,
    irregularity: float,
    anisotropy: float,
    flow_angle: float,
    profile: PrinterProfile,
    rng: np.random.Generator,
) -> CellField:
    v_margin = min(0.3, RIM_MM / surface.length)
    domain = _Domain(surface, v_margin, 1.0 - v_margin)
    span_cap = SPAN_VS_CURVATURE * surface.min_curvature_radius()
    table = _SpacingTable(domain, density, profile, strut, wall_thickness, span_cap)
    warp = Warp.make(anisotropy, flow_angle)
    spacing = _LatticeSpacing(table, warp)
    band = 2.5 * spacing.max

    q_lo, q_hi = domain.V_lo / warp.sy, domain.V_hi / warp.sy
    seeds = _seed(spacing, irregularity, warp.period, q_lo, q_hi, band, rng)
    return CellField(
        seeds=seeds,
        warp=warp,
        domain=domain,
        spacing=spacing,
        band=band,
        a_max=min(profile.max_hole_span(wall_thickness), span_cap),
        strut=strut,
    )


# --- seeding ------------------------------------------------------------
# One code path covers both ends of the irregularity slider: build a graded
# hexagonal lattice, displace each node by `irregularity` times a random
# offset, then enforce the variable disk radius. At 0 the lattice is
# untouched; at 1 the nodes are as scattered as the spacing allows.


def _hex_lattice(
    spacing: _LatticeSpacing, period: float, q_lo: float, q_hi: float
) -> np.ndarray:
    rows: list[tuple[float, float]] = []
    q = q_lo
    while True:
        h = math.sqrt(3.0) / 2.0 * spacing.mean_at(q)
        if h <= 0 or q + h > q_hi:
            break
        rows.append((q + h / 2.0, h))
        q += h
    if not rows:
        return np.zeros((0, 2))

    # Centre the leftover slack so the rims match top and bottom.
    slack = (q_hi - (rows[-1][0] + rows[-1][1] / 2.0)) / 2.0
    pts: list[tuple[float, float]] = []
    for j, (centre, h) in enumerate(rows):
        centre += slack
        step = h / (math.sqrt(3.0) / 2.0)
        n = max(3, int(round(period / step)))
        du = period / n
        offset = du / 2.0 if j % 2 else 0.0
        for k in range(n):
            pts.append((offset + k * du, centre))
    return np.array(pts, dtype=float)


def _spread(
    pts: np.ndarray,
    spacing: _LatticeSpacing,
    period: float,
    q_lo: float,
    q_hi: float,
    band: float,
) -> np.ndarray:
    """Push apart any pair closer than the local disk radius.

    This is the variable-radius Poisson disk condition applied directly to the
    layout, rather than by rejection sampling, so it holds no matter how hard
    the jitter pushed.
    """
    for _ in range(SPREAD_PASSES):
        tiled = _tiled(pts, period, q_lo, q_hi, band)
        tree = cKDTree(tiled)
        d, idx = tree.query(pts, k=min(7, len(tiled)))
        radius = MIN_SEPARATION * spacing(pts[:, 0], pts[:, 1])
        move = np.zeros_like(pts)
        for col in range(1, d.shape[1]):
            need = np.maximum(radius - d[:, col], 0.0)
            if not np.any(need > 0):
                continue
            delta = pts - tiled[idx[:, col]]
            norm = np.maximum(np.linalg.norm(delta, axis=1, keepdims=True), 1e-9)
            move += delta / norm * (0.5 * need)[:, None]
        if not np.any(move):
            break
        pts = pts + move
        pts[:, 0] %= period
        pts[:, 1] = np.clip(pts[:, 1], q_lo + 1e-6, q_hi - 1e-6)
    return pts


def _settle(
    pts: np.ndarray,
    spacing: _LatticeSpacing,
    damping: float,
    period: float,
    q_lo: float,
    q_hi: float,
    band: float,
) -> np.ndarray:
    """Move each seed part of the way to its cell's density-weighted centroid.

    For a regular hexagon that centroid is the seed itself, so an ordered
    lattice does not move. Where the lattice has to change its column count
    the cells are lopsided, and those rows quietly even out instead of reading
    as a belt around the cover.
    """
    if damping <= MIN_SETTLE:
        return pts
    for _ in range(SETTLE_PASSES):
        moved = pts.copy()
        for i, ring in enumerate(_rings(pts, period, q_lo, q_hi, band)):
            if ring is None:
                continue
            seed = pts[i]
            q0, q1 = ring, np.roll(ring, -1, axis=0)
            area = 0.5 * np.abs(
                (q0[:, 0] - seed[0]) * (q1[:, 1] - seed[1])
                - (q1[:, 0] - seed[0]) * (q0[:, 1] - seed[1])
            )
            cent = (seed + q0 + q1) / 3.0
            w = area / np.maximum(spacing(cent[:, 0], cent[:, 1]), 1e-9) ** 2
            total = w.sum()
            if total > 1e-12:
                moved[i] = seed + damping * ((cent * w[:, None]).sum(axis=0) / total - seed)
        pts = moved
        pts[:, 0] %= period
        pts[:, 1] = np.clip(pts[:, 1], q_lo + 1e-6, q_hi - 1e-6)
    return pts


def _seed(
    spacing: _LatticeSpacing,
    irregularity: float,
    period: float,
    q_lo: float,
    q_hi: float,
    band: float,
    rng: np.random.Generator,
) -> np.ndarray:
    pts = _hex_lattice(spacing, period, q_lo, q_hi)
    if len(pts) < 4:
        return pts
    if irregularity <= 0.0:
        return _settle(pts, spacing, 0.6, period, q_lo, q_hi, band)
    local = spacing(pts[:, 0], pts[:, 1])
    ang = rng.uniform(0.0, TWO_PI, len(pts))
    mag = irregularity * MAX_JITTER * local * np.sqrt(rng.random(len(pts)))
    pts = pts + np.stack([mag * np.cos(ang), mag * np.sin(ang)], axis=1)
    pts[:, 0] %= period
    pts[:, 1] = np.clip(pts[:, 1], q_lo + 1e-6, q_hi - 1e-6)
    pts = _settle(pts, spacing, 0.6 * (1.0 - irregularity), period, q_lo, q_hi, band)
    return _spread(pts, spacing, period, q_lo, q_hi, band)


# --- periodic Voronoi ---------------------------------------------------


def _tiled(
    points: np.ndarray, period: float, q_lo: float, q_hi: float, band: float
) -> np.ndarray:
    """Ghost seeds: wrapped around the seam, mirrored across both rims.

    Only seeds within `band` of an edge need a ghost, which keeps the Voronoi
    input close to the real seed count. The wrap makes the pattern meet itself
    at the seam; the mirrors stop every core cell at the rim, so nothing has to
    be clipped later.
    """
    blocks = [points]
    left = points[points[:, 0] < band]
    right = points[points[:, 0] > period - band]
    if len(left):
        blocks.append(left + np.array([period, 0.0]))
    if len(right):
        blocks.append(right - np.array([period, 0.0]))
    base = np.vstack(blocks)
    out = [base]
    for pivot, mask in (
        (q_lo, base[:, 1] < q_lo + band),
        (q_hi, base[:, 1] > q_hi - band),
    ):
        m = base[mask]
        if len(m):
            m = m.copy()
            m[:, 1] = 2.0 * pivot - m[:, 1]
            out.append(m)
    return np.vstack(out)


def _rings(
    points: np.ndarray, period: float, q_lo: float, q_hi: float, band: float
) -> list[np.ndarray | None]:
    """Voronoi cells for the core seeds, as raw vertex arrays in lattice space."""
    n = len(points)
    if n < 4:
        return [None] * n
    vor = Voronoi(_tiled(points, period, q_lo, q_hi, band))
    out: list[np.ndarray | None] = []
    for i in range(n):
        region = vor.regions[vor.point_region[i]]
        out.append(
            vor.vertices[region] if region and -1 not in region and len(region) >= 3 else None
        )
    return out


# --- the motif, if there is one -----------------------------------------


@dataclass(frozen=True)
class Placement:
    """A motif and how it sits in a cell.

    `shape` lives in the unit square with its bounding box centred on the
    origin and its longer side exactly one. The domain is conformal, so
    scaling it by one number is a true scaling on the cover: a leaf is a leaf
    at the ankle and at the calf, and neither the girth nor the anisotropic
    warp can shear it.
    """

    shape: MultiPolygon
    fill: float
    rotation: float
    """Degrees, applied to every motif."""
    rotation_jitter: float
    """Degrees, either side, drawn per cell."""
    align_flow: bool
    scale_jitter: float
    flow_angle: float
    seed: int


def _lay(shape: MultiPolygon, size: float, angle: float, cx: float, cy: float) -> MultiPolygon:
    """The unit motif, scaled, turned and set down at a point in the domain."""
    cos, sin = math.cos(angle), math.sin(angle)
    parts = []
    for poly in shape.geoms:
        a = np.asarray(poly.exterior.coords, dtype=float) * size
        parts.append(
            Polygon(
                np.stack(
                    [cx + a[:, 0] * cos - a[:, 1] * sin, cy + a[:, 0] * sin + a[:, 1] * cos],
                    axis=1,
                )
            )
        )
    return MultiPolygon(parts)


def _outlines(geom: BaseGeometry) -> list[Polygon]:
    """Every part of a geometry, with its interior openings filled.

    An opening inside a hole is a disc of shell with nothing holding it, so it
    would drop out of the print. Filling it is the same move as leaving a cell
    solid: the design gives up the detail the machine cannot keep.
    """
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [Polygon(geom.exterior.coords)] if geom.area > 0 else []
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _outlines(g)]
    return []


def _shrank(before: float, after: float) -> bool:
    """Whether a morphological step moved enough of the area to be worth a note."""
    return before > 0 and abs(after - before) > 0.005 * before


def _apart(parts: list[Polygon], reach: float) -> list[Polygon]:
    """Keep only parts that stay `reach` away from the parts already kept.

    The closing is what normally holds a motif's own parts a strut apart, and
    it does so by construction: the complement of a closed shape is a union of
    discs of that radius, so nothing in it can be narrower. What construction
    cannot survive is its own arithmetic at the exact width where two parts
    are on the edge of merging. There the library hands back a hairline sliver
    joining them, and dropping the sliver would leave the two a hair apart.

    So the rule is put in twice: once as a shape, and once as this, which
    keeps the larger part and leaves the cover solid where the other was.
    """
    kept: list[Polygon] = []
    for poly in sorted(parts, key=lambda q: q.area, reverse=True):
        if all(poly.distance(other) >= reach for other in kept):
            kept.append(poly)
    return kept


def _inradius(poly: Polygon) -> float:
    """Inscribed radius in domain units, or zero when there is not one."""
    if poly.area <= 0:
        return 0.0
    try:
        centre = polylabel(poly, tolerance=0.03 * math.sqrt(poly.area))
    except Exception:
        return 0.0
    return float(poly.exterior.distance(centre))


def _motif_holes(
    pocket: Polygon,
    place: Placement,
    profile: PrinterProfile,
    strut: float,
    lo: float,
    hi: float,
    a_max: float,
    fill: float,
    angle: float,
    scale: float,
    quad_segs: int,
    chord_tolerance: float,
) -> tuple[list[Polygon], float, bool, bool]:
    """Fit the motif into one cell.

    Returns its parts, the fill it settled on, and whether the closing and the
    opening each actually took something away, so the panel can say what the
    picture cost rather than warn about it every time.

    The pocket is the cell already eroded by half a strut, which is exactly
    what a cell's own hole is cut from, so the strut between two neighbouring
    motifs is the strut the slider asked for and there is nothing to check.

    Inside the pocket two morphological steps do the rest of the work, and the
    order they come in is the whole of their correctness.

    Opening by MIN_HOLE/2 goes first and deletes anything thinner than a hole:
    a leaf's stem goes on its own that way, and so does the pixel fringe on a
    photograph traced at a bad threshold. An opened shape is a union of discs
    of that radius, so nothing in it can be too thin.

    Closing by strut/2 goes second and widens every gap in the motif narrower
    than a strut, because two prongs of a fork are a strut like any other. It
    has to be second: opening can part a shape at a thin waist, and the two
    halves come back a hair apart. Closing after it sweeps those up, and it
    cannot undo the opening, because closing only ever adds.

    Both steps stay inside the cell. Every disc the opening puts back was
    already inside the pocket. And the closing of a shape never leaves any
    half-plane the shape was in, so it never leaves the pocket either, the
    pocket being a convex cell eroded by a constant.
    """
    try:
        centre = polylabel(pocket, tolerance=0.03 * math.sqrt(pocket.area))
    except Exception:
        return [], fill, False, False
    inscribed = pocket.exterior.distance(centre)
    if inscribed <= 0:
        return [], fill, False, False

    # Every radius here carries the simplification tolerance as well, so a
    # gap is still a strut wide and a detail still a hole wide *after* the
    # outline has been thinned out.
    tolerance = chord_tolerance / lo
    close = (strut / 2.0 + chord_tolerance) / lo
    open_by = (profile.MIN_HOLE / 2.0 + chord_tolerance) / lo
    cx, cy = centre.x, centre.y

    for _ in range(MOTIF_ATTEMPTS):
        if fill < MOTIF_FLOOR:
            return [], fill, False, False
        laid = _lay(place.shape, fill * scale * 2.0 * inscribed, angle, cx, cy)
        clipped = laid.intersection(pocket)
        opened = clipped.buffer(-open_by, quad_segs=quad_segs).buffer(
            open_by, quad_segs=quad_segs
        )
        closed = opened.buffer(close, quad_segs=quad_segs).buffer(
            -close, quad_segs=quad_segs
        )
        # An outline out of four buffers carries three times the vertices it
        # needs, and the triangulation that turns it into a prism cap costs
        # more than linearly in them. Simplifying here is paid for above.
        loose = [q for p in _outlines(closed) for q in _outlines(p.simplify(tolerance))]
        # A part below MIN_HOLE is not cut, which is the rule a cell's own hole
        # already lives by. Simplifying an outline can leave a sliver where a
        # part would otherwise have disappeared, and this is where it goes.
        sized = [(q, _inradius(q)) for q in loose]
        big = [(q, r) for q, r in sized if 2.0 * r * lo >= profile.MIN_HOLE]
        parts = _apart([q for q, _ in big], strut / lo)
        if not parts:
            return [], fill, False, False
        span = 2.0 * max(r for q, r in big if q in parts) * hi
        if span <= a_max:
            return (
                parts,
                fill,
                _shrank(clipped.area, opened.area),
                _shrank(opened.area, closed.area),
            )
        # Linear in the scale, so one step lands close and the next two only
        # pay back what the closing and the clip put on.
        fill *= 0.98 * a_max / span
    return [], fill, False, False


# --- main entry ---------------------------------------------------------


def build_pattern(
    cells: CellField,
    mask: Field,
    *,
    profile: PrinterProfile,
    corner_radius: float = 0.0,
    quad_segs: int = 3,
    chord_tolerance: float = 0.0,
    placement: Placement | None = None,
) -> PatternResult:
    """Turn the cell field into holes. Nothing here can refuse a design."""
    warp, domain = cells.warp, cells.domain
    q_lo, q_hi = domain.V_lo / warp.sy, domain.V_hi / warp.sy
    pts = cells.seeds
    result = PatternResult(strut=cells.strut)
    if len(pts) < 4:
        return result
    if placement is not None and placement.shape.is_empty:
        # A picture with nothing in it is a cover with nothing cut out of it.
        result.cells = len(pts)
        result.solid_cells = len(pts)
        return result

    mask_fn = as_array_field(mask)

    holes: list[np.ndarray] = []
    solid = 0
    subdivided = 0
    rounds = 0
    for rounds in range(1, MAX_SUBDIVISION_ROUNDS + 1):
        lattice = _rings(pts, warp.period, q_lo, q_hi, cells.band)
        holes, solid, oversized = _erode(
            lattice,
            warp,
            domain,
            cells.strut,
            profile,
            cells.a_max,
            quad_segs,
            chord_tolerance,
            mask_fn,
            corner_radius,
            placement,
            result,
        )
        if not oversized:
            break
        pts = _subdivide(pts, lattice, oversized)
        subdivided += len(oversized)
    # No pass ever emits a hole it could not bring inside the limits: a cell
    # that cannot comply is left solid instead. A motif is never subdivided:
    # it shrinks in place, so that loop runs once.

    result.holes = [
        np.stack([ring[:, 0] / TWO_PI, domain.v_of_V(ring[:, 1])], axis=1) for ring in holes
    ]
    result.cells = len(pts)
    result.solid_cells = solid
    result.subdivided = subdivided
    result.rounds = rounds
    return result


def _erode(
    lattice: list[np.ndarray | None],
    warp: Warp,
    domain: _Domain,
    strut: float,
    profile: PrinterProfile,
    a_max: float,
    quad_segs: int,
    chord_tolerance: float,
    mask_fn: Field,
    corner_radius: float,
    placement: Placement | None,
    tally: PatternResult,
) -> tuple[list[np.ndarray], int, list[int]]:
    holes: list[np.ndarray] = []
    solid = 0
    oversized: list[int] = []

    live = [i for i, r in enumerate(lattice) if r is not None]
    solid += len(lattice) - len(live)
    if not live:
        return holes, solid, oversized

    # Carry the cells into the domain first: every measurement below is then
    # in the surface's own coordinates and the warp cannot bend a rule.
    cells = [Polygon(warp.to_domain(lattice[i])) for i in live]
    keep = [k for k, c in enumerate(cells) if c.area > 1e-12]
    solid += len(cells) - len(keep)
    cells = [cells[k] for k in keep]
    live = [live[k] for k in keep]
    if not cells:
        return holes, solid, oversized

    # A cell covers a patch of the domain, and the scale varies across it.
    scales = [domain.box(*np.asarray(c.bounds)[[0, 2, 1, 3]]) for c in cells]
    lo_all = np.array([lo for lo, _ in scales])
    hi_all = np.array([hi for _, hi in scales])

    centroids = np.array([[c.centroid.x, c.centroid.y] for c in cells])
    strength = mask_fn(centroids[:, 0] / TWO_PI, domain.v_of_V(centroids[:, 1]))

    if placement is not None:
        return _motif_pass(
            cells,
            live,
            lattice,
            lo_all,
            hi_all,
            strength,
            solid,
            placement,
            profile,
            strut,
            chord_tolerance,
            a_max,
            quad_segs,
            tally,
        )

    for k, poly in enumerate(cells):
        lo, hi = float(lo_all[k]), float(hi_all[k])
        # Erode by half a strut measured in millimetres at the cell's tightest
        # scale, so the real strut is never thinner than asked for. The chord
        # tolerance pays back what the mesh's straight edges bow into it, and
        # the mask term eats into the cell's own radius where the pattern is
        # fading out, so a fine pattern fades at the same rate as a coarse one.
        reach = 2.0 * poly.area / poly.length if poly.length > 0 else 0.0
        fade = (1.0 - float(strength[k])) * MASK_CLOSE * reach
        inset = (strut / 2.0 + chord_tolerance) / lo + fade
        hole = poly.buffer(-inset, quad_segs=quad_segs, join_style=1)
        if hole.is_empty or hole.geom_type != "Polygon":
            solid += 1
            continue

        if corner_radius > 0.0 and hole.length > 0:
            # Opening the hole rounds its corners and can only make it
            # smaller, so no rule needs re-checking on account of it.
            r = corner_radius * ROUND_FRACTION * (2.0 * hole.area / hole.length)
            hole = hole.buffer(-r, quad_segs=quad_segs).buffer(r, quad_segs=quad_segs)
            if hole.is_empty or hole.geom_type != "Polygon":
                solid += 1
                continue

        ring = np.asarray(hole.exterior.coords)[:-1]
        if len(ring) < 3:
            solid += 1
            continue
        try:
            centre = polylabel(hole, tolerance=0.03 * math.sqrt(hole.area))
            r_dom = hole.exterior.distance(centre)
        except Exception:
            solid += 1
            continue
        if 2.0 * r_dom * lo < profile.MIN_HOLE:
            solid += 1
            continue
        if 2.0 * r_dom * hi > a_max:
            oversized.append(live[k])
            continue
        holes.append(ring)
    return holes, solid, oversized


def _motif_pass(
    cells: list[Polygon],
    live: list[int],
    lattice: list[np.ndarray | None],
    lo_all: np.ndarray,
    hi_all: np.ndarray,
    strength: np.ndarray,
    solid: int,
    place: Placement,
    profile: PrinterProfile,
    strut: float,
    chord_tolerance: float,
    a_max: float,
    quad_segs: int,
    tally: PatternResult,
) -> tuple[list[np.ndarray], int, list[int]]:
    """The same cells, filled with a picture instead of with themselves.

    The scatter is drawn once for the whole lattice and read by each cell's own
    index, so it belongs to the cell rather than to the order the cells came
    out in. The stream starts from the same seed the layout did, which is what
    makes one set of parameters and one file give one mesh, every time.
    """
    rng = np.random.default_rng(place.seed)
    turn = rng.uniform(-1.0, 1.0, len(lattice))
    grow = rng.uniform(-1.0, 1.0, len(lattice))
    lean = math.radians(place.rotation + (place.flow_angle if place.align_flow else 0.0))

    holes: list[np.ndarray] = []
    for k, poly in enumerate(cells):
        lo, hi = float(lo_all[k]), float(hi_all[k])
        # Twice the chord tolerance: once for the bow a straight mesh edge
        # puts into the strut, once for the outline being simplified to the
        # same tolerance before it becomes a ring.
        pocket = poly.buffer(
            -(strut / 2.0 + 2.0 * chord_tolerance) / lo, quad_segs=quad_segs, join_style=1
        )
        if pocket.is_empty or pocket.geom_type != "Polygon":
            solid += 1
            continue

        # Where the mask fades the motif shrinks and goes out, rather than
        # having its edges eaten by a deeper erosion. A leaf half gone still
        # reads as a leaf; a leaf with a bite out of it reads as a mistake.
        i = live[k]
        fill = place.fill * float(strength[k])
        angle = lean + math.radians(place.rotation_jitter) * float(turn[i])
        scale = 1.0 + place.scale_jitter * float(grow[i])

        parts, took, thinned, merged = _motif_holes(
            pocket,
            place,
            profile,
            strut,
            lo,
            hi,
            a_max,
            fill,
            angle,
            scale,
            quad_segs,
            chord_tolerance,
        )
        if not parts:
            solid += 1
            continue
        if took < fill - 1e-9:
            tally.reduced += 1
            tally.least_fill = min(tally.least_fill, took)
        tally.thinned += thinned
        tally.merged += merged
        for part in parts:
            ring = np.asarray(part.exterior.coords)[:-1]
            if len(ring) >= 3:
                holes.append(ring)
    return holes, solid, []


def _subdivide(
    pts: np.ndarray, lattice: list[np.ndarray | None], oversized: list[int]
) -> np.ndarray:
    """Replace an oversized cell's seed with three, so the cell splits.

    Subdividing rather than shrinking keeps the pattern's own character: the
    mesh simply gets finer where the wall needs more support.
    """
    keep = np.ones(len(pts), dtype=bool)
    extra = []
    for idx in oversized:
        ring = lattice[idx]
        if ring is None:
            continue
        keep[idx] = False
        centre = ring.mean(axis=0)
        radius = float(np.mean(np.linalg.norm(ring - centre, axis=1)))
        for k in range(3):
            ang = TWO_PI * k / 3.0 + 0.3
            extra.append(centre + 0.5 * radius * np.array([math.cos(ang), math.sin(ang)]))
    return np.vstack([pts[keep], np.array(extra)]) if extra else pts


__all__ = [
    "CellField",
    "Fields",
    "PatternResult",
    "Placement",
    "Warp",
    "build_cells",
    "build_pattern",
]
