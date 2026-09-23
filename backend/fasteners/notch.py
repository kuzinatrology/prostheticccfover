"""The opening at the back, and what fills it.

A cover that crosses the knee is in the way of the knee.  Everything above the
flexion axis swings back when the leg bends; the cover is bolted to the shin
and does not, so the back of it has to be cut away in a shape wide enough for
however far the module bends -- 130 degrees on the College Park Capital.

Two things are built here:

*   the **notch** -- what a thigh sweeps through, taken out of the cover;
*   the **shroud** -- a second wall standing in the opening, sunk in far enough
    that the thigh passes over it, so the notch reads as a recess rather than
    as a hole with the prosthesis showing through it.

The sweep is not sampled.  A thigh turning about an axis is a cylinder turning
about a line, and how far a point lies outside that is a closed formula: the
nearest angle of the sweep is simply the point's own angle, clamped to the
range the knee turns through.  So the same call answers both "cut here" and
"how far is this from the cut", and the second is what fades the pattern.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from manifold3d import Manifold

from . import config as cfg
from . import solids as S


def thigh_radius(hardware) -> float:
    """How thick the thigh is, taken off the scan just above the knee.

    The 90th percentile of the section radius over the first 40 mm above the
    axis, not the largest and not the mean.  The largest follows one spike of
    scan noise; the mean is pulled down by the third of each section the scan
    never reached.  The transfemoral tab met the same choice and settled it the
    same way -- a thigh read too fat bites the front half into a waist, and one
    read too thin lets the leg foul the cover at deep flexion.
    """
    z = hardware.z - hardware.shift[2]
    rows = (z >= 0.0) & (z <= cfg.THIGH_SAMPLE_MM)
    band = hardware.radius[rows]
    band = band[np.isfinite(band)]
    if band.size == 0:
        return cfg.THIGH_RADIUS_FALLBACK
    return float(np.clip(np.percentile(band, 90), 30.0, 80.0))


@dataclass(frozen=True)
class Sweep:
    """The volume a thigh passes through, in one cover's frame."""

    origin: np.ndarray
    """A point on the flexion axis."""

    radius: float
    angle: float
    length: float = 320.0
    start: float = cfg.THIGH_START_MM
    """How far up the femur the thigh begins.  Below it is the knee module."""

    @classmethod
    def for_cover(cls, hardware, angle: float, radius: float | None = None) -> "Sweep":
        return cls(
            origin=np.asarray(hardware.shift, dtype=float),
            radius=thigh_radius(hardware) if radius is None else float(radius),
            angle=float(angle),
        )

    def distance(self, pts: np.ndarray) -> np.ndarray:
        """How far each point is outside the swept thigh, mm.  Negative inside.

        The axis runs along x, the thigh starts straight up and turns back, so
        a point's own angle about the axis says which moment of the sweep comes
        nearest it.  Clamped to the range the knee turns through: below the
        start the nearest is the leg straight, past the end it is the leg fully
        bent, and in between the thigh passes straight through the point's own
        angle and only the distance along the axis is left.
        """
        p = np.asarray(pts, dtype=float).reshape(-1, 3) - self.origin
        dx, dy, dz = p[:, 0], p[:, 1], p[:, 2]
        rho = np.hypot(dy, dz)
        phi = np.arctan2(-dy, dz)
        theta = np.clip(phi, 0.0, math.radians(self.angle))
        along = rho * np.cos(phi - theta)
        perp = np.abs(rho * np.sin(phi - theta))
        radial = np.hypot(dx, perp) - self.radius
        axial = np.maximum(self.start - along, along - self.length)
        outside = np.hypot(np.maximum(radial, 0.0), np.maximum(axial, 0.0))
        return outside + np.minimum(np.maximum(radial, axial), 0.0)

    def solid(self, grow: float = 0.0, steps: int = 24) -> Manifold:
        """The same volume as a body, for the boolean that does the cutting.

        Built as the cylinder at a number of angles, unioned.  `distance` is
        exact and this is not, so the step is chosen from the sag it leaves:
        between two angles the union falls short of the true sweep by
        r(1 - cos(step/2)), and at 130 degrees over 24 steps that is under a
        tenth of a millimetre.
        """
        r = self.radius + grow
        lo = max(self.start - grow, 0.0)
        parts = []
        for k in range(steps + 1):
            a = self.angle * k / steps
            cyl = Manifold.cylinder(self.length + grow - lo, r, r, 64).translate([0.0, 0.0, lo])
            # Positive about x swings the top toward -y, which is backward:
            # y is forward in this frame, and a knee bends the thigh back.
            cyl = cyl.rotate([a, 0.0, 0.0])
            parts.append(cyl.translate(list(self.origin)))
        return S.add(parts)

    def sag(self, steps: int = 24) -> float:
        return self.radius * (1.0 - math.cos(math.radians(self.angle) / (2 * steps)))


