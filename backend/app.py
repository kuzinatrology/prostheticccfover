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
import io
import logging
import pathlib
import time
from functools import lru_cache
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Response
from fastapi import Request as HttpRequest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import anatomic_api
from .export import FORMATS, preview_glb, write
from .generator import DRAFT, FINAL, Cover, audit, generate
from .motif import LIBRARY, MAX_BYTES, Motif, MotifError, held
from .params import CoverParams, schema
from .presets import as_json as presets_json
from .printer_profile import DEFAULT_PROFILE, PROFILES
from .accounts import authenticate, avatar, community_designs, create_user, delete_design, get_design, get_public_design, leaderboard, list_designs, my_rank, profile, rate_design, save_avatar, save_design, token, top_designers, top_designs, update_profile, user_from_token

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


class AccountRequest(BaseModel):
    email: str
    password: str
    nickname: str = ""


class DesignRequest(BaseModel):
    name: str = "Untitled design"
    mode: str = "transtibial"
    params: dict[str, Any]


class RatingRequest(BaseModel):
    score: int


class ProfileRequest(BaseModel):
    avatar_url: str = ""
    first_name: str = ""
    last_name: str = ""
    city: str = ""
    bio: str = ""
    website: str = ""
    social_link: str = ""


MAX_AVATAR_BYTES = 2 * 1024 * 1024


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


def current_user(request: HttpRequest) -> dict[str, Any]:
    user = user_from_token(request.cookies.get("cover_session"))
    if not user:
        raise HTTPException(401, "Sign in to use your account")
    return user


@app.get("/api/auth/me")
def auth_me(request: HttpRequest) -> dict[str, Any]:
    return {"user": user_from_token(request.cookies.get("cover_session"))}


