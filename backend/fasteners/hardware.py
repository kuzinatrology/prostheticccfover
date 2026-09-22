"""The prosthesis, in whatever frame a cover is drawn in.

`tools/prepare_hardware.py` measures the scan once and stores it; this reads
that and answers the two questions the fasteners ask of it: where is the tube,
and how close is anything else.

The two covers that use this are drawn in different frames, so a `Hardware` is
always made for one of them and carries the shift as part of itself.  Nothing
downstream has to know which cover it is holding.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from . import config as cfg


@dataclass(frozen=True)
class Tube:
    """The pylon: a straight line and a catalogue radius.

    `radius` is the catalogue's, not the fit's.  A third of the tube's
    circumference is missing from the scan -- its section outlines measure 75
    of the 107 mm a 34 mm tube has -- so a radius read off it comes out small,
    and a clamp bored to it does not go on.  The fit agrees with the catalogue
    to 0.33 mm, which is what makes the catalogue safe to use.
    """

    x_of_z: tuple[float, float]
    y_of_z: tuple[float, float]
    radius: float
    z_lo: float
    z_hi: float
    tilt_deg: float

    def centre(self, z) -> np.ndarray:
        z = np.asarray(z, dtype=float)
        return np.stack([
            self.x_of_z[0] * z + self.x_of_z[1],
            self.y_of_z[0] * z + self.y_of_z[1],
        ], axis=-1)

    @property
    def direction(self) -> np.ndarray:
        d = np.array([self.x_of_z[0], self.y_of_z[0], 1.0])
        return d / np.linalg.norm(d)

    def frame(self, z: float) -> np.ndarray:
        """3x4: x across, y forward, z along the tube, origin on its axis."""
        ez = self.direction
        ey = np.array([0.0, 1.0, 0.0]) - ez[1] * ez
        ey /= np.linalg.norm(ey)
        ex = np.cross(ey, ez)
        c = self.centre(z)
        return np.column_stack([ex, ey, ez, [c[0], c[1], z]])

    def shifted(self, shift: np.ndarray) -> "Tube":
        """The same tube in a frame moved by `shift`.

        A shift in z moves the line along itself as well as up, so the
        intercepts have to be corrected by the slope, not merely offset.
        """
        dx, dy, dz = shift
        return Tube(
            x_of_z=(self.x_of_z[0], self.x_of_z[1] + dx - self.x_of_z[0] * dz),
            y_of_z=(self.y_of_z[0], self.y_of_z[1] + dy - self.y_of_z[0] * dz),
            radius=self.radius,
            z_lo=self.z_lo + dz,
            z_hi=self.z_hi + dz,
            tilt_deg=self.tilt_deg,
        )

    def distance(self, pts: np.ndarray) -> np.ndarray:
        """How far each point is outside the tube, mm.  Negative inside."""
        pts = np.asarray(pts, dtype=float)
        c = self.centre(pts[:, 2])
        return np.hypot(pts[:, 0] - c[:, 0], pts[:, 1] - c[:, 1]) - self.radius


@lru_cache(maxsize=1)
def _stored() -> tuple[dict, dict]:
    data = np.load(cfg.HARDWARE_NPZ)
    report = json.loads(cfg.HARDWARE_JSON.read_text())
    return {k: data[k] for k in data.files}, report


@dataclass(frozen=True)
class Hardware:
    """Everything in the way, in one cover's own coordinates."""

    z: np.ndarray
    """Heights of the stored grid, in this cover's frame."""

    radius: np.ndarray
    coverage: np.ndarray
    tube: Tube
    shift: np.ndarray
    name: str

    @property
    def _z_scan(self) -> np.ndarray:
        """The grid's heights in the scan's own frame, which is where the
        stored radii were measured."""
        return self.z - self.shift[2]

    # --- making one -------------------------------------------------------

    @classmethod
    def _base(cls) -> tuple[np.ndarray, np.ndarray, np.ndarray, Tube]:
        data, report = _stored()
        p = report["pylon"]
        knee_axis_at = 213.0  # stage 1's z of the knee axis; stage 2 moved the origin there
        parts = report["parts_z"]
        tube = Tube(
            x_of_z=tuple(p["x_of_z"]),
            y_of_z=tuple(p["y_of_z"]),
            radius=float(p["radius_catalogue_mm"]),
            z_lo=float(parts["pylon"][0]) - knee_axis_at,
            z_hi=float(parts["pylon"][1]) - knee_axis_at,
            tilt_deg=float(p["tilt_deg"]),
        )
        return data["z"], data["radius"], data["coverage"], tube

    @classmethod
    def for_anatomic(cls) -> "Hardware":
        """The anatomic cover is built in the knee-axis frame already."""
        z, radius, coverage, tube = cls._base()
        return cls(z, radius, coverage, tube, np.zeros(3), "anatomic")

    @classmethod
    def for_model(cls, key: str) -> "Hardware":
        """A modelled (Rhino) cover, in its own frame.

        `prepare_hardware` slides the scan inside each cover's inner skin until
        the room to spare is greatest.  For `Cover new.stl` that comes out with
        the median gap at 29 mm and nothing touching at all, so the placement
        is a fit, not a guess.
        """
        z, radius, coverage, tube = cls._base()
        reg = _stored()[1]["registrations"][key]
        shift = np.asarray(reg["shift_mm"], dtype=float)
        return cls(z + shift[2], radius, coverage, tube.shifted(shift), shift, key)

    @classmethod
    def for_tab(cls, tab: str) -> "Hardware":
        return cls.for_anatomic() if tab == "anatomic" else cls.for_model(tab)

    # --- what the fasteners ask -------------------------------------------

    @property
    def clamp_band(self) -> tuple[float, float]:
        """Heights a clamp's centre may sit at: tube, less an end margin."""
        h = cfg.CLAMP_HEIGHT / 2.0 + cfg.CLAMP_END_MARGIN
        return self.tube.z_lo + h, self.tube.z_hi - h

    def clearance(self, pts: np.ndarray) -> np.ndarray:
        """How far each point is outside the prosthesis, mm.  Negative inside.

        Takes points, not angles, because the scan's sections are stored about
        the knee axis while a cover is drawn about its own centre line: only
        the caller's point knows both.  Outside the measured stretch the answer
        is `inf` -- there is nothing there to hit -- and the caller is expected
        to keep out of such heights for other reasons (below is the shoe, above
        is the socket, and no cover reaches either).
        """
        pts = np.asarray(pts, dtype=float).reshape(-1, 3)
        local = pts - self.shift
        z = local[:, 2]
        rows = np.interp(z, self._z_scan, np.arange(len(self._z_scan)),
                         left=np.nan, right=np.nan)
        out = np.full(len(pts), np.inf)
        ok = np.isfinite(rows)
        if not np.any(ok):
            return out
        theta = np.arctan2(local[ok, 1], local[ok, 0]) % (2.0 * np.pi)
        rho = np.hypot(local[ok, 0], local[ok, 1])
        nbin = self.radius.shape[1]
        cols = theta / (2.0 * np.pi) * nbin
        i0 = np.clip(np.floor(rows[ok]).astype(int), 0, len(self._z_scan) - 2)
        t = rows[ok] - i0
        j0 = np.floor(cols).astype(int) % nbin
        j1 = (j0 + 1) % nbin
        s = cols - np.floor(cols)
        lo = self.radius[i0, j0] * (1 - s) + self.radius[i0, j1] * s
        hi = self.radius[i0 + 1, j0] * (1 - s) + self.radius[i0 + 1, j1] * s
        r = lo * (1 - t) + hi * t
        # A row the scan never covered reads NaN; treat it as nothing in the
        # way rather than as a wall, and let `coverage` be what warns.
        gap = rho - r
        gap[~np.isfinite(gap)] = np.inf
        out[ok] = gap
        return out

    def measured_at(self, z: float) -> float:
        """Share of the section the scan reached at this height, 0 to 1."""
        return float(np.interp(z - self.shift[2], self._z_scan, self.coverage,
                               left=0.0, right=0.0))

    def report(self) -> dict:
        _, report = _stored()
        return {
            "frame": self.name,
            "shift_mm": [round(float(x), 2) for x in self.shift],
            "tube_z": [round(self.tube.z_lo, 1), round(self.tube.z_hi, 1)],
            "tube_radius_mm": self.tube.radius,
            "tube_tilt_deg": self.tube.tilt_deg,
            "clamp_band": [round(x, 1) for x in self.clamp_band],
            "measured": report["pylon"],
            "scan_fit": report["registrations"].get(self.name),
        }
