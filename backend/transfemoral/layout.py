"""Where the cover is, and which half it belongs to.

Everything here is a field over the unwrapped surface: a function of (u, v)
giving a distance in millimetres. The notch, the seam and the rims are three of
them, and they are the same kind of object as the mask a pattern lives under.
Where material is and where the pattern fades out are read from the same
fields, so a hole can never land somewhere the cover does not exist.

The notch is the knee's sector, grown by its fillet, together with everything
the thigh sweeps through on its way to full flexion. The sector alone does not
clear the thigh: a leg-radius cylinder above the knee is wider than the shin,
and turning it sweeps its sides across the shin's side walls below the
sector's lower edge. Both parts come from the same configuration, and the
rotation test is run against the thigh itself, not against either shape.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from functools import lru_cache

import numpy as np
from scipy.interpolate import RegularGridInterpolator
from shapely.geometry import MultiPolygon, Polygon, box
from skimage import measure

from ..surface import TWO_PI
from . import config as cfg
from .knee import Knee
from .scan_surface import ScanSurface

COARSE_STEP_DEG = 2.5
FINE_STEP_DEG = 0.25


# --- the thigh ----------------------------------------------------------------


@dataclass(frozen=True)
class Thigh:
    """The thigh stand-in: a leg-radius cylinder standing on top_z.

    Flexion turns it backward about the knee axis. `penetration` is how far a
    point is inside the body at its worst angle, clearance included; negative
    means outside by at least that much.
    """

    knee: Knee
    centre_x: float
    centre_y: float
    radius: float
    bottom: float
    clearance: float

    @classmethod
    def for_surface(cls, surface: ScanSurface, knee: Knee) -> Thigh:
        """Radius: half the width of the knee across, at the axis.

        The mean radius at top_z would be the obvious reading, and it is 67 mm
        on this scan, because that section is the bent knee: 153 mm front to
        back with the thigh and the filled blind spot in it. A cylinder that
        size is wider than the shin and bites the front half at the knee into
        a waist. Across the knee the scan is not distorted by the bend, and it
        gives 56 mm, which is what a leg that size is.
        """
        return cls(knee, *thigh_centre_and_radius(surface), cfg.top_z, cfg.notch_clearance)

    def _at(self, points: np.ndarray, angles: np.ndarray, grow: float) -> np.ndarray:
        dy = points[:, 1] - self.knee.axis_y
        dz = points[:, 2] - self.knee.axis_z
        dx = points[:, 0] - self.centre_x
        best = np.full(len(points), -np.inf)
        for a in angles:
            c, s = math.cos(a), math.sin(a)
            # Undo the thigh's turn on the point instead of turning the thigh.
            qy = dy * c + dz * s + self.knee.axis_y
            qz = -dy * s + dz * c + self.knee.axis_z
            rho = np.hypot(dx, qy - self.centre_y)
            best = np.maximum(best, np.minimum(qz - self.bottom, self.radius + grow - rho))
        return best

    def penetration(self, points: np.ndarray, grow: float | None = None) -> np.ndarray:
        """Worst depth inside the swept thigh over the whole flexion range.

        Sampled coarsely, then again finely wherever the coarse answer could
        be near zero. Each term moves by at most the arc a point travels
        between two samples, which is what bounds the error of the coarse pass.
        """
        grow = self.clearance if grow is None else grow
        pts = np.asarray(points, dtype=float).reshape(-1, 3)
        flex = math.radians(self.knee.flexion)
        coarse = np.linspace(0.0, flex, max(2, int(math.ceil(self.knee.flexion / COARSE_STEP_DEG)) + 1))
        f = self._at(pts, coarse, grow)
        arm = np.hypot(pts[:, 1] - self.knee.axis_y, pts[:, 2] - self.knee.axis_z)
        slack = arm * (coarse[1] - coarse[0]) / 2.0
        near = np.abs(f) <= slack + 1.0
        if np.any(near):
            fine = np.linspace(0.0, flex, int(math.ceil(self.knee.flexion / FINE_STEP_DEG)) + 1)
            f[near] = self._at(pts[near], fine, grow)
        return f.reshape(np.shape(points)[:-1])


def thigh_centre_and_radius(surface: ScanSurface) -> tuple[float, float, float]:
    theta = np.linspace(0.0, TWO_PI, 720, endpoint=False)
    c = surface.centre(cfg.knee_axis_z)
    r = surface.radial(theta, np.full(720, cfg.knee_axis_z))
    across = c[0] + r * np.cos(theta)
    top = surface.centre(cfg.top_z)
    return float((across.max() + across.min()) / 2.0), float(top[1]), float(np.ptp(across) / 2.0)


def smooth_min(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    """A union that rounds its inside corners by about k and never shrinks."""
    if k <= 0:
        return np.minimum(a, b)
    h = np.maximum(k - np.abs(a - b), 0.0)
    return np.minimum(a, b) - h * h / (4.0 * k)


# --- the grid -----------------------------------------------------------------


@dataclass(frozen=True)
class Resolution:
    nu: int
    dz: float
    chord: float
    """Longest triangle edge on a body's faces, mm."""


