"""Files out of the prototype: one per body, or all of them in a zip.

The same shipping as the Iteration 2 tab -- these are the same kinds of part,
and one of them is a cover half either way.
"""

from __future__ import annotations

from ..iteration2.export import (  # noqa: F401
    LABELS as _LABELS,
    PREVIEW_TOLERANCE,
    body_3mf,
    body_stl,
    preview_glb as _preview_glb,
    summary as _summary,
)

LABELS = dict(_LABELS)


def bundle(cover, fmt: str = "3mf") -> bytes:
    import io
    import json
    import zipfile

    from .generator import BODY_NAMES

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in BODY_NAMES:
            if name not in cover.bodies:
                continue
            z.writestr(f"{LABELS[name]}.{fmt}",
                       body_3mf(cover, name) if fmt == "3mf" else body_stl(cover, name))
        z.writestr("masses.json", json.dumps(summary(cover), indent=2, ensure_ascii=False))
    return out.getvalue()


def summary(cover) -> dict:
    out = _summary(cover)
    out["scale"] = cover.scale
    out["note"] = (
        "The cover is at this fraction of full size; wall, land, magnet seats "
        "and every clamp are left at the size they are really printed at."
    )
    return out


SIMPLIFY_ABOVE = 20_000
"""Faces a body needs before the screen mesh is simplified at all.

Simplification is for the halves, which carry a quarter of a million triangles
of pattern.  A clamp carries two thousand, and at PREVIEW_TOLERANCE a 4.6 mm
bolt hole comes back with seven sides -- so the screen showed hex sockets on
parts that are bored round.  Nothing is saved by touching them."""


def preview_glb(cover, crease_deg: float = 35.0) -> bytes:
    import numpy as np
    import trimesh

    from .. import mesh_build as mb
    from .generator import BODY_NAMES

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


def write(cover, fmt: str) -> bytes:
    return bundle(cover, fmt)
