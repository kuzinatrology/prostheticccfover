"""The prototype's parameters: the Iteration 2 tab's, plus how small."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..iteration2.params import ITER2_ENUMS, ITER2_RANGES, Iter2Params, schema as it2_schema
from ..params import Range

PROTO_RANGES: dict[str, Range] = {
    **ITER2_RANGES,
    "scale": Range(0.3, 1.0, 0.05, ""),
    "beside_gap": Range(0.0, 80.0, 5.0, "mm"),
}

PROTO_ENUMS = dict(ITER2_ENUMS)


@dataclass
class ProtoParams(Iter2Params):
    scale: float = 0.6
    """How big the printed model is against the real cover."""

    beside_gap: float = 25.0
    """Clear space between the cover and the clamps standing next to it."""

    def clamped(self) -> "ProtoParams":
        out = super().clamped()
        data = out.__dict__
        for key in ("scale", "beside_gap"):
            r = PROTO_RANGES[key]
            data[key] = float(min(max(float(data[key]), r.lo), r.hi))
        return out


def schema(min_strut: float | None = None) -> dict[str, Any]:
    out = it2_schema(min_strut)
    defaults = ProtoParams().clamped()
    out["ranges"] = {
        k: {"lo": r.lo, "hi": r.hi, "step": r.step, "unit": r.unit, "scale": r.scale}
        for k, r in PROTO_RANGES.items()
    }
    if min_strut is not None:
        out["ranges"]["strut_width"]["lo"] = min_strut
        defaults.strut_width = max(defaults.strut_width, min_strut)
    out["defaults"] = defaults.to_dict()
    return out
