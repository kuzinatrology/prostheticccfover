"""HTTP service.

One endpoint builds a cover and hands back the viewer mesh; another hands back
a print file. Both take the same parameter object, so what you look at and
what you print cannot drift apart.

A third pair takes an uploaded picture and hands back the silhouette it was
read as. The picture stays in memory and the design carries only its digest,
so the parameter object is still the whole of what a cover is.
"""

from __future__ import annotations

import json
import logging
import pathlib
import time
from functools import lru_cache
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Response
from fastapi import Request as HttpRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .export import FORMATS, preview_glb, write
from .generator import DRAFT, FINAL, Cover, audit, generate
from .motif import LIBRARY, MAX_BYTES, Motif, MotifError, held
from .params import CoverParams, schema
from .presets import as_json as presets_json
from .printer_profile import DEFAULT_PROFILE, PROFILES

log = logging.getLogger("cover.api")

BUILT = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "dist"

app = FastAPI(title="Prosthetic cover configurator", version="0.1")

# The built front end is served from this same process, so the browser only
# ever talks to one origin. Cross-origin is only needed while `npm run dev`
# holds the page on its own port, so that is all this allows.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"http://(\d{1,3}\.){3}\d{1,3}:5173",
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Cover"],
)


class Request(BaseModel):
    params: dict[str, Any]
    draft: bool = False


class MotifRequest(BaseModel):
    """The three controls that change how a held picture is read."""

    motif_id: str = ""
    threshold_bias: float = 0.0
    motif_invert: bool = False
    motif_smoothing: float = 0.35


@lru_cache(maxsize=16)
def _build(frozen: tuple, draft: bool) -> Cover:
    params = CoverParams(**dict(frozen))
    return generate(params, quality=DRAFT if draft else FINAL, profile=DEFAULT_PROFILE)


def _cover(req: Request) -> tuple[Cover, float]:
    params = CoverParams.from_dict(req.params)
    started = time.time()
    cover = _build(tuple(sorted(params.to_dict().items())), req.draft)
    return cover, time.time() - started


def _stats(cover: Cover, seconds: float, draft: bool) -> dict[str, Any]:
    p = cover.params
    m = p.material_spec
    return {
        "mass_g": round(cover.mass_g, 1),
        "plain_mass_g": round(cover.plain_mass_g, 1),
        # Positive when the pattern took material away, negative when relief
        # put it on. The panel picks its wording from the sign.
        "saving_pct": round(cover.saving_pct),
        "delta_g": round(cover.mass_g - cover.plain_mass_g, 1),
        "holes": cover.holes,
        "triangles": len(cover.mesh.faces),
        "max_wall_thickness": round(cover.max_wall, 2),
        "max_relief_depth": round(cover.max_relief, 2),
        "operation": p.operation,
        "cuts_through": cover.cuts_through,
        "notes": cover.notes,
        "material": {"key": m.key, "label": m.label, "hex": m.hex, "polymer": m.polymer},
        "finish": {
            "mode": p.finish,
            "colour_a": m.hex,
            "colour_b": p.colour_b_spec.hex,
            "facet_scale": p.facet_scale,
        },
        "draft": draft,
        "seconds": round(seconds, 2),
    }


@app.get("/api/schema")
def get_schema() -> dict[str, Any]:
    out = schema(min_strut=DEFAULT_PROFILE.MIN_STRUT)
    out["profile"] = {
        "name": DEFAULT_PROFILE.name,
        "min_strut": DEFAULT_PROFILE.MIN_STRUT,
        "min_hole": DEFAULT_PROFILE.MIN_HOLE,
        "clearance": DEFAULT_PROFILE.CLEARANCE,
    }
    out["profiles"] = list(PROFILES)
    out["formats"] = list(FORMATS)
    out["presets"] = presets_json()
    return out


@app.post("/api/cover")
def post_cover(req: Request) -> Response:
    """The viewer mesh, with everything the panel needs in a header."""
    cover, seconds = _cover(req)
    body = preview_glb(cover)
    stats = _stats(cover, seconds, req.draft)
    return Response(
        content=body,
        media_type="model/gltf-binary",
        headers={"X-Cover": quote(json.dumps(stats))},
    )


def _silhouette(motif: Motif) -> dict[str, Any]:
    """What the panel needs to draw the shape it is about to cut.

    The outlines go back as path data in the unit square rather than as a
    picture, so the preview is the same geometry the cover will carry and not
    a second rendering of the file that could disagree with it.
    """
    return {
        "id": motif.digest,
        "short": motif.digest[:6].upper(),
        "paths": motif.paths(),
        "shapes": len(motif.solid.geoms),
        "found": motif.found,
        "notes": motif.notes,
    }


@app.post("/api/motif")
async def post_motif(request: HttpRequest) -> dict[str, Any]:
    """Take a picture, keep it in memory, hand back the silhouette read from it."""
    data = await request.body()
    if not data:
        raise HTTPException(400, "no file in the request")
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "file is larger than 8 MB")
    digest = LIBRARY.add(bytes(data))
    try:
        motif = held(digest, 0.0, False, CoverParams().motif_smoothing)
    except MotifError as exc:
        raise HTTPException(415, str(exc)) from exc
    return _silhouette(motif)


@app.post("/api/motif/preview")
def post_motif_preview(req: MotifRequest) -> dict[str, Any]:
    """The same picture read again, at a different threshold or smoothing."""
    p = CoverParams.from_dict({"hole_shape": "image", **req.model_dump()})
    if not p.motif_id or LIBRARY.get(p.motif_id) is None:
        raise HTTPException(404, "that picture is not being held any more")
    try:
        motif = held(p.motif_id, p.threshold_bias, p.motif_invert, p.motif_smoothing)
    except MotifError as exc:
        raise HTTPException(415, str(exc)) from exc
    return _silhouette(motif)