def field(surface, sweep: Sweep, clearance: float, rows: int = 240, cols: int | None = None):
    """Distance from the notch, over the cover's own (u, v) square.

    Positive outside the opening, so it drops into the pattern's edge mask the
    same way a rim does.
    """
    def at(u, v):
        p = surface.point(u, v)
        d = sweep.distance(p.reshape(-1, 3)) - clearance
        return d.reshape(np.shape(p)[:-1])

    return at


def tidy_top(surface, sweep: Sweep, clearance: float, centre=None, around: int = 360,
             samples: int = 200, smooth_deg: float = 45.0) -> tuple[np.ndarray, np.ndarray]:
    """An even top rim: the highest the cover may reach at every angle.

    The raw edge the sweep leaves is uneven -- on this cover it drops twenty
    millimetres over part of the front, because at no flexion at all the thigh
    stands straight up through the top of it.  Smoothed round the section it
    becomes one gentle curve; taken back to the raw value wherever the smooth
    one is higher, it never reaches into the sweep.
    """
    from scipy.ndimage import gaussian_filter1d

    u = np.linspace(0.0, 1.0, around, endpoint=False)
    v = np.linspace(0.0, 1.0, samples)
    uu, vv = np.meshgrid(u, v, indexing="ij")
    p = surface.point(uu, vv)
    d = sweep.distance(p.reshape(-1, 3)).reshape(uu.shape) - clearance
    z = p[..., 2]

    # Where each column stops being clear, to the millimetre and not to the
    # nearest row of the grid: rounding to a row leaves the rim a staircase
    # three millimetres deep, which is the one thing this is here to avoid.
    highest = np.empty(around)
    rim_xy = np.empty((around, 2))
    for i in range(around):
        col = d[i]
        free = col >= 0.0
        if not free.any():
            j, t = 0, 0.0
        else:
            j = int(np.max(np.nonzero(free)[0]))
            if j == samples - 1:
                j, t = samples - 2, 1.0
            else:
                a, b = col[j], col[j + 1]
                t = a / (a - b) if a != b else 0.0
        q = p[i, j] + t * (p[i, j + 1] - p[i, j])
        highest[i] = q[2]
        rim_xy[i] = q[:2]

    # The rim is taken per column of the unwrapping, and on this surface a
    # column does not sit at the angle its parameter suggests: the section's
    # centre drifts with height, so u and the angle about one fixed centre
    # differ by a few degrees.  The roof is built about that fixed centre, so
    # the rim is resampled onto its angles -- otherwise every column lands a
    # little beside where its height was measured, and the edge comes out
    # serrated.
    c = np.asarray(centre if centre is not None else rim_xy.mean(axis=0), dtype=float)
    ang = np.arctan2(rim_xy[:, 1] - c[1], rim_xy[:, 0] - c[0]) % (2.0 * np.pi)
    order = np.argsort(ang)
    ang, height = ang[order], highest[order]
    theta = np.linspace(0.0, 2.0 * np.pi, around, endpoint=False)
    at_theta = np.interp(theta, np.concatenate([ang, ang[:1] + 2.0 * np.pi]),
                         np.concatenate([height, height[:1]]))
    width = max(smooth_deg / 360.0 * around, 1.0)
    smoothed = gaussian_filter1d(at_theta, width, mode="wrap")
    return theta, np.minimum(smoothed, at_theta)