DRAFT_RES = Resolution(nu=360, dz=2.0, chord=5.0)
FINAL_RES = Resolution(nu=720, dz=1.0, chord=2.5)


def _pad_v(surface: ScanSurface, dz: float) -> np.ndarray:
    """v samples running a few rows past both rims, so contours close."""
    rows = int(math.ceil(surface.length / dz)) + 1
    v = np.linspace(0.0, 1.0, rows)
    step = v[1] - v[0]
    return np.concatenate([[-2 * step, -step], v, [1 + step, 1 + 2 * step]])


@dataclass
class NotchGrid:
    u: np.ndarray
    v: np.ndarray
    signed: np.ndarray
    """(nv, nu) signed distance to the notch at the deepest layer, mm.
    Negative inside."""
    thigh: Thigh


LAYER_STEP = 2.0
"""mm between the depths the notch is read at. The swept thigh is not
monotonic through the wall: a layer between two clear ones can be inside it."""


@lru_cache(maxsize=4)
def notch_grid(smoothing: float, depth: float, res: Resolution, wall: float = 0.0) -> NotchGrid:
    """The notch over the whole surface, at every depth anything is built at."""
    surface = ScanSurface.default(smoothing)
    knee = knee_for(surface)
    thigh = Thigh.for_surface(surface, knee)
    u = np.linspace(0.0, 1.0, res.nu, endpoint=False)
    v = _pad_v(surface, res.dz)
    uu, vv = np.meshgrid(u, v)
    p, n = surface.frame(uu, np.clip(vv, 0.0, 1.0))
    p[..., 2] = surface.z_of_v(vv)
    worst = np.full(uu.shape, np.inf)
    depths = set(np.linspace(0.0, depth, int(math.ceil(depth / LAYER_STEP)) + 1).tolist())
    depths.add(wall)
    for d in sorted(depths):
        layer = p - n * d
        sector = knee.notch_distance(layer)
        swept = -thigh.penetration(layer)
        worst = np.minimum(worst, smooth_min(sector, swept, knee.fillet))
    return NotchGrid(u=u, v=v, signed=worst, thigh=thigh)


def knee_for(surface: ScanSurface) -> Knee:
    return Knee(
        axis_y=float(surface.data.meta["knee_axis_y"]) + cfg.knee_axis_y_offset,
        axis_z=cfg.knee_axis_z,
        flexion=min(cfg.flexion_angle, 179.0),
        split=cfg.notch_split,
        fillet=cfg.notch_fillet,
    )


# --- the layout ---------------------------------------------------------------


@dataclass
class Side:
    """One seam: +1 is the +x side, -1 the -x side."""

    sign: int
    meet: float
    """Height where the seam runs into the notch; the back half ends here."""
    bottom: float


