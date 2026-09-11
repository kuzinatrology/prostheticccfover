"""The cover's outer surface and its (u, v) parameterisation.

u is the angle around the circumference, normalised to [0, 1) and PERIODIC.
v is height, normalised to [0, 1], v = 0 at the ankle and v = 1 at the knee.

Everything downstream (pattern, relief, holes, projection) works in that
square. The surface is the only place that knows about millimetres.

The section is a superellipse rather than an ellipse, and its centre moves
backward where the calf swells. Those two together are most of what makes a
shape read as a shin instead of a tapered tube: a real calf grows toward the
back while the front of the shank stays almost flat.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import PchipInterpolator

from .params import CoverParams
from .printer_profile import PrinterProfile

TWO_PI = 2.0 * np.pi

# Axes: +x is lateral, +y is anterior (the front of the shin), +z is up.
# The calf therefore grows toward -y.


@dataclass
class Surface:
    """Outer surface of the cover, sampled from analytic definitions."""

    length: float
    ovality: float
    twist_rad: float
    squareness: float
    posterior_bias: float
    radius: PchipInterpolator
    base_radius: PchipInterpolator
    _angle: np.ndarray = None  # type: ignore[assignment]
    """Lookup from u to the section angle, sampled at equal arc length."""

    # --- construction ---------------------------------------------------
    @classmethod
    def from_params(cls, p: CoverParams) -> "Surface":
        r_ankle = p.ankle_diameter / 2.0
        r_knee = p.knee_diameter / 2.0
        vc = p.calf_position
        plain = r_ankle + (r_knee - r_ankle) * vc
        knots = np.array([0.0, vc, 1.0])
        # PCHIP is shape preserving: it will not invent a waist above the calf.
        return cls(
            length=p.length,
            ovality=p.ovality,
            twist_rad=np.radians(p.twist),
            squareness=p.section_squareness,
            posterior_bias=p.posterior_bias,
            radius=PchipInterpolator(knots, np.array([r_ankle, plain + p.calf_bulge / 2.0, r_knee])),
            base_radius=PchipInterpolator(knots, np.array([r_ankle, plain, r_knee])),
        )

    def __post_init__(self) -> None:
        if self._angle is None:
            self._angle = self._arc_length_table()

    def _arc_length_table(self, samples: int = 4096) -> np.ndarray:
        """u to section angle, so that equal steps in u are equal arc length.

        A superellipse parameterised by angle races through the ends of its
        axes: the curve is perfectly smooth there, but the parameter is not.
        Left alone that stretches every cell sitting near an axis and makes the
        generator subdivide cells that were never too big. The section's shape
        does not change with height, so one table serves the whole cover.
        """
        # The speed blows up at every quarter turn, so the quadrature is
        # clustered there; sampling the angle evenly would measure the arc
        # short exactly where the section is most square.
        w = (1.0 - np.cos(np.linspace(0.0, np.pi, samples // 4 + 1))) / 2.0
        quarter = w * (np.pi / 2.0)
        t = np.unique(
            np.concatenate([quarter + j * np.pi / 2.0 for j in range(4)] + [[TWO_PI]])
        )
        k = self.ovality
        e = 2.0 / self.squareness
        c, s = np.cos(t), np.sin(t)
        x = (1.0 / np.sqrt(k)) * np.sign(c) * np.abs(c) ** e
        y = np.sqrt(k) * np.sign(s) * np.abs(s) ** e
        step = np.hypot(np.diff(x), np.diff(y))
        run = np.concatenate([[0.0], np.cumsum(step)])
        run /= run[-1]
        # Resample so index i holds the angle at arc fraction i / samples.
        return np.interp(np.linspace(0.0, 1.0, samples + 1), run, t)

    def angle(self, u: np.ndarray) -> np.ndarray:
        """Section angle at circumferential position u."""
        frac = np.asarray(u, dtype=float) % 1.0
        table = self._angle
        return np.interp(frac * (len(table) - 1), np.arange(len(table)), table)

    # --- geometry -------------------------------------------------------
    def semi_axes(self, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Section half-widths at height v, keeping a*b = r**2."""
        r = self.radius(np.clip(v, 0.0, 1.0))
        k = self.ovality
        return r / np.sqrt(k), r * np.sqrt(k)

    def swell(self, v: np.ndarray) -> np.ndarray:
        """How much of the radius at this height is calf, in mm."""
        v = np.clip(v, 0.0, 1.0)
        return np.maximum(self.radius(v) - self.base_radius(v), 0.0)

    def centre(self, v: np.ndarray) -> np.ndarray:
        """Where the section sits relative to the axis, in mm along y.

        At posterior_bias = 0 the section stays centred and the calf grows in
        every direction. At 1 it slides back by the whole swell, which leaves
        the front of the shank where it was and puts all of the growth behind.
        """
        return -self.swell(v) * self.posterior_bias

    def point(self, u: np.ndarray, v: np.ndarray) -> np.ndarray:
        """Surface point(s). u and v broadcast together; returns (..., 3)."""
        u = np.asarray(u, dtype=float)
        v = np.asarray(v, dtype=float)
        a, b = self.semi_axes(v)
        phi = self.angle(u)
        c, s = np.cos(phi), np.sin(phi)
        e = 2.0 / self.squareness
        # Superellipse |x/a|^n + |y/b|^n = 1, which is the ellipse at n = 2 and
        # flattens the sides as n grows.
        x0 = a * np.sign(c) * np.abs(c) ** e
        y0 = b * np.sign(s) * np.abs(s) ** e + self.centre(v)
        th = self.twist_rad * v
        ct, st = np.cos(th), np.sin(th)
        return np.stack(
            [x0 * ct - y0 * st, x0 * st + y0 * ct, v * self.length], axis=-1
        )

    def frame(self, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Point and outward unit normal, by central differences in (u, v)."""
        du, dv = 1e-4, 1e-4
        p = self.point(u, v)
        tu = (self.point(u + du, v) - self.point(u - du, v)) / (2 * du)
        vv = np.clip(np.asarray(v, dtype=float), dv, 1.0 - dv)
        tv = (self.point(u, vv + dv) - self.point(u, vv - dv)) / (2 * dv)
        n = np.cross(tu, tv)
        norm = np.linalg.norm(n, axis=-1, keepdims=True)
        # cross(d/du, d/dv) already points away from the axis.
        return p, n / np.maximum(norm, 1e-12)

    def grid(self, nu: int, nv: int) -> tuple[np.ndarray, np.ndarray]:
        """Outer surface as an (nv, nu, 3) point grid plus matching normals."""
        u = np.linspace(0.0, 1.0, nu, endpoint=False)
        v = np.linspace(0.0, 1.0, nv)
        uu, vv = np.meshgrid(u, v)
        return self.frame(uu, vv)

    # --- the Mercator (conformal) pattern domain ------------------------
    # A tube of radius r(v) has metric ds^2 = r^2 (dU^2 + dV^2) when
    # U = 2*pi*u and V = integral(L dv / r(v)). Cells that are round in that
    # domain are round on the cover, and they grow with the cover's girth.
    def mercator(self, samples: int = 512) -> tuple[np.ndarray, np.ndarray]:
        v = np.linspace(0.0, 1.0, samples)
        integrand = self.length / self.radius(v)
        V = np.concatenate(
            [[0.0], np.cumsum(np.diff(v) * (integrand[1:] + integrand[:-1]) / 2)]
        )
        return v, V

    # --- printability inputs --------------------------------------------
    def min_curvature_radius(self, rows: int = 48, around: int = 256) -> float:
        """Smallest radius of curvature where the surface bulges outward.

        Offsetting the wall inward folds on itself once the thickness passes
        this radius, so it is the hard ceiling on wall_thickness. A superellipse
        has no closed form worth writing down, so the section is sampled and
        differentiated; the corners of a squarer section are what it finds.
        """
        v = np.linspace(0.0, 1.0, rows)
        u = np.linspace(0.0, 1.0, around, endpoint=False)
        uu, vv = np.meshgrid(u, v)
        p = self.point(uu, vv)[..., :2]
        # Periodic derivatives around each section.
        d1 = (np.roll(p, -1, axis=1) - np.roll(p, 1, axis=1)) / 2.0
        d2 = np.roll(p, -1, axis=1) - 2.0 * p + np.roll(p, 1, axis=1)
        cross = np.abs(d1[..., 0] * d2[..., 1] - d1[..., 1] * d2[..., 0])
        speed = np.linalg.norm(d1, axis=-1)
        kappa = cross / np.maximum(speed**3, 1e-12)
        r_section = float(1.0 / max(np.max(kappa), 1e-9))

        # Meridian: only convex-outward stretches (rho'' < 0) constrain us.
        z = v * self.length
        rho = np.max(np.linalg.norm(p, axis=-1), axis=1)
        g1 = np.gradient(rho, z)
        g2 = np.gradient(g1, z)
        convex = g2 < -1e-9
        if np.any(convex):
            km = np.abs(g2[convex]) / (1.0 + g1[convex] ** 2) ** 1.5
            r_meridian = float(1.0 / max(np.max(km), 1e-9))
        else:
            r_meridian = np.inf
        return min(r_section, r_meridian)

    def max_wall_thickness(self, profile: PrinterProfile, ceiling: float) -> float:
        """Dynamic upper bound for the wall_thickness slider."""
        return min(ceiling, profile.CURVATURE_SAFETY * self.min_curvature_radius())
