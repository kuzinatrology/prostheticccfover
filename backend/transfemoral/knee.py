"""The knee axis and the notch that lets it bend.

Seen from the side with the origin on the flexion axis, the cover holds one
angular sector and the thigh another. Flexing turns the thigh about the axis
and closes the gap between them by exactly the flexion angle. So the cover
must leave a sector free behind the axis at least that wide, and at every
distance from it: whatever turns about a point moves on an arc, which is why a
rectangular window does not work.

Angles here are measured in the side view from the posterior horizontal,
positive upward. The sector runs from -split*F below it to (1-split)*F above.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import config as cfg


@dataclass(frozen=True)
class Knee:
    axis_y: float
    axis_z: float
    flexion: float
    """Degrees."""
    split: float
    fillet: float

    @classmethod
    def from_config(cls, centre_y_at_axis: float) -> Knee:
        return cls(
            axis_y=centre_y_at_axis + cfg.knee_axis_y_offset,
            axis_z=cfg.knee_axis_z,
            flexion=min(cfg.flexion_angle, 179.0),
            split=cfg.notch_split,
            fillet=cfg.notch_fillet,
        )

    @property
    def lower(self) -> float:
        """Lower edge of the sector, radians, negative."""
        return -math.radians(self.split * self.flexion)

    @property
    def upper(self) -> float:
        return math.radians((1.0 - self.split) * self.flexion)

    def side(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Side-view offsets from the axis: backward and upward."""
        p = np.asarray(points, dtype=float)
        return -(p[..., 1] - self.axis_y), p[..., 2] - self.axis_z

    def angle(self, points: np.ndarray) -> np.ndarray:
        back, up = self.side(points)
        return np.arctan2(up, back)

    def in_sector(self, points: np.ndarray) -> np.ndarray:
        a = self.angle(points)
        return (a >= self.lower) & (a <= self.upper)

    def sector_distance(self, points: np.ndarray) -> np.ndarray:
        """Side-view distance to the sector, zero inside it.

        The sector is convex while it is narrower than a half turn, so the
        nearest point of it is on one of its two edges or at its apex.
        """
        back, up = self.side(points)
        inside = self.in_sector(points)
        best = np.full(np.shape(back), np.inf)
        for edge in (self.lower, self.upper):
            d = np.array([math.cos(edge), math.sin(edge)])
            along = back * d[0] + up * d[1]
            across = np.abs(back * d[1] - up * d[0])
            dist = np.where(along >= 0.0, across, np.hypot(back, up))
            best = np.minimum(best, dist)
        return np.where(inside, 0.0, best)

    def notch_distance(self, points: np.ndarray) -> np.ndarray:
        """Signed distance to the notch: negative inside it.

        The notch is the sector grown by the fillet, so its V is rounded and
        the rounding only ever takes material away.
        """
        return self.sector_distance(points) - self.fillet

    def back_height_range(self, distance_behind: float) -> tuple[float, float]:
        """Where the sector's edges meet a vertical line this far behind the axis."""
        def at(edge: float) -> float:
            # An edge at or past the vertical never meets a line behind the axis.
            if abs(edge) >= math.pi / 2.0:
                return math.copysign(math.inf, edge)
            return self.axis_z + distance_behind * math.tan(edge)

        return at(self.lower), at(self.upper)