@dataclass
class Layout:
    surface: ScanSurface
    knee: Knee
    thigh: Thigh
    res: Resolution
    clearance: float
    seam_offset: float
    u: np.ndarray
    v: np.ndarray
    notch: np.ndarray
    seam: np.ndarray
    """(nv, nu) y minus the seam plane's y at that height, mm: positive is
    toward the front."""
    side: np.ndarray
    """(nv, nu) +1 where the surface is on the +x side of the centreline."""
    sides: dict[int, Side] = field(default_factory=dict)
    seam_offset_max: float = 0.0
    back_span_deg: float = 0.0

    # --- construction -----------------------------------------------------
    @classmethod
    def build(
        cls,
        surface: ScanSurface,
        smoothing: float,
        depth: float,
        seam_offset: float,
        clearance: float,
        res: Resolution,
        wall: float = 0.0,
    ) -> Layout:
        grid = notch_grid(round(smoothing, 4), round(depth, 2), res, round(wall, 3))
        uu, vv = np.meshgrid(grid.u, grid.v)
        p = surface.point(uu, np.clip(vv, 0.0, 1.0))
        z = surface.z_of_v(vv)
        c = surface.centre(z)
        side = np.where(p[..., 0] - c[..., 0] >= 0.0, 1, -1)

        out = cls(
            surface=surface,
            knee=grid.thigh.knee,
            thigh=grid.thigh,
            res=res,
            clearance=clearance,
            seam_offset=seam_offset,
            u=grid.u,
            v=grid.v,
            notch=grid.signed,
            seam=np.zeros_like(z),
            side=side,
        )
        out.seam_offset_max, out.back_span_deg = out._offset_limit()
        out.seam_offset = float(np.clip(seam_offset, 0.0, out.seam_offset_max))
        out.seam = p[..., 1] - out.seam_y(c[..., 1])
        out.sides = {s: out._side(s) for s in (1, -1)}
        # Both seams end where the FIRST of them runs into the notch. The notch
        # is a sector cut at an angle, so it crosses one seam tens of
        # millimetres below the other; taken side by side, the back half keeps
        # a tail between the two heights that narrows from a quarter of the
        # turn to nothing — a fin that prints badly, snaps easily and reads as
        # a mistake. Ending both seams together squares the back half off.
        first = min(side.meet for side in out.sides.values())
        out.sides = {s: replace(side, meet=first) for s, side in out.sides.items()}
        return out

    @property
    def seam_shift(self) -> float:
        """How far the centreline at the knee axis is in front of the axis.

        The seams follow the centreline down the leg, shifted so that at the
        axis height they pass through the axis: at seam_offset = 0 a seam runs
        into the notch exactly at its corner, and moving it back only lowers
        that point."""
        return float(self.surface.centre(cfg.knee_axis_z)[1]) - self.knee.axis_y

    def seam_y(self, centre_y):
        return centre_y - self.seam_shift - self.seam_offset

    def _rows_z(self) -> np.ndarray:
        return self.surface.z_of_v(self.v)

    def _side(self, sign: int) -> Side:
        """Where along its height one seam is a seam at all."""
        z = self._rows_z()
        band = self.clearance / 2.0 + self.clearance
        mask = (self.side == sign) & (np.abs(self.seam) <= band + 2.0)
        inside = np.where(mask, self.notch <= 0.0, False)
        present = mask.any(axis=1)
        blocked = inside.any(axis=1) & present
        rows = np.nonzero((z >= self.surface.z0) & (z <= self.surface.z1))[0]
        meet = self.surface.z1
        for j in rows:
            if blocked[j]:
                meet = float(z[j]) - self.res.dz
                break
        return Side(sign=sign, meet=meet, bottom=self.surface.z0)

    def _offset_limit(self) -> tuple[float, float]:
        """How far back the seams may go.

        The back half keeps at least a quarter turn of the circumference at
        every height it has, and neither seam may run into the notch below
        where the other one does. Read off the grid once per surface.
        """
        z = self._rows_z()
        rows = (z >= self.surface.z0 + 2.0) & (z <= cfg.knee_axis_z)
        theta = TWO_PI * self.u
        uu, vv = np.meshgrid(self.u, self.v[rows])
        p = self.surface.point(uu, np.clip(vv, 0.0, 1.0))
        c = self.surface.centre(p[..., 2])
        notch = self.notch[rows]
        best_span = 0.0
        limit = 0.0
        for offset in np.arange(0.0, 60.0 + 1e-9, 0.5):
            behind = (p[..., 1] < c[..., 1] - self.seam_shift - offset - self.clearance / 2.0) & (notch > 0.0)
            # Only rows where the back half exists at all: below the notch.
            alive = behind.any(axis=1) & (notch > 0.0).all(axis=1)
            if not alive.any():
                break
            span = behind[alive].sum(axis=1) * (360.0 / len(theta))
            if span.min() < 90.0:
                break
            limit = float(offset)
            best_span = float(span.min())
        return limit, best_span

    # --- fields -------------------------------------------------------------
    def interpolator(self, grid: np.ndarray):
        """(u, v) -> value, periodic in u, held beyond the ends in v."""
        u = np.concatenate([self.u - 1.0, self.u, self.u + 1.0])
        values = np.concatenate([grid, grid, grid], axis=1)
        f = RegularGridInterpolator((self.v, u), values, bounds_error=False, fill_value=None)

        def read(uq, vq):
            uq = np.asarray(uq, dtype=float) % 1.0
            vq = np.clip(np.asarray(vq, dtype=float), self.v[0], self.v[-1])
            uq, vq = np.broadcast_arrays(uq, vq)
            return f(np.stack([vq.ravel(), uq.ravel()], axis=1)).reshape(uq.shape)

        return read

    def front_field(self) -> np.ndarray:
        """Positive where the front half has material: in front of its seams
        and clear of the notch, all the way up.

        It used to take everything behind the seam as well, once the seam had
        left the notch and there was no back half left to meet. That is the
        knee, where the notch's edge is already sweeping forward, so what the
        front got was a lens of material twelve millimetres deep peaking at
        z = 45 and pinched off above and below: on the model it reads as a beak
        stuck on the side of the knee. Left at the seam the edge runs straight
        up into the notch and the silhouette is one curve. What is given up is
        a strip behind the seam beside the joint, which is inside the opening
        the notch makes anyway.
        """
        clear = self.clearance / 2.0
        return np.minimum(self.seam - clear, self.notch)

    def back_field(self) -> np.ndarray:
        """Positive where the back half has material."""
        z = self._rows_z()[:, None]
        clear = self.clearance / 2.0
        meet = np.where(self.side == 1, self.sides[1].meet, self.sides[-1].meet)
        return np.minimum(np.minimum(-self.seam - clear, meet - z + self.res.dz), self.notch)

    def seam_distance(self) -> np.ndarray:
        """Distance to the seam gap, mm, where the seam divides; inf elsewhere."""
        z = self._rows_z()[:, None]
        meet = np.where(self.side == 1, self.sides[1].meet, self.sides[-1].meet)
        return np.where(z <= meet + self.res.dz, np.abs(self.seam) - self.clearance / 2.0, np.inf)

    # --- regions as polygons in (u, v) ----------------------------------------
    def region(self, grid: np.ndarray, centre_u: float) -> MultiPolygon:
        """Where `grid` is positive, as polygons around `centre_u`, rims exact.

        The field is laid out over one full turn centred on `centre_u`, so a
        half that crosses u = 0 comes back in one piece.
        """
        nu = len(self.u)
        shift = int(round((centre_u - 0.5) * nu))
        rolled = np.roll(grid, -shift, axis=1)
        u0 = self.u[shift % nu] - (1.0 if shift < 0 else 0.0)
        # Close every contour: a row and a column of "outside" all round.
        padded = np.pad(rolled, 1, constant_values=-1.0)
        du = 1.0 / nu
        polys = []
        for contour in measure.find_contours(padded, 0.0):
            j = contour[:, 0] - 1.0
            i = contour[:, 1] - 1.0
            vq = np.interp(j, np.arange(len(self.v)), self.v)
            uq = u0 + i * du
            if len(uq) < 4:
                continue
            poly = Polygon(np.stack([uq, vq], axis=1))
            if not poly.is_valid:
                poly = poly.buffer(0)
            if poly.area > 0:
                polys.append(poly)
        # Contours come back as outlines and as holes in them alike: an outline
        # contains the holes inside it.
        polys.sort(key=lambda q: q.area, reverse=True)
        shapes: list[Polygon] = []
        for poly in polys:
            host = next((s for s in shapes if s.contains(poly.representative_point())), None)
            if host is None:
                shapes.append(poly)
            else:
                shapes[shapes.index(host)] = host.difference(poly)
        rim = box(u0 - 1.0, 0.0, u0 + 2.0, 1.0)
        parts = []
        for s in shapes:
            clipped = s.intersection(rim)
            for g in getattr(clipped, "geoms", [clipped]):
                if isinstance(g, Polygon) and g.area > 1e-7:
                    parts.append(g)
        return MultiPolygon(parts)

    def uv_mm(self, u: float, v: float) -> tuple[float, float]:
        """Millimetres per unit u and per unit v at a point."""
        e = 1e-4
        p0 = self.surface.point(u, v)
        pu = self.surface.point(u + e, v)
        pv = self.surface.point(u, min(v + e, 1.0))
        return float(np.linalg.norm(pu - p0) / e), float(np.linalg.norm(pv - p0) / e)
