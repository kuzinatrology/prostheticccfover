"""The second modelled cover's parameters: the first tab's, plus the fasteners.

The shape controls are the modelled tab's unchanged -- a file is the shape, so
there is nothing to draw -- and what is added is the attachment, whose ranges
follow the transfemoral tab's because they describe the same hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..fasteners import config as fc
from ..params import MATERIALS, Range
from ..printer_profile import DEFAULT_PROFILE
from ..iteration1 import config as cfg
from ..iteration1.params import ITER_ENUMS, ITER_RANGES, IterParams
from ..iteration1.surface import _data

MODEL = "iteration2"

MOUNT_RANGES: dict[str, Range] = {
    "magnet_diameter": Range(3.0, 12.0, 0.5, "mm"),
    "magnet_height": Range(1.0, 6.0, 0.5, "mm"),
    "magnet_count": Range(0.0, 8.0, 1.0, ""),
    "bolt_diameter": Range(3.0, 5.0, 1.0, "mm"),
    "clamp_count": Range(0.0, 2.0, 1.0, ""),
    "seam_curve": Range(0.0, 40.0, 1.0, "mm"),
    "flexion": Range(60.0, 130.0, 5.0, "deg"),
    "leaf_count": Range(1.0, 7.0, 1.0, ""),
    "leaf_size": Range(30.0, 110.0, 1.0, "mm"),
    "leaf_tilt": Range(0.0, 45.0, 1.0, "deg"),
    "lower_clamp_z": Range(-400.0, 500.0, 1.0, "mm"),
    "upper_clamp_z": Range(-400.0, 500.0, 1.0, "mm"),
}
"""`bolt_diameter` steps in whole millimetres because only M3, M4 and M5 have
an insert and a nut in the tables the lugs are sized from."""

MOUNT_ENUMS = {"nut_kind": list(fc.NUT_KINDS)}

ITER2_RANGES: dict[str, Range] = {**ITER_RANGES, **MOUNT_RANGES}
ITER2_ENUMS = {**ITER_ENUMS, **MOUNT_ENUMS}

UNPLACED = -1e9
"""A clamp height nobody has set.  The kit then spreads the clamps over the
tube itself, which is what a fresh tab should show."""


@dataclass
class Iter2Params(IterParams):
    model: str = MODEL
    magnet_diameter: float = 4.0
    magnet_height: float = 3.0
    magnet_count: float = 5.0
    bolt_diameter: float = 4.0
    nut_kind: str = "heat_set"
    seam_curve: float = fc.SEAM_CURVE
    flexion: float = fc.FLEXION_ANGLE
    # Leaves on the back, the same feature the other tabs carry: large drawn
    # panels instead of cells, down the back midline.
    back_leaves: bool = False
    leaf_count: float = 3.0
    leaf_size: float = 70.0
    leaf_tilt: float = 20.0
    clamp_count: float = 2.0
    lower_clamp_z: float = UNPLACED
    upper_clamp_z: float = UNPLACED

    @property
    def magnets(self) -> int:
        return int(round(self.magnet_count))

    @property
    def clamps(self) -> int:
        return int(round(self.clamp_count))

    def clamped(self) -> "Iter2Params":
        out = super().clamped()
        data = out.__dict__
        data["model"] = MODEL
        for key, rng in MOUNT_RANGES.items():
            value = float(data[key])
            # A clamp height nobody has touched stays untouched: clamping it
            # into the range would pin it to the bottom of the tube, and the
            # kit's own spread is the better default.
            if key.endswith("_clamp_z") and value <= UNPLACED / 2.0:
                continue
            data[key] = float(min(max(value, rng.lo), rng.hi))
        data["back_leaves"] = bool(data["back_leaves"])
        if data["nut_kind"] not in fc.NUT_KINDS:
            data["nut_kind"] = fc.NUT_KINDS[0]
        return out


def schema(min_strut: float | None = None) -> dict[str, Any]:
    defaults = Iter2Params().clamped()
    ranges = {
        k: {"lo": r.lo, "hi": r.hi, "step": r.step, "unit": r.unit, "scale": r.scale}
        for k, r in ITER2_RANGES.items()
    }
    if min_strut is not None:
        ranges["strut_width"]["lo"] = min_strut
        defaults.strut_width = max(defaults.strut_width, min_strut)
    return {
        "ranges": ranges,
        "enums": {k: list(v) for k, v in ITER2_ENUMS.items()},
        "defaults": defaults.to_dict(),
        "materials": [
            {"key": m.key, "label": m.label, "hex": m.hex, "polymer": m.polymer,
             "density": m.density}
            for m in MATERIALS
        ],
        "model": _data(MODEL).meta,
    }
