"""Files out of a cover built on the Rhino model.

One body, so one file: a 3MF carrying the cover's colour, or an STL when a
tool insists on one.  The viewer gets the same body simplified, because the
screen cannot show a tenth of a millimetre and the print file keeps every
triangle.
"""

from __future__ import annotations

import numpy as np
import trimesh

from ..export import paint_3mf
from .generator import IterCover, audit

PREVIEW_TOLERANCE = 0.3
"""mm the screen mesh may stray from the printed one."""


def write(cover: IterCover, fmt: str) -> bytes:
    audit(cover)
    data = cover.mesh.export(file_type=fmt)
    data = data if isinstance(data, bytes) else data.encode()
    if fmt == "3mf":
        spec = cover.params.material_spec
        data = paint_3mf(data, spec.hex, f"{spec.label} {spec.polymer}")
    return data


def preview_glb(cover: IterCover, crease_deg: float = 35.0) -> bytes:
    from .. import mesh_build as mb

    light = mb.from_manifold(mb.to_manifold(cover.mesh).simplify(PREVIEW_TOLERANCE))
    mesh = trimesh.graph.smooth_shade(light, angle=np.radians(crease_deg))
    buf = trimesh.Scene(mesh).export(file_type="glb")
    return buf if isinstance(buf, bytes) else bytes(buf)
