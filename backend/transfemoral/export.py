"""Files out of a transfemoral cover.

Four bodies, printed separately, so a print file is per body: a 3MF each, or
all four in one zip. The viewer gets one GLB with the bodies as named nodes,
so it can tint the halves apart and pull the back parts away on request.
"""

from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import trimesh

from ..export import paint_3mf
from .generator import BODY_NAMES, TFCover, audit

LABELS = {
    "front": "front-half",
    "back": "back-half",
    "lower_clamp_back": "lower-clamp-back",
    "upper_clamp_back": "upper-clamp-back",
}


def body_3mf(cover: TFCover, name: str) -> bytes:
    mesh = cover.bodies[name]
    data = mesh.export(file_type="3mf")
    data = data if isinstance(data, bytes) else data.encode()
    spec = cover.params.material_spec
    return paint_3mf(data, spec.hex, f"{spec.label} {spec.polymer}")


def body_stl(cover: TFCover, name: str) -> bytes:
    data = cover.bodies[name].export(file_type="stl")
    return data if isinstance(data, bytes) else data.encode()


def bundle(cover: TFCover, fmt: str = "3mf") -> bytes:
    """Every body in one zip, with the masses beside them."""
    audit(cover)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in BODY_NAMES:
            if name not in cover.bodies:
                continue
            payload = body_3mf(cover, name) if fmt == "3mf" else body_stl(cover, name)
            z.writestr(f"{LABELS[name]}.{fmt}", payload)
        z.writestr("masses.json", json.dumps(summary(cover), indent=2, ensure_ascii=False))
    return out.getvalue()


def summary(cover: TFCover) -> dict:
    return {
        "material": cover.params.material_spec.label,
        "density_g_cm3": cover.params.material_spec.density,
        "bodies": {
            LABELS[k]: {"volume_mm3": round(cover.volumes[k], 1), "mass_g": round(cover.masses[k], 1)}
            for k in BODY_NAMES
            if k in cover.bodies
        },
        "total_mass_g": round(cover.mass_g, 1),
        "notes": cover.notes,
    }


PREVIEW_TOLERANCE = 0.3
"""mm the screen mesh may stray from the printed one. A tenth of the triangles
for a deviation no one sees at any zoom the viewer allows; the print file keeps
every triangle."""


def preview_glb(cover: TFCover, crease_deg: float = 35.0) -> bytes:
    """One node per body, named after it, simplified for the screen."""
    from .. import mesh_build as mb

    scene = trimesh.Scene()
    for name in BODY_NAMES:
        if name in cover.bodies:
            light = mb.from_manifold(mb.to_manifold(cover.bodies[name]).simplify(PREVIEW_TOLERANCE))
            mesh = trimesh.graph.smooth_shade(light, angle=np.radians(crease_deg))
            scene.add_geometry(mesh, node_name=name, geom_name=name)
    buf = scene.export(file_type="glb")
    return buf if isinstance(buf, bytes) else bytes(buf)
