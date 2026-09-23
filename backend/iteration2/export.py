"""Files out of the second modelled cover.

Four bodies, printed separately, so a print file is per body: a 3MF each, or
all of them in one zip with their masses.  The viewer gets one GLB with the
bodies as named nodes, so it can tint the halves apart and pull the clamp
straps away from the cover on request.
"""

from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import trimesh

from ..export import paint_3mf
from .generator import BODY_NAMES, Iter2Cover, audit

LABELS = {
    "front": "front-half",
    "back": "back-half",
    "lower_clamp_front": "lower-clamp-front",
    "lower_clamp_back": "lower-clamp-back",
    "upper_clamp_front": "upper-clamp-front",
    "upper_clamp_back": "upper-clamp-back",
}

PREVIEW_TOLERANCE = 0.3
"""mm the screen mesh may stray from the printed one."""


def body_3mf(cover: Iter2Cover, name: str) -> bytes:
    data = cover.bodies[name].export(file_type="3mf")
    data = data if isinstance(data, bytes) else data.encode()
    spec = cover.params.material_spec
    return paint_3mf(data, spec.hex, f"{spec.label} {spec.polymer}")


def body_stl(cover: Iter2Cover, name: str) -> bytes:
    data = cover.bodies[name].export(file_type="stl")
    return data if isinstance(data, bytes) else data.encode()


def bundle(cover: Iter2Cover, fmt: str = "3mf") -> bytes:
    audit(cover)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in BODY_NAMES:
            if name not in cover.bodies:
                continue
            z.writestr(f"{LABELS[name]}.{fmt}",
                       body_3mf(cover, name) if fmt == "3mf" else body_stl(cover, name))
        z.writestr("masses.json", json.dumps(summary(cover), indent=2, ensure_ascii=False))
    return out.getvalue()


def summary(cover: Iter2Cover) -> dict:
    return {
        "material": cover.params.material_spec.label,
        "density_g_cm3": cover.params.material_spec.density,
        "bodies": {
            LABELS[k]: {"volume_mm3": round(cover.volumes[k], 1),
                        "mass_g": round(cover.masses[k], 1)}
            for k in BODY_NAMES if k in cover.bodies
        },
        "total_mass_g": round(cover.mass_g, 1),
        "notes": cover.notes,
    }


def write(cover: Iter2Cover, fmt: str) -> bytes:
    return bundle(cover, fmt)


SIMPLIFY_ABOVE = 20_000
"""Faces a body needs before the screen mesh is simplified at all.

Simplification is for the halves, which carry a quarter of a million triangles
of pattern.  A clamp carries two thousand, and at PREVIEW_TOLERANCE a 4.6 mm
bolt hole comes back with seven sides -- so the screen showed hex sockets on
parts that are bored round.  Nothing is saved by touching them."""


def preview_glb(cover: Iter2Cover, crease_deg: float = 35.0) -> bytes:
    """One node per body, named after it, simplified for the screen."""
    from .. import mesh_build as mb

    scene = trimesh.Scene()
    for name in BODY_NAMES:
        if name in cover.bodies:
            body = cover.bodies[name]
            if len(body.faces) > SIMPLIFY_ABOVE:
                body = mb.from_manifold(mb.to_manifold(body).simplify(PREVIEW_TOLERANCE))
            mesh = trimesh.graph.smooth_shade(body, angle=np.radians(crease_deg))
            scene.add_geometry(mesh, node_name=name, geom_name=name)
    buf = scene.export(file_type="glb")
    return buf if isinstance(buf, bytes) else bytes(buf)