@app.post("/api/download")
def post_download(req: Request, fmt: str = "3mf") -> Response:
    if fmt not in FORMATS:
        raise HTTPException(400, f"unknown format {fmt!r}")
    cover, _ = _cover(req)
    faults = audit(cover)
    if faults:
        # The user still gets their file; the bug is ours to chase.
        log.error("shipping a file that failed audit: %s", "; ".join(faults))
    body = write(cover, fmt)
    name = f"cover-{cover.params.material}-{cover.mass_g:.0f}g.{fmt}"
    return Response(
        content=body,
        media_type=FORMATS[fmt],
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# --- transfemoral: the scanned leg, its own tab -----------------------------

from .transfemoral import export as tf_export  # noqa: E402
from .transfemoral.generator import DRAFT as TF_DRAFT  # noqa: E402
from .transfemoral.generator import FINAL as TF_FINAL  # noqa: E402
from .transfemoral.generator import TFCover, generate as tf_generate  # noqa: E402
from .transfemoral.generator import audit as tf_audit  # noqa: E402
from .transfemoral.params import TFParams, schema as tf_schema  # noqa: E402
from .transfemoral.presets import as_json as tf_presets_json  # noqa: E402


@lru_cache(maxsize=8)
def _tf_build(frozen: tuple, draft: bool) -> TFCover:
    params = TFParams(**dict(frozen))
    return tf_generate(params, quality=TF_DRAFT if draft else TF_FINAL, profile=DEFAULT_PROFILE)


def _tf_cover(req: Request) -> tuple[TFCover, float]:
    params = TFParams.from_dict(req.params)
    started = time.time()
    cover = _tf_build(tuple(sorted(params.to_dict().items())), req.draft)
    return cover, time.time() - started


def _tf_stats(cover: TFCover, seconds: float, draft: bool) -> dict[str, Any]:
    p = cover.params
    m = p.material_spec
    return {
        "mass_g": round(cover.mass_g, 1),
        "plain_mass_g": round(cover.plain_mass_g, 1),
        "saving_pct": round(cover.saving_pct),
        "delta_g": round(cover.mass_g - cover.plain_mass_g, 1),
        "bodies": {k: round(v, 1) for k, v in cover.masses.items()},
        "holes": cover.holes,
        "triangles": sum(len(b.faces) for b in cover.bodies.values()),
        "max_wall_thickness": round(cover.max_wall, 2),
        "max_relief_depth": round(cover.max_relief, 2),
        "limits": {k: [round(lo, 2), round(hi, 2)] for k, (lo, hi) in cover.limits.items()},
        "operation": p.operation,
        "cuts_through": p.cuts_through,
        "notes": cover.notes,
        "material": {"key": m.key, "label": m.label, "hex": m.hex, "polymer": m.polymer},
        "finish": {
            "mode": p.finish,
            "colour_a": m.hex,
            "colour_b": p.colour_b_spec.hex,
            "facet_scale": p.facet_scale,
        },
        "explode_mm": tf_export_explode(),
        "draft": draft,
        "seconds": round(seconds, 2),
    }


def tf_export_explode() -> float:
    from .transfemoral import config as tf_config

    return tf_config.EXPLODE_MM


@app.get("/api/tf/schema")
def get_tf_schema() -> dict[str, Any]:
    out = tf_schema(min_strut=DEFAULT_PROFILE.MIN_STRUT)
    out["profile"] = {
        "name": DEFAULT_PROFILE.name,
        "min_strut": DEFAULT_PROFILE.MIN_STRUT,
        "min_hole": DEFAULT_PROFILE.MIN_HOLE,
        "clearance": DEFAULT_PROFILE.CLEARANCE,
    }
    out["profiles"] = list(PROFILES)
    out["formats"] = ["3mf", "stl"]
    out["presets"] = tf_presets_json()
    out["bodies"] = list(tf_export.LABELS)
    return out


@app.post("/api/tf/cover")
def post_tf_cover(req: Request) -> Response:
    cover, seconds = _tf_cover(req)
    body = tf_export.preview_glb(cover)
    stats = _tf_stats(cover, seconds, req.draft)
    return Response(
        content=body,
        media_type="model/gltf-binary",
        headers={"X-Cover": quote(json.dumps(stats))},
    )


@app.post("/api/tf/download")
def post_tf_download(req: Request, fmt: str = "3mf", body: str = "all") -> Response:
    if fmt not in ("3mf", "stl"):
        raise HTTPException(400, f"unknown format {fmt!r}")
    cover, _ = _tf_cover(req)
    faults = tf_audit(cover)
    if faults:
        log.error("shipping transfemoral files that failed audit: %s", "; ".join(faults))
    stem = f"transfemoral-{cover.params.material}-{cover.mass_g:.0f}g"
    if body == "all":
        data = tf_export.bundle(cover, fmt)
        media, name = "application/zip", f"{stem}.zip"
    elif body in cover.bodies:
        data = tf_export.body_3mf(cover, body) if fmt == "3mf" else tf_export.body_stl(cover, body)
        media, name = FORMATS[fmt], f"{stem}-{tf_export.LABELS[body]}.{fmt}"
    else:
        raise HTTPException(400, f"unknown body {body!r}")
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# Mounted last: the API routes above claim their paths first, and everything
# else falls through to the built page. Absent until `npm run build` has run.
if BUILT.is_dir():
    app.mount("/", StaticFiles(directory=BUILT, html=True), name="app")
