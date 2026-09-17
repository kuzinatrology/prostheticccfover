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
    params = CoverParams.from_dict(req.params).to_dict()
    motif_id = str(params.get("motif_id", ""))
    motif_data = LIBRARY.get(motif_id) if motif_id else None
    return save_design(int(user["id"]), req.name, params, motif_id, motif_data)


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