@app.post("/api/auth/register")
def auth_register(req: AccountRequest, response: Response) -> dict[str, Any]:
    try:
        user = create_user(req.email, req.password, req.nickname)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    response.set_cookie("cover_session", token(int(user["id"])), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return {"user": user}


@app.post("/api/auth/login")
def auth_login(req: AccountRequest, response: Response) -> dict[str, Any]:
    user = authenticate(req.email, req.password)
    if not user:
        raise HTTPException(401, "Email or password is incorrect")
    response.set_cookie("cover_session", token(int(user["id"])), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return {"user": user}


@app.post("/api/auth/logout")
def auth_logout(response: Response) -> dict[str, bool]:
    response.delete_cookie("cover_session")
    return {"ok": True}


@app.get("/api/designs")
def designs(request: HttpRequest) -> list[dict[str, Any]]:
    return list_designs(int(current_user(request)["id"]))


@app.post("/api/designs")
def design_save(req: DesignRequest, request: HttpRequest) -> dict[str, Any]:
    user = current_user(request)
    if req.mode not in DESIGN_MODES:
        raise HTTPException(400, f"unknown cover {req.mode!r}")
    # `DESIGN_MODES` is built at the foot of this file, once every tab has been
    # imported; by the time a request arrives it is there.
    params = DESIGN_MODES[req.mode](req.params)
    motif_id = str(params.get("motif_id", ""))
    motif_data = LIBRARY.get(motif_id) if motif_id else None
    return save_design(int(user["id"]), req.name, params, motif_id, motif_data, req.mode)


@app.get("/api/designs/{design_id}")
def design_load(design_id: int, request: HttpRequest) -> dict[str, Any]:
    record = get_design(int(current_user(request)["id"]), design_id)
    if not record:
        raise HTTPException(404, "Design not found")
    design, motif_data = record
    if motif_data and design["params"].get("motif_id"):
        LIBRARY.add(motif_data)
    return design


@app.delete("/api/designs/{design_id}")
def design_delete(design_id: int, request: HttpRequest) -> dict[str, bool]:
    if not delete_design(int(current_user(request)["id"]), design_id):
        raise HTTPException(404, "Design not found")
    return {"ok": True}


@app.get("/api/community/designs")
def public_designs(request: HttpRequest, search: str = "") -> list[dict[str, Any]]:
    user = user_from_token(request.cookies.get("cover_session"))
    return community_designs(search, int(user["id"]) if user else None)


@app.get("/api/community/designs/{design_id}")
def public_design(design_id: int, request: HttpRequest) -> dict[str, Any]:
    viewer = user_from_token(request.cookies.get("cover_session"))
    record = get_public_design(design_id, int(viewer["id"]) if viewer else None)
    if not record:
        raise HTTPException(404, "Design not found")
    design, motif_data = record
    if motif_data and design["params"].get("motif_id"):
        LIBRARY.add(motif_data)
    return design


@app.post("/api/community/designs/{design_id}/rating")
def public_design_rate(design_id: int, req: RatingRequest, request: HttpRequest) -> dict[str, Any]:
    user = current_user(request)
    try:
        return rate_design(int(user["id"]), design_id, req.score)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/community/participants")
def public_participants() -> list[dict[str, Any]]:
    return leaderboard()


@app.get("/api/community/top-designers")
@app.get("/community/top-designers")
def public_top_designers(limit: int = 5) -> list[dict[str, Any]]:
    return top_designers(limit)


@app.get("/api/community/top-designs")
@app.get("/community/top-designs")
def public_top_designs(limit: int = 5) -> list[dict[str, Any]]:
    return top_designs(limit)


@app.get("/api/community/my-rank")
@app.get("/community/my-rank")
def public_my_rank(request: HttpRequest) -> dict[str, Any]:
    try:
        return my_rank(int(current_user(request)["id"]))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/profiles/{user_id}")
def public_profile(user_id: int, request: HttpRequest) -> dict[str, Any]:
    viewer = user_from_token(request.cookies.get("cover_session"))
    try:
        return profile(user_id, int(viewer["id"]) if viewer else None)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.put("/api/profile")
def profile_update(req: ProfileRequest, request: HttpRequest) -> dict[str, Any]:
    owner = current_user(request)
    try:
        return update_profile(int(owner["id"]), req.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/profile/avatar")
async def profile_avatar(request: HttpRequest) -> dict[str, Any]:
    owner = current_user(request)
    data = await request.body()
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if not data:
        raise HTTPException(400, "Choose an image first")
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(413, "Avatar must be 2 MB or smaller")
    if not content_type.startswith("image/"):
        raise HTTPException(415, "Avatar must be an image")
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception as exc:
        raise HTTPException(415, "That image could not be read") from exc
    try:
        return save_avatar(int(owner["id"]), data, content_type)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/profiles/{user_id}/avatar")
def profile_avatar_image(user_id: int) -> Response:
    stored = avatar(user_id)
    if not stored:
        raise HTTPException(404, "Avatar not found")
    data, mime = stored
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-cache"})


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


# --- the anatomical cover ----------------------------------------------
#
# A third tab, and a different kind of object: the shape is not drawn by
# sliders but measured off a scan of the prosthesis and off a human shank,
# so the handful of controls here are tolerances and the shape of the rim.


@app.get("/api/anat/schema")
def get_anat_schema() -> dict[str, Any]:
    return anatomic_api.schema()


def _anat(req: Request) -> tuple[Cover, dict[str, Any]]:
    built = anatomic_api.build(req.params, req.draft)
    return built["cover"], anatomic_api.stats(built, built["seconds"], req.draft)


@app.post("/api/anat/cover")
def post_anat_cover(req: Request) -> Response:
    cover, stats = _anat(req)
    return Response(
        content=preview_glb(cover),
        media_type="model/gltf-binary",
        headers={"X-Cover": quote(json.dumps(stats))},
    )


@app.post("/api/anat/download")
def post_anat_download(req: Request, fmt: str = "3mf") -> Response:
    if fmt not in FORMATS:
        raise HTTPException(400, f"unknown format {fmt!r}")
    req.draft = False
    cover, stats = _anat(req)
    faults = audit(cover)
    if faults:
        log.error("shipping a file that failed audit: %s", "; ".join(faults))
    if not stats["flexion"]["clears"]:
        log.error(
            "shipping an anatomical cover that jams at %.0f degrees",
            stats["flexion"]["max_angle"],
        )
    name = f"cover-anatomic-{cover.params.material}-{cover.mass_g:.0f}g.{fmt}"
    return Response(
        content=write(cover, fmt),
        media_type=FORMATS[fmt],
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# --- the modelled cover ------------------------------------------------
#
# A fourth tab, and the other way round from the rest: the shape is not drawn
# by sliders and not derived from a scan, but taken from `cover ready
# iteration 1.stl`, modelled in Rhino.  The service measures that file once
# into a radius over (angle, height); what the sliders do is give it a wall
# and a pattern.

from .iteration1 import export as it_export  # noqa: E402
from .iteration1.generator import DRAFT as IT_DRAFT  # noqa: E402
from .iteration1.generator import FINAL as IT_FINAL  # noqa: E402
from .iteration1.generator import IterCover, audit as it_audit  # noqa: E402
from .iteration1.generator import generate as it_generate  # noqa: E402
from .iteration1.params import IterParams, schema as it_schema  # noqa: E402
from .iteration1.presets import as_json as it_presets_json  # noqa: E402
from .iteration2 import export as it2_export  # noqa: E402
from .iteration2.generator import DRAFT as IT2_DRAFT  # noqa: E402
from .iteration2.generator import FINAL as IT2_FINAL  # noqa: E402
from .iteration2.generator import Iter2Cover, audit as it2_audit  # noqa: E402
from .iteration2.generator import generate as it2_generate  # noqa: E402
from .iteration2.params import Iter2Params, schema as it2_schema  # noqa: E402
from .iteration2.presets import as_json as it2_presets_json  # noqa: E402
from .prototype import export as pr_export  # noqa: E402
from .prototype.generator import DRAFT as PR_DRAFT  # noqa: E402
from .prototype.generator import FINAL as PR_FINAL  # noqa: E402
from .prototype.generator import ProtoCover, audit as pr_audit  # noqa: E402
from .prototype.generator import generate as pr_generate  # noqa: E402
from .prototype.params import ProtoParams, schema as pr_schema  # noqa: E402


@lru_cache(maxsize=8)
def _it_build(frozen: tuple, draft: bool) -> IterCover:
    params = IterParams(**dict(frozen))
    return it_generate(params, quality=IT_DRAFT if draft else IT_FINAL, profile=DEFAULT_PROFILE)


def _it_cover(req: Request) -> tuple[IterCover, float]:
    params = IterParams.from_dict(req.params)
    started = time.time()
    cover = _it_build(tuple(sorted(params.to_dict().items())), req.draft)
    return cover, time.time() - started


def _it_stats(cover: IterCover, seconds: float, draft: bool) -> dict[str, Any]:
    p = cover.params
    m = p.material_spec
    return {
        "mass_g": round(cover.mass_g, 1),
        "plain_mass_g": round(cover.plain_mass_g, 1),
        "saving_pct": round(cover.saving_pct),
        "delta_g": round(cover.mass_g - cover.plain_mass_g, 1),
        "holes": cover.holes,
        "triangles": len(cover.mesh.faces),
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
        "wall_mm": round(cover.wall, 2),
        "draft": draft,
        "seconds": round(seconds, 2),
    }


@app.get("/api/iter1/schema")
def get_it_schema() -> dict[str, Any]:
    out = it_schema(min_strut=DEFAULT_PROFILE.MIN_STRUT)
    out["profile"] = {
        "name": DEFAULT_PROFILE.name,
        "min_strut": DEFAULT_PROFILE.MIN_STRUT,
        "min_hole": DEFAULT_PROFILE.MIN_HOLE,
        "clearance": DEFAULT_PROFILE.CLEARANCE,
    }
    out["profiles"] = list(PROFILES)
    out["formats"] = ["3mf", "stl"]
    out["presets"] = it_presets_json()
    return out


@app.post("/api/iter1/cover")
def post_it_cover(req: Request) -> Response:
    cover, seconds = _it_cover(req)
    return Response(
        content=it_export.preview_glb(cover),
        media_type="model/gltf-binary",
        headers={"X-Cover": quote(json.dumps(_it_stats(cover, seconds, req.draft)))},
    )


@app.post("/api/iter1/download")
def post_it_download(req: Request, fmt: str = "3mf") -> Response:
    if fmt not in ("3mf", "stl"):
        raise HTTPException(400, f"unknown format {fmt!r}")
    req.draft = False
    cover, _ = _it_cover(req)
    faults = it_audit(cover)
    if faults:
        log.error("shipping a file that failed audit: %s", "; ".join(faults))
    name = f"cover-iteration1-{cover.params.material}-{cover.mass_g:.0f}g.{fmt}"
    return Response(
        content=it_export.write(cover, fmt),
        media_type=FORMATS[fmt],
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


LAST_BUILD = pathlib.Path(__file__).resolve().parents[1] / "out" / "last_build.json"
"""Where the settings of the most recent build of each tab are kept.

The interface holds its sliders in the open page and nowhere else, so once a
page is reloaded what someone had set is gone.  This is the only record of it,
and it is what lets a question like "scale what is on the screen" be answered
at all."""


def _recorded(tab: str) -> dict[str, Any]:
    """What that tab last built, if anything."""
    try:
        return json.loads(LAST_BUILD.read_text()).get(tab, {}).get("params", {})
    except (OSError, ValueError):
        return {}


def _record(tab: str, params: dict[str, Any]) -> None:
    try:
        LAST_BUILD.parent.mkdir(parents=True, exist_ok=True)
        seen = json.loads(LAST_BUILD.read_text()) if LAST_BUILD.exists() else {}
        seen[tab] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "params": params}
        LAST_BUILD.write_text(json.dumps(seen, indent=2, ensure_ascii=False))
    except OSError:
        pass  # A prototype's convenience must never fail a build.


# --- the second modelled cover, with its fasteners --------------------------
#
# A fifth tab.  The shape is another Rhino file; what it has that the fourth
# has not is the attachment: the cover is cut into a front and a back, the
# seam carries magnets, and two clamps hold it on the pylon.  So its answers
# are four bodies, and it borrows the transfemoral tab's way of shipping them:
# one file per body, a zip of all of them, and a GLB whose nodes are named so
# the viewer can pull the loose parts away from the cover.


@lru_cache(maxsize=8)
def _it2_build(frozen: tuple, draft: bool) -> Iter2Cover:
    params = Iter2Params(**dict(frozen))
    return it2_generate(params, quality=IT2_DRAFT if draft else IT2_FINAL,
                        profile=DEFAULT_PROFILE)


def _it2_cover(req: Request) -> tuple[Iter2Cover, float]:
    params = Iter2Params.from_dict(req.params)
    _record("iter2", params.to_dict())
    started = time.time()
    cover = _it2_build(tuple(sorted(params.to_dict().items())), req.draft)
    return cover, time.time() - started


def _it2_stats(cover: Iter2Cover, seconds: float, draft: bool) -> dict[str, Any]:
    p = cover.params
    m = p.material_spec
    return {
        "mass_g": round(cover.mass_g, 1),
        "plain_mass_g": round(cover.plain_mass_g, 1),
        "saving_pct": round(cover.saving_pct),
        "delta_g": round(cover.mass_g - cover.plain_mass_g, 1),
        "holes": cover.holes,
        "triangles": sum(len(m2.faces) for m2 in cover.bodies.values()),
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
        "wall_mm": round(cover.wall, 2),
        "bodies": {
            it2_export.LABELS[k]: round(v, 1) for k, v in cover.masses.items()
        },
        "draft": draft,
        "seconds": round(seconds, 2),
    }


@app.get("/api/iter2/schema")
def get_it2_schema() -> dict[str, Any]:
    out = it2_schema(min_strut=DEFAULT_PROFILE.MIN_STRUT)
    out["profile"] = {
        "name": DEFAULT_PROFILE.name,
        "min_strut": DEFAULT_PROFILE.MIN_STRUT,
        "min_hole": DEFAULT_PROFILE.MIN_HOLE,
        "clearance": DEFAULT_PROFILE.CLEARANCE,
    }
    out["profiles"] = list(PROFILES)
    out["formats"] = ["3mf", "stl"]
    out["presets"] = it2_presets_json()
    out["bodies"] = list(it2_export.LABELS)
    return out


@app.post("/api/iter2/cover")
def post_it2_cover(req: Request) -> Response:
    cover, seconds = _it2_cover(req)
    return Response(
        content=it2_export.preview_glb(cover),
        media_type="model/gltf-binary",
        headers={"X-Cover": quote(json.dumps(_it2_stats(cover, seconds, req.draft)))},
    )


@app.post("/api/iter2/download")
def post_it2_download(req: Request, fmt: str = "3mf", body: str = "all") -> Response:
    if fmt not in ("3mf", "stl"):
        raise HTTPException(400, f"unknown format {fmt!r}")
    req.draft = False
    cover, _ = _it2_cover(req)
    faults = it2_audit(cover)
    if faults:
        log.error("shipping files that failed audit: %s", "; ".join(faults))
    stem = f"cover-iteration2-{cover.params.material}-{cover.mass_g:.0f}g"
    if body == "all":
        data = it2_export.bundle(cover, fmt)
        media, name = "application/zip", f"{stem}.zip"
    elif body in cover.bodies:
        data = (it2_export.body_3mf(cover, body) if fmt == "3mf"
                else it2_export.body_stl(cover, body))
        media, name = FORMATS[fmt], f"{stem}-{it2_export.LABELS[body]}.{fmt}"
    else:
        raise HTTPException(400, f"unknown body {body!r}")
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# --- the prototype ----------------------------------------------------------
#
# A sixth tab, and not a design: it is whatever Iteration 2 is showing, built
# small enough to print and hold.  Everything with a real counterpart is left
# alone -- the wall, the land, the magnet seats, every clamp -- and the clamps
# stand beside the cover rather than inside it, where at this size nothing
# could see them.


@lru_cache(maxsize=4)
def _pr_build(frozen: tuple, draft: bool) -> ProtoCover:
    params = ProtoParams(**dict(frozen))
    return pr_generate(params, quality=PR_DRAFT if draft else PR_FINAL,
                       profile=DEFAULT_PROFILE)


def _pr_cover(req: Request) -> tuple[ProtoCover, float]:
    params = ProtoParams.from_dict(req.params)
    _record("proto", params.to_dict())
    started = time.time()
    cover = _pr_build(tuple(sorted(params.to_dict().items())), req.draft)
    return cover, time.time() - started


@app.get("/api/proto/schema")
def get_pr_schema() -> dict[str, Any]:
    out = pr_schema(min_strut=DEFAULT_PROFILE.MIN_STRUT)
    out["profile"] = {
        "name": DEFAULT_PROFILE.name,
        "min_strut": DEFAULT_PROFILE.MIN_STRUT,
        "min_hole": DEFAULT_PROFILE.MIN_HOLE,
        "clearance": DEFAULT_PROFILE.CLEARANCE,
    }
    out["profiles"] = list(PROFILES)
    out["formats"] = ["3mf", "stl"]
    out["presets"] = it2_presets_json()
    out["bodies"] = list(pr_export.LABELS)
    # The prototype is not a design of its own: it opens on whatever Iteration
    # 2 last built, which is the whole point of it.  Its own two handles keep
    # their defaults; everything else comes from there.
    seen = _recorded("iter2")
    if seen:
        own = {"scale", "beside_gap"}
        out["defaults"] = {
            k: (v if k in own else seen.get(k, v)) for k, v in out["defaults"].items()
        }
        out["from"] = "the settings Iteration 2 last built"
    return out


@app.post("/api/proto/cover")
def post_pr_cover(req: Request) -> Response:
    cover, seconds = _pr_cover(req)
    stats = _it2_stats(cover, seconds, req.draft)
    stats["scale"] = cover.scale
    return Response(
        content=pr_export.preview_glb(cover),
        media_type="model/gltf-binary",
        headers={"X-Cover": quote(json.dumps(stats))},
    )


@app.post("/api/proto/download")
def post_pr_download(req: Request, fmt: str = "3mf", body: str = "all") -> Response:
    if fmt not in ("3mf", "stl"):
        raise HTTPException(400, f"unknown format {fmt!r}")
    req.draft = False
    cover, _ = _pr_cover(req)
    faults = pr_audit(cover)
    if faults:
        log.error("shipping files that failed audit: %s", "; ".join(faults))
    stem = f"prototype-{cover.scale:.2f}-{cover.params.material}-{cover.mass_g:.0f}g"
    if body == "all":
        data, media, name = pr_export.bundle(cover, fmt), "application/zip", f"{stem}.zip"
    elif body in cover.bodies:
        data = (pr_export.body_3mf(cover, body) if fmt == "3mf"
                else pr_export.body_stl(cover, body))
        media, name = FORMATS[fmt], f"{stem}-{pr_export.LABELS[body]}.{fmt}"
    else:
        raise HTTPException(400, f"unknown body {body!r}")
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# --- the same cover, shaped by the reference renders ------------------------
#
# A fourth tab. ref_2 is a straight side view, so the top boundary of its
# silhouette is the rim curve itself and the notch can be measured instead of
# guessed; the girth profile is the mean of both renders. What the renders
# cannot say is where the cover sits on the leg, and that turns out to matter:
# the traced notch is narrow, and a narrow notch will not clear the thigh at
# deep flexion however deep it is cut. Sitting the cover lower does, with the
# reference's own shape untouched.


@app.get("/api/ref/schema")
def get_ref_schema() -> dict[str, Any]:
    return anatomic_api.schema(from_reference=True)


def _ref(req: Request) -> tuple[Cover, dict[str, Any]]:
    built = anatomic_api.build(req.params, req.draft, from_reference=True)
    return built["cover"], anatomic_api.stats(built, built["seconds"], req.draft)


@app.post("/api/ref/cover")
def post_ref_cover(req: Request) -> Response:
    cover, stats = _ref(req)
    return Response(
        content=preview_glb(cover),
        media_type="model/gltf-binary",
        headers={"X-Cover": quote(json.dumps(stats))},
    )


@app.post("/api/ref/download")
def post_ref_download(req: Request, fmt: str = "3mf") -> Response:
    if fmt not in FORMATS:
        raise HTTPException(400, f"unknown format {fmt!r}")
    req.draft = False
    cover, stats = _ref(req)
    faults = audit(cover)
    if faults:
        log.error("shipping a file that failed audit: %s", "; ".join(faults))
    if not stats["flexion"]["clears"]:
        log.error(
            "shipping a reference cover that jams at %.0f degrees",
            stats["flexion"]["max_angle"],
        )
    name = f"cover-reference-{cover.params.material}-{cover.mass_g:.0f}g.{fmt}"
    return Response(
        content=write(cover, fmt),
        media_type=FORMATS[fmt],
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# --- a saved design remembers which tab drew it ----------------------------
#
# The tabs do not share a parameter object: the transtibial cover knows nothing
# of a pylon diameter, and Iteration 2 knows nothing of a calf bulge.  Reading
# every saved design back through `CoverParams` would therefore quietly throw
# away everything but the transtibial fields and hand back that tab's defaults.
# So a design carries the tab it came from, and is read back through that tab's
# own class -- which also keeps a design somebody else saved from arriving as
# values this tab has no range for.


def _by_schema(raw: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """For the two tabs measured off a scan, which have no class of their own:
    whatever keys their schema declares, and their own defaults for the rest."""
    return {**defaults, **{k: v for k, v in raw.items() if k in defaults}}


DESIGN_MODES: dict[str, Any] = {
    "transtibial": lambda raw: CoverParams.from_dict(raw).to_dict(),
    "transfemoral": lambda raw: TFParams.from_dict(raw).to_dict(),
    "anatomic": lambda raw: _by_schema(raw, anatomic_api.schema()["defaults"]),
    "iter1": lambda raw: IterParams.from_dict(raw).to_dict(),
    "iter2": lambda raw: Iter2Params.from_dict(raw).to_dict(),
    "proto": lambda raw: ProtoParams.from_dict(raw).to_dict(),
    "reference": lambda raw: _by_schema(raw, anatomic_api.schema(from_reference=True)["defaults"]),
}


# Mounted last: the API routes above claim their paths first, and everything
# else falls through to the built page. Absent until `npm run build` has run.
if BUILT.is_dir():
    @app.get("/workshop", include_in_schema=False)
    def workshop_page() -> FileResponse:
        return FileResponse(BUILT / "index.html")

    @app.get("/profile/{user_id}", include_in_schema=False)
    def profile_page(user_id: int) -> FileResponse:
        return FileResponse(BUILT / "index.html")

    app.mount("/", StaticFiles(directory=BUILT, html=True), name="app")
