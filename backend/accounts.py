"""Small persistent account store for the configurator.

This intentionally uses only the Python standard library.  Accounts are
identified by email and the browser receives a signed, HttpOnly session cookie.
Saved designs include the source motif bytes so an image-based design survives
restarts as well as ordinary parameter designs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "configurator.sqlite3"
SESSION_SECRET = os.environ.get("COVER_SESSION_SECRET", "development-only-change-me").encode()


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
      CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        nickname TEXT NOT NULL DEFAULT '',
        avatar_data BLOB,
        avatar_mime TEXT NOT NULL DEFAULT '',
        avatar_url TEXT NOT NULL DEFAULT '',
        first_name TEXT NOT NULL DEFAULT '',
        last_name TEXT NOT NULL DEFAULT '',
        city TEXT NOT NULL DEFAULT '',
        bio TEXT NOT NULL DEFAULT '',
        website TEXT NOT NULL DEFAULT '',
        social_link TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS designs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'transtibial',
        params TEXT NOT NULL,
        motif_id TEXT NOT NULL DEFAULT '',
        motif_data BLOB,
        created_at INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS ratings (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        design_id INTEGER NOT NULL REFERENCES designs(id) ON DELETE CASCADE,
        score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5),
        created_at INTEGER NOT NULL,
        PRIMARY KEY(user_id, design_id)
      );
    """)
    # Existing installations predate nicknames.  Keep those accounts and give
    # them a stable, readable default based on the email local-part.
    columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
    if "nickname" not in columns:
        db.execute("ALTER TABLE users ADD COLUMN nickname TEXT NOT NULL DEFAULT ''")
    for column, definition in (("avatar_data", "BLOB"), ("avatar_mime", "TEXT NOT NULL DEFAULT ''"), ("avatar_url", "TEXT NOT NULL DEFAULT ''"), ("first_name", "TEXT NOT NULL DEFAULT ''"), ("last_name", "TEXT NOT NULL DEFAULT ''"), ("city", "TEXT NOT NULL DEFAULT ''"), ("bio", "TEXT NOT NULL DEFAULT ''"), ("website", "TEXT NOT NULL DEFAULT ''"), ("social_link", "TEXT NOT NULL DEFAULT ''")):
        if column not in columns:
            db.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
    design_columns = {row[1] for row in db.execute("PRAGMA table_info(designs)")}
    if "mode" not in design_columns:
        db.execute("ALTER TABLE designs ADD COLUMN mode TEXT NOT NULL DEFAULT 'transtibial'")
    for row in db.execute("SELECT id,email FROM users WHERE nickname='' OR nickname IS NULL").fetchall():
        db.execute("UPDATE users SET nickname=? WHERE id=?", (_available_nickname(db, row["email"].split("@", 1)[0], row["id"]), row["id"]))
    db.commit()
    return db


def _available_nickname(db: sqlite3.Connection, value: str, own_id: int | None = None) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]", "", value)[:20] or "designer"
    candidate = base
    number = 2
    while db.execute("SELECT 1 FROM users WHERE nickname=? AND id!=?", (candidate, own_id or -1)).fetchone():
        suffix = f"-{number}"
        candidate = f"{base[:24-len(suffix)]}{suffix}"
        number += 1
    return candidate


def _password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 210_000)
    return base64.urlsafe_b64encode(salt + digest).decode()


def check_password(password: str, stored: str) -> bool:
    raw = base64.urlsafe_b64decode(stored.encode())
    return hmac.compare_digest(_password(password, raw[:16]), stored)


def create_user(email: str, password: str, nickname: str) -> dict[str, Any]:
    email = email.strip().lower()
    if len(email) > 200 or "@" not in email:
        raise ValueError("Enter a valid email")
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    db = _db()
    nickname = nickname.strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{2,24}", nickname):
        raise ValueError("Nickname must be 2–24 characters: letters, numbers, _ or -")
    if db.execute("SELECT 1 FROM users WHERE nickname=? COLLATE NOCASE", (nickname,)).fetchone():
        raise ValueError("That nickname is already taken")
    try:
        cur = db.execute("INSERT INTO users(email,nickname,password_hash,created_at) VALUES(?,?,?,?)", (email, nickname, _password(password), int(time.time())))
        db.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("An account with that email already exists") from exc
    return {"id": cur.lastrowid, "email": email, "nickname": nickname}


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    db = _db()
    row = db.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email.strip(),)).fetchone()
    if not row or not check_password(password, row["password_hash"]):
        return None
    return {"id": row["id"], "email": row["email"], "nickname": row["nickname"]}


