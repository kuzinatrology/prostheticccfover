"""File output.

3MF first: STL drops topology and cannot promise a manifold comes back on
reimport. The cover's colour is written into the 3MF as a base material, which
is the only part of the finish that survives into a print file at all.
"""

from __future__ import annotations

import io
import re
import zipfile

import numpy as np
import trimesh

from .generator import Cover, audit

FORMATS = {"3mf": "model/3mf", "stl": "model/stl", "glb": "model/gltf-binary"}

MODEL_PART = "3D/3dmodel.model"


def write(cover: Cover, fmt: str) -> bytes:
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}")
    audit(cover)
    data = cover.mesh.export(file_type=fmt)
    data = data if isinstance(data, bytes) else data.encode()
    if fmt == "3mf":
        spec = cover.params.material_spec
        data = paint_3mf(data, spec.hex, f"{spec.label} {spec.polymer}")
    return data


def paint_3mf(data: bytes, colour: str, name: str) -> bytes:
    """Give the model a single base material carrying its display colour.

    A gradient or a faceted shading is a property of the preview, not of the
    object, so only the one flat colour is written. Anything that cannot be
    edited safely is left exactly as it was found.
    """
    source = zipfile.ZipFile(io.BytesIO(data))
    model = source.read(MODEL_PART).decode("utf-8")

    material = (
        f'<basematerials id="900">'
        f'<base name="{_escape(name)}" displaycolor="{_display(colour)}"/>'
        f"</basematerials>"
    )
    if "<resources>" in model:
        model = model.replace("<resources>", "<resources>" + material, 1)
    else:
        return data
    # Point the first object at the material; objects carry no pid otherwise.
    model, count = re.subn(r"(<object\b(?![^>]*\bpid=))", r'\1 pid="900" pindex="0"', model, count=1)
    if not count:
        return data

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            payload = model.encode("utf-8") if item.filename == MODEL_PART else source.read(item)
            target.writestr(item, payload)
    return out.getvalue()


def _display(colour: str) -> str:
    value = colour.lstrip("#").upper()
    return f"#{value}FF" if len(value) == 6 else f"#{value}"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def preview_glb(cover: Cover, crease_deg: float = 35.0) -> bytes:
    """Viewer mesh: creases kept sharp, the rest of the surface smooth.

    Splitting the vertices along the creases here is what lets the viewer
    average normals without rounding off the edge of every hole.
    """
    mesh = trimesh.graph.smooth_shade(cover.mesh, angle=np.radians(crease_deg))
    buf = trimesh.Scene(mesh).export(file_type="glb")
    return buf if isinstance(buf, bytes) else bytes(buf)
