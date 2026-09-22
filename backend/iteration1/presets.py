"""Starting points for a cover built on the Rhino model.

The same six the other tabs offer, carried over by key, with every value that
has no meaning here left out.  They are named for what they do to the surface,
and that is the same whether the surface was drawn by sliders, measured off a
scan or modelled in Rhino — so a preset moves the pattern and leaves the shape
of the file exactly where the shape sliders put it.
"""

from __future__ import annotations

from typing import Any

from ..presets import PRESETS
from .params import IterParams

_FIELDS = set(IterParams().to_dict())


def iter_values(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if k in _FIELDS}


def params(key: str) -> IterParams:
    preset = next(p for p in PRESETS if p.key == key)
    data = IterParams().to_dict()
    data.update(iter_values(preset.values))
    return IterParams.from_dict(data)


def as_json() -> list[dict[str, Any]]:
    return [
        {"key": p.key, "label": p.label, "note": p.note, "values": iter_values(p.values)}
        for p in PRESETS
    ]