def token(user_id: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"id": user_id, "exp": int(time.time()) + 60 * 60 * 24 * 30}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def user_from_token(value: str | None) -> dict[str, Any] | None:
    if not value or "." not in value:
        return None
    payload, signature = value.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data["exp"] < time.time():
            return None
        db = _db()
        row = db.execute("SELECT id,email,nickname FROM users WHERE id=?", (int(data["id"]),)).fetchone()
        return dict(row) if row else None
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def save_design(user_id: int, name: str, params: dict[str, Any], motif_id: str, motif_data: bytes | None, mode: str = "transtibial") -> dict[str, Any]:
    name = name.strip()[:100] or "Untitled design"
    db = _db()
    cur = db.execute("INSERT INTO designs(user_id,name,mode,params,motif_id,motif_data,created_at) VALUES(?,?,?,?,?,?,?)", (user_id, name, mode, json.dumps(params), motif_id, motif_data, int(time.time())))
    db.commit()
    return {"id": cur.lastrowid, "name": name, "mode": mode, "params": params, "created_at": int(time.time())}


def list_designs(user_id: int) -> list[dict[str, Any]]:
    db = _db()
    return [{"id": r["id"], "name": r["name"], "mode": r["mode"], "params": json.loads(r["params"]), "created_at": r["created_at"], "rating": _rating(db, r["id"])} for r in db.execute("SELECT id,name,mode,params,created_at FROM designs WHERE user_id=? ORDER BY created_at DESC", (user_id,))]


def _rating(db: sqlite3.Connection, design_id: int, user_id: int | None = None) -> dict[str, Any]:
    row = db.execute("SELECT ROUND(AVG(score), 1) AS average, COUNT(*) AS count FROM ratings WHERE design_id=?", (design_id,)).fetchone()
    vote = db.execute("SELECT score FROM ratings WHERE design_id=? AND user_id=?", (design_id, user_id)).fetchone() if user_id is not None else None
    mine = vote["score"] if vote is not None else None
    return {"average": float(row["average"] or 0), "count": int(row["count"]), "mine": mine}


