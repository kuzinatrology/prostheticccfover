"""Starting points for a transfemoral cover.

The same six the transtibial tab offers, carried over by key, with every value
that has no meaning on a scanned leg left out. They are named for what they do
to the surface, which is the same on either cover.
"""

from __future__ import annotations

from typing import Any

from ..presets import PRESETS
from .params import TFParams

_FIELDS = set(TFParams().to_dict())


def tf_values(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if k in _FIELDS}


def params(key: str) -> TFParams:
    preset = next(p for p in PRESETS if p.key == key)
    data = TFParams().to_dict()
    data.update(tf_values(preset.values))
    return TFParams.from_dict(data)


def as_json() -> list[dict[str, Any]]:
    return [
        {"key": p.key, "label": p.label, "note": p.note, "values": tf_values(p.values)}
        for p in PRESETS
    ]