def community_designs(search: str = "", user_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
    db = _db()
    search = f"%{search.strip()}%"
    rows = db.execute("""
      SELECT d.id,d.user_id,d.name,d.mode,d.created_at,u.nickname
      FROM designs d JOIN users u ON u.id=d.user_id
      WHERE d.name LIKE ? COLLATE NOCASE
      ORDER BY d.created_at DESC LIMIT ?
    """, (search, min(max(limit, 1), 200))).fetchall()
    return [{"id": r["id"], "user_id": r["user_id"], "name": r["name"], "mode": r["mode"], "nickname": r["nickname"], "created_at": r["created_at"], "rating": _rating(db, r["id"], user_id)} for r in rows]


def get_public_design(design_id: int, user_id: int | None = None) -> tuple[dict[str, Any], bytes | None] | None:
    db = _db()
    r = db.execute("SELECT d.*,u.nickname FROM designs d JOIN users u ON u.id=d.user_id WHERE d.id=?", (design_id,)).fetchone()
    if not r:
        return None
    design = {"id": r["id"], "user_id": r["user_id"], "name": r["name"], "mode": r["mode"], "nickname": r["nickname"], "params": json.loads(r["params"]), "created_at": r["created_at"], "rating": _rating(db, design_id, user_id)}
    return design, r["motif_data"]


def rate_design(user_id: int, design_id: int, score: int) -> dict[str, Any]:
    if score < 0 or score > 5:
        raise ValueError("Rating must be between 1 and 5, or 0 to remove it")
    db = _db()
    design = db.execute("SELECT user_id FROM designs WHERE id=?", (design_id,)).fetchone()
    if not design:
        raise LookupError("Design not found")
    if int(design["user_id"]) == user_id:
        raise PermissionError("You cannot rate your own design")
    if score == 0:
        db.execute("DELETE FROM ratings WHERE user_id=? AND design_id=?", (user_id, design_id))
    else:
        db.execute("INSERT INTO ratings(user_id,design_id,score,created_at) VALUES(?,?,?,?) ON CONFLICT(user_id,design_id) DO UPDATE SET score=excluded.score,created_at=excluded.created_at", (user_id, design_id, score, int(time.time())))
    db.commit()
    return _rating(db, design_id, user_id)


def _ranked_designer_rows(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute("""
      SELECT u.id,u.nickname,
        CASE WHEN u.avatar_data IS NOT NULL THEN '/api/profiles/' || u.id || '/avatar' ELSE u.avatar_url END AS avatar_url,
        ROUND(AVG(r.score),1) AS average,
        COUNT(r.score) AS ratings,
        (SELECT COUNT(*) FROM designs all_designs WHERE all_designs.user_id=u.id) AS designs
      FROM users u
      JOIN designs d ON d.user_id=u.id
      JOIN ratings r ON r.design_id=d.id
      GROUP BY u.id
      HAVING COUNT(r.score) > 0
      ORDER BY average DESC, ratings DESC, u.nickname COLLATE NOCASE
    """).fetchall()
    return [
        {
            "id": r["id"],
            "nickname": r["nickname"],
            "avatar_url": r["avatar_url"] or "",
            "average": float(r["average"] or 0),
            "ratings": int(r["ratings"]),
            "designs": int(r["designs"]),
        }
        for r in rows
    ]


def top_designers(limit: int = 5) -> list[dict[str, Any]]:
    db = _db()
    return _ranked_designer_rows(db)[:min(max(limit, 1), 100)]


def top_designs(limit: int = 5) -> list[dict[str, Any]]:
    db = _db()
    rows = db.execute("""
      SELECT d.id,d.user_id,d.name,d.mode,u.nickname,
        CASE WHEN u.avatar_data IS NOT NULL THEN '/api/profiles/' || u.id || '/avatar' ELSE u.avatar_url END AS avatar_url,
        ROUND(AVG(r.score),1) AS average, COUNT(r.score) AS ratings
      FROM designs d
      JOIN users u ON u.id=d.user_id
      JOIN ratings r ON r.design_id=d.id
      GROUP BY d.id
      HAVING COUNT(r.score) > 0
      ORDER BY average DESC, ratings DESC, d.name COLLATE NOCASE
      LIMIT ?
    """, (min(max(limit, 1), 100),)).fetchall()
    return [
        {
            "id": r["id"],
            "user_id": r["user_id"],
            "name": r["name"],
            "mode": r["mode"],
            "nickname": r["nickname"],
            "avatar_url": r["avatar_url"] or "",
            "average": float(r["average"] or 0),
            "ratings": int(r["ratings"]),
        }
        for r in rows
    ]


def my_rank(user_id: int) -> dict[str, Any]:
    db = _db()
    ranked = _ranked_designer_rows(db)
    position = next((index for index, row in enumerate(ranked) if row["id"] == user_id), None)
    if position is not None:
        found = {**ranked[position], "rank": position + 1}
        return {"rank": found["rank"], "designer": found}
    person = db.execute("""
      SELECT u.id,u.nickname,
        CASE WHEN u.avatar_data IS NOT NULL THEN '/api/profiles/' || u.id || '/avatar' ELSE u.avatar_url END AS avatar_url,
        (SELECT COUNT(*) FROM designs d WHERE d.user_id=u.id) AS designs,
        (SELECT COUNT(*) FROM ratings r JOIN designs d ON d.id=r.design_id WHERE d.user_id=u.id) AS ratings
      FROM users u WHERE u.id=?
    """, (user_id,)).fetchone()
    if not person:
        raise LookupError("User not found")
    return {
        "rank": None,
        "designer": {
            "id": person["id"],
            "nickname": person["nickname"],
            "avatar_url": person["avatar_url"] or "",
            "average": 0.0,
            "ratings": int(person["ratings"]),
            "designs": int(person["designs"]),
        },
    }


def leaderboard(limit: int = 20) -> list[dict[str, Any]]:
    return top_designers(limit)


PROFILE_FIELDS = ("avatar_url", "first_name", "last_name", "city", "bio", "website", "social_link")


def _clean_profile(values: dict[str, Any]) -> dict[str, str]:
    limits = {
        "avatar_url": 500,
        "first_name": 60,
        "last_name": 60,
        "city": 100,
        "bio": 1000,
        "website": 500,
        "social_link": 500,
    }
    clean = {key: str(values.get(key, "")).strip()[:limits[key]] for key in PROFILE_FIELDS}
    for key in ("avatar_url", "website", "social_link"):
        if clean[key] and not clean[key].lower().startswith(("http://", "https://")):
            raise ValueError(f"{key.replace('_', ' ').title()} must start with http:// or https://")
    return clean


def update_profile(user_id: int, values: dict[str, Any]) -> dict[str, Any]:
    clean = _clean_profile(values)
    db = _db()
    assignments = ",".join(f"{key}=?" for key in PROFILE_FIELDS)
    db.execute(f"UPDATE users SET {assignments} WHERE id=?", (*clean.values(), user_id))
    db.commit()
    return profile(user_id, user_id)


def save_avatar(user_id: int, data: bytes, mime: str) -> dict[str, Any]:
    db = _db()
    if not db.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
        raise LookupError("User not found")
    db.execute("UPDATE users SET avatar_data=?,avatar_mime=? WHERE id=?", (data, mime, user_id))
    db.commit()
    return profile(user_id, user_id)


def avatar(user_id: int) -> tuple[bytes, str] | None:
    db = _db()
    row = db.execute("SELECT avatar_data,avatar_mime FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or row["avatar_data"] is None:
        return None
    return bytes(row["avatar_data"]), row["avatar_mime"] or "application/octet-stream"


def profile(user_id: int, viewer_id: int | None = None) -> dict[str, Any]:
    db = _db()
    person = db.execute(
        "SELECT id,nickname,avatar_data,avatar_url,first_name,last_name,city,bio,website,social_link FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    if not person:
        raise LookupError("User not found")
    public_user = dict(person)
    public_user.pop("avatar_data", None)
    public_user["avatar_url"] = f"/api/profiles/{user_id}/avatar" if person["avatar_data"] is not None else person["avatar_url"]
    designs = db.execute(
        "SELECT id,name,mode,created_at FROM designs WHERE user_id=? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    design_items = [
        {
            "id": row["id"],
            "name": row["name"],
            "mode": row["mode"],
            "created_at": row["created_at"],
            "nickname": person["nickname"],
            "rating": _rating(db, row["id"], viewer_id),
        }
        for row in designs
    ]
    activity = db.execute("""
      SELECT day,COUNT(*) AS count FROM (
        SELECT date(created_at,'unixepoch') AS day FROM designs WHERE user_id=?
        UNION ALL
        SELECT date(created_at,'unixepoch') AS day FROM ratings WHERE user_id=?
      ) WHERE day IS NOT NULL GROUP BY day ORDER BY day
    """, (user_id, user_id)).fetchall()
    rating = db.execute("""
      SELECT ROUND(AVG(r.score),1) AS average,COUNT(r.score) AS ratings
      FROM designs d LEFT JOIN ratings r ON r.design_id=d.id WHERE d.user_id=?
    """, (user_id,)).fetchone()
    return {
        "user": public_user,
        "designs": design_items,
        "activity": [{"date": row["day"], "count": int(row["count"])} for row in activity],
        "stats": {
            "designs": len(design_items),
            "average": float(rating["average"] or 0),
            "ratings": int(rating["ratings"] or 0),
        },
        "is_owner": viewer_id == user_id,
    }


def get_design(user_id: int, design_id: int) -> tuple[dict[str, Any], bytes | None] | None:
    db = _db()
    r = db.execute("SELECT * FROM designs WHERE id=? AND user_id=?", (design_id, user_id)).fetchone()
    if not r:
        return None
    return {"id": r["id"], "name": r["name"], "mode": r["mode"], "params": json.loads(r["params"]), "created_at": r["created_at"]}, r["motif_data"]


def delete_design(user_id: int, design_id: int) -> bool:
    db = _db()
    cur = db.execute("DELETE FROM designs WHERE id=? AND user_id=?", (design_id, user_id))
    db.commit()
    return cur.rowcount > 0
