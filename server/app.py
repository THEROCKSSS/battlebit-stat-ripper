"""BattleBit profile site - accounts, uploads, and public stat pages.

Run locally:
    python server/app.py
Then open http://127.0.0.1:8099
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import db
import media
import site_helpers as H
import socials
import steam_openid
import steam_profiles
from rate_limit import LIMITER

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("BBR_SERVER_DATA", BASE_DIR / "data"))
DATABASE = DATA_DIR / "profiles.db"
SECRET_FILE = DATA_DIR / "secret_key"
MEDIA_DIR = DATA_DIR / "uploads"
DOWNLOAD_PATH = Path(
    os.environ.get("BBR_DOWNLOAD", BASE_DIR.parent / "dist" / "BattleBitStatRipper.exe")
)
ZIP_PATH = Path(
    os.environ.get(
        "BBR_DOWNLOAD_ZIP",
        BASE_DIR.parent / "dist" / "BattleBitStatRipper-windows-x64.zip",
    )
)
RIPPER_VERSION = "0.3.0"
PUBLIC_URL = os.environ.get("BBR_PUBLIC_URL", "").rstrip("/")
MAX_PROFILE_BYTES = 2 * 1024 * 1024
UPLOAD_LIMIT = (10, 3600)  # 10 captures per account per hour
PLAYER_ADD_LIMIT = (6, 3600)  # 6 Steam lookups per IP per hour



def _secret_key() -> str:
    env = os.environ.get("BBR_SECRET_KEY")
    if env:
        return env
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SECRET_FILE.exists():
        return SECRET_FILE.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    SECRET_FILE.write_text(key, encoding="utf-8")
    return key


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_secret_key(),
    DATABASE=str(DATABASE),
    BBR_MEDIA_DIR=str(MEDIA_DIR),
    BBR_RIPPER_VERSION=RIPPER_VERSION,
    MAX_CONTENT_LENGTH=media.MAX_IMAGE_BYTES + 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
app.jinja_env.trim_blocks = True
app.jinja_env.lstrip_blocks = True
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)

if os.environ.get("BBR_HTTPS") == "1":
    app.config["SESSION_COOKIE_SECURE"] = True


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = db.connect(app.config["DATABASE"])
    return g.db


@app.teardown_appcontext
def close_db(_exc: BaseException | None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db() -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    conn = db.connect(app.config["DATABASE"])
    conn.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Auth / CSRF
# ---------------------------------------------------------------------------
def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view: Callable):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Sign in first.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def csrf_token() -> str:
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def verify_csrf() -> None:
    supplied = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
    expected = session.get("_csrf", "")
    if not supplied or not expected or not secrets.compare_digest(supplied, expected):
        abort(400, "Invalid or expired form token. Reload the page and try again.")


# Small in-memory sign-in throttle.  Good enough for a single-process v1; move
# to Redis if the site is ever run behind multiple workers.
_LOGIN_FAILS: dict[str, list[float]] = defaultdict(list)
LOGIN_LIMIT = 8
LOGIN_WINDOW_SECONDS = 600


def _too_many_attempts(key: str) -> bool:
    now = time.time()
    attempts = [t for t in _LOGIN_FAILS.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    _LOGIN_FAILS[key] = attempts
    return len(attempts) >= LOGIN_LIMIT


def _record_attempt(key: str) -> None:
    _LOGIN_FAILS[key].append(time.time())


def _clear_attempts(key: str) -> None:
    _LOGIN_FAILS.pop(key, None)


@app.context_processor
def inject_globals() -> dict[str, Any]:
    return {
        "current_user": current_user(),
        "csrf_token": csrf_token,
        "year": 2026,
        "profile_name": H.profile_name,
        "social_links": socials.links,
        "ripper_version": RIPPER_VERSION,
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
@app.template_filter("num")
def fmt_num(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


@app.template_filter("pct")
def fmt_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


@app.template_filter("hours")
def fmt_hours(value: Any) -> str:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return "—"
    return f"{seconds / 3600:,.1f} h"


@app.template_filter("date")
def fmt_date(value: Any) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y")
    except ValueError:
        return str(value)


# ---------------------------------------------------------------------------
# Profile validation
# ---------------------------------------------------------------------------
STEAM_ID_RE = re.compile(r"^\d{16,18}$")
REQUIRED_STATS = ("kills", "deaths", "rank", "total_score", "playtime_seconds")


def validate_profile(doc: Any) -> tuple[str, str]:
    if not isinstance(doc, dict):
        raise ValueError("The file is not a JSON object.")
    if doc.get("schema") != "bbr-profile/1":
        raise ValueError("This is not a BattleBit Stat Ripper profile (schema mismatch).")
    player = doc.get("player")
    if not isinstance(player, dict):
        raise ValueError("Profile has no player block.")
    steam_id = str(player.get("steam_id", "")).strip()
    if not STEAM_ID_RE.match(steam_id):
        raise ValueError("Profile has an invalid Steam ID.")
    progress = doc.get("progress")
    if not isinstance(progress, dict):
        raise ValueError("Profile has no progress block.")
    for key in REQUIRED_STATS:
        if not isinstance(progress.get(key), (int, float)):
            raise ValueError(f"Profile is missing the numeric field '{key}'.")
    persona = str(player.get("persona_name") or player.get("username") or "").strip()
    if not persona:
        persona = f"Player {steam_id[-4:]}"
    if len(persona) > 64:
        persona = persona[:64]
    return steam_id, persona


def _load_profile(steam_id: str):
    return get_db().execute(
        "SELECT * FROM profiles WHERE steam_id = ?", (steam_id,)
    ).fetchone()


def _profile_data(row) -> dict[str, Any]:
    try:
        return json.loads(row["data"])
    except (TypeError, ValueError):
        return {}


def _can_view(row, user) -> bool:
    if row["visibility"] == "public":
        return True
    return bool(user) and user["id"] == row["user_id"]


def _load_player(steam_id: str):
    return get_db().execute(
        "SELECT * FROM players WHERE steam_id = ?", (steam_id,)
    ).fetchone()


def _public_url(endpoint: str, **values: Any) -> str:
    """Absolute URL for links Steam must be able to read back."""
    path = url_for(endpoint, **values)
    if PUBLIC_URL:
        return PUBLIC_URL + path
    return url_for(endpoint, _external=True, **values)


def _unique_username(conn, base: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", base or "")[:20] or "player"
    if len(cleaned) < 3:
        cleaned = f"player{cleaned}"
    candidate = cleaned
    suffix = 1
    while conn.execute(
        "SELECT 1 FROM users WHERE username = ?", (candidate,)
    ).fetchone():
        suffix += 1
        candidate = f"{cleaned}{suffix}"
    return candidate


def _get_or_create_steam_user(conn, steam_id: str, persona: str):
    user = conn.execute(
        "SELECT * FROM users WHERE steam_id = ?", (steam_id,)
    ).fetchone()
    if user:
        return user
    username = _unique_username(conn, persona)
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, steam_id, created_at) VALUES (?, ?, ?, ?)",
        (username, generate_password_hash(secrets.token_urlsafe(32)), steam_id, utc_now()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()


def _sign_in_session(user) -> None:
    session.clear()
    session["user_id"] = user["id"]
    session["_csrf"] = secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM profiles WHERE visibility = 'public' ORDER BY updated_at DESC LIMIT 6"
    ).fetchall()
    recent = []
    for row in rows:
        data = _profile_data(row)
        clan = H.profile_clan(conn, row["user_id"])
        recent.append(
            {
                "row": row,
                "persona": H.profile_name(row),
                "avatar": row["avatar_path"],
                "clan": clan,
                "rank": data.get("progress", {}).get("rank", 0),
                "kills": data.get("progress", {}).get("kills", 0),
                "kd": data.get("derived", {}).get("kd", 0),
                "hours": data.get("derived", {}).get("hours_played", 0),
            }
        )
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM profiles WHERE visibility = 'public'"
    ).fetchone()["n"]
    total_clans = conn.execute("SELECT COUNT(*) AS n FROM clans").fetchone()["n"]
    clan_preview = H.clan_directory(conn, "", "members")[:3]
    return render_template(
        "index.html",
        recent=recent,
        total=total,
        total_clans=total_clans,
        clan_preview=clan_preview,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("me"))
    if request.method == "POST":
        verify_csrf()
        allowed, retry = LIMITER.hit(f"register:{request.remote_addr or '?'}", 5, 3600)
        if not allowed:
            return (
                render_template("429.html", retry=retry, scope="register"),
                429,
                {"Retry-After": str(retry)},
            )
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if not re.match(r"^[A-Za-z0-9_]{3,24}$", username):
            flash("Username must be 3-24 characters: letters, numbers, underscore.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        else:
            conn = get_db()
            try:
                cur = conn.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    (username, generate_password_hash(password), utc_now()),
                )
                conn.commit()
            except Exception:
                flash("That username is already taken.", "error")
            else:
                session.clear()
                session["user_id"] = cur.lastrowid
                session["_csrf"] = secrets.token_urlsafe(32)
                flash("Account created. Upload your profile next.", "ok")
                return redirect(url_for("upload"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("me"))
    if request.method == "POST":
        verify_csrf()
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        allowed, retry = LIMITER.hit(f"login:{request.remote_addr or '?'}", 30, 600)
        if not allowed:
            return (
                render_template("429.html", retry=retry, scope="login"),
                429,
                {"Retry-After": str(retry)},
            )
        attempt_key = f"{request.remote_addr or '?'}|{username.lower()}"
        if _too_many_attempts(attempt_key):
            flash("Too many sign-in attempts. Wait a few minutes and try again.", "error")
            return render_template("login.html"), 429
        row = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row and check_password_hash(row["password_hash"], password):
            _clear_attempts(attempt_key)
            session.clear()
            session["user_id"] = row["id"]
            session["_csrf"] = secrets.token_urlsafe(32)
            flash(f"Welcome back, {row['username']}.", "ok")
            target = request.args.get("next")
            if not target or not target.startswith("/"):
                target = url_for("me")
            return redirect(target)
        _record_attempt(attempt_key)
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@app.get("/auth/steam")
def steam_login():
    allowed, retry = LIMITER.hit(f"steam:{request.remote_addr or '?'}", 20, 600)
    if not allowed:
        return (
            render_template("429.html", retry=retry, scope="steam"),
            429,
            {"Retry-After": str(retry)},
        )
    state = secrets.token_urlsafe(24)
    session["steam_state"] = state
    target = request.args.get("next", "")
    if target.startswith("/"):
        session["steam_next"] = target
    return_to = _public_url("steam_callback", state=state)
    parsed = urllib.parse.urlparse(return_to)
    realm = f"{parsed.scheme}://{parsed.netloc}"
    return redirect(steam_openid.build_login_url(return_to, realm))


@app.get("/auth/steam/callback")
def steam_callback():
    expected = session.pop("steam_state", None)
    state = request.args.get("state", "")
    if not expected or not secrets.compare_digest(state, expected):
        abort(400, "Expired Steam sign-in. Start again.")
    steam_id = steam_openid.verify(request.args.to_dict())
    if not steam_id:
        flash("Steam did not confirm that sign-in. Try again.", "error")
        return redirect(url_for("login"))
    conn = get_db()
    try:
        player = steam_profiles.refresh_player(conn, steam_id, MEDIA_DIR)
    except steam_profiles.SteamError as exc:
        player = _load_player(steam_id)
        if player is None:
            flash(f"Signed in to Steam, but the profile could not be read: {exc}", "error")
            return redirect(url_for("login"))
    user = _get_or_create_steam_user(conn, steam_id, player["persona_name"])
    # Steam proves who owns this Steam ID, so hand any existing capture record
    # for it to this account (a local password account may have uploaded it).
    conn.execute(
        "UPDATE profiles SET user_id = ? WHERE steam_id = ? AND user_id != ?",
        (user["id"], steam_id, user["id"]),
    )
    conn.commit()
    target = session.get("steam_next") or url_for("me")
    if not str(target).startswith("/"):
        target = url_for("me")
    _sign_in_session(user)
    flash(f"Signed in through Steam as {player['persona_name']}.", "ok")
    return redirect(target)


@app.post("/logout")
def logout():
    verify_csrf()
    session.clear()
    flash("Signed out.", "ok")
    return redirect(url_for("index"))


@app.get("/upload")
@login_required
def upload():
    return render_template("upload.html")


@app.post("/upload")
@login_required
def upload_post():
    verify_csrf()
    user = current_user()
    allowed, retry = LIMITER.hit(f"upload:{user['id']}", *UPLOAD_LIMIT)
    if not allowed:
        return (
            render_template("429.html", retry=retry, scope="upload"),
            429,
            {"Retry-After": str(retry)},
        )
    raw: bytes | None = None
    file = request.files.get("file")
    if file and file.filename:
        raw = file.read(MAX_PROFILE_BYTES + 1)
    else:
        pasted = request.form.get("json") or ""
        if pasted.strip():
            raw = pasted.encode("utf-8")

    if not raw:
        flash("Choose a .bbrstats file or paste the profile JSON.", "error")
        return redirect(url_for("upload"))
    if len(raw) > MAX_PROFILE_BYTES:
        flash("That profile is larger than 2 MB.", "error")
        return redirect(url_for("upload"))
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
        steam_id, persona = validate_profile(doc)
    except (UnicodeDecodeError, json.JSONDecodeError):
        flash("That file is not valid UTF-8 JSON.", "error")
        return redirect(url_for("upload"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("upload"))

    conn = get_db()
    existing = _load_profile(steam_id)
    if existing and existing["user_id"] != user["id"]:
        flash(
            "That Steam profile is already linked to another account. "
            "Ask the owner to unlink it first.",
            "error",
        )
        return redirect(url_for("upload"))

    visibility = request.form.get("visibility", "public")
    if visibility not in ("public", "private"):
        visibility = "public"
    captured = doc.get("captured_at") or utc_now()
    conn.execute(
        """
        INSERT INTO profiles (steam_id, user_id, persona_name, captured_at, updated_at, visibility, data)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(steam_id) DO UPDATE SET
            persona_name = excluded.persona_name,
            captured_at = excluded.captured_at,
            updated_at = excluded.updated_at,
            visibility = excluded.visibility,
            data = excluded.data
        """,
        (
            steam_id,
            user["id"],
            persona,
            captured,
            utc_now(),
            visibility,
            json.dumps(doc, ensure_ascii=False),
        ),
    )
    conn.commit()
    flash("Profile uploaded. Here is your public page.", "ok")
    return redirect(url_for("profile", steam_id=steam_id))


@app.get("/me")
@login_required
def me():
    user = current_user()
    rows = get_db().execute(
        "SELECT * FROM profiles WHERE user_id = ? ORDER BY updated_at DESC", (user["id"],)
    ).fetchall()
    profiles = []
    for row in rows:
        data = _profile_data(row)
        profiles.append(
            {
                "row": row,
                "persona": H.profile_name(row),
                "avatar": row["avatar_path"],
                "clan": H.profile_clan(get_db(), user["id"]),
                "rank": data.get("progress", {}).get("rank", 0),
                "kills": data.get("progress", {}).get("kills", 0),
                "kd": data.get("derived", {}).get("kd", 0),
            }
        )
    clan = H.profile_clan(get_db(), user["id"])
    tokens = get_db().execute(
        "SELECT * FROM upload_tokens WHERE user_id = ? AND revoked_at IS NULL ORDER BY id DESC",
        (user["id"],),
    ).fetchall()
    new_token = session.pop("new_token", None)
    return render_template(
        "me.html", profiles=profiles, clan=clan, tokens=tokens, new_token=new_token
    )


@app.post("/me/tokens")
@login_required
def create_upload_token():
    verify_csrf()
    user = current_user()
    label = (request.form.get("label") or "").strip()[:40]
    steam_id = (request.form.get("steam_id") or "").strip()
    if not STEAM_ID_RE.match(steam_id):
        flash("Enter the Steam ID this token may upload for.", "error")
        return redirect(url_for("me"))
    if user["steam_id"] and user["steam_id"] != steam_id:
        flash("A Steam-linked account can only create tokens for its own Steam ID.", "error")
        return redirect(url_for("me"))
    token = "bbr_" + secrets.token_urlsafe(32)
    conn = get_db()
    conn.execute(
        """
        INSERT INTO upload_tokens (user_id, token_hash, label, steam_id, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user["id"],
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
            label or "collector",
            steam_id,
            utc_now(),
        ),
    )
    conn.commit()
    session["new_token"] = token
    flash("Token created. Copy it now; the server only keeps a hash.", "ok")
    return redirect(url_for("me"))


@app.post("/me/tokens/<int:token_id>/revoke")
@login_required
def revoke_upload_token(token_id: int):
    verify_csrf()
    user = current_user()
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM upload_tokens WHERE id = ? AND user_id = ?",
        (token_id, user["id"]),
    ).fetchone()
    if not row:
        abort(404)
    conn.execute(
        "UPDATE upload_tokens SET revoked_at = ? WHERE id = ?", (utc_now(), token_id)
    )
    conn.commit()
    flash("Token revoked.", "ok")
    return redirect(url_for("me"))


@app.post("/api/captures")
def api_upload_capture():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify(ok=False, error="Missing bearer token."), 401
    digest = hashlib.sha256(auth[7:].strip().encode("utf-8")).hexdigest()
    conn = get_db()
    token_row = conn.execute(
        "SELECT * FROM upload_tokens WHERE token_hash = ? AND revoked_at IS NULL",
        (digest,),
    ).fetchone()
    if not token_row:
        return jsonify(ok=False, error="Unknown or revoked token."), 401
    doc = request.get_json(silent=True)
    if not isinstance(doc, dict):
        return jsonify(ok=False, error="Send the capture as a JSON object."), 400
    try:
        steam_id, persona = validate_profile(doc)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    if steam_id != token_row["steam_id"]:
        return (
            jsonify(
                ok=False,
                error="This token is bound to a different Steam ID.",
            ),
            403,
        )
    allowed, retry = LIMITER.hit(
        f"api_upload:{token_row['user_id']}", *UPLOAD_LIMIT
    )
    if not allowed:
        return (
            jsonify(ok=False, error="Too many uploads. Try later."),
            429,
            {"Retry-After": str(retry)},
        )
    existing = _load_profile(steam_id)
    if existing and existing["user_id"] != token_row["user_id"]:
        return (
            jsonify(ok=False, error="That Steam record belongs to another account."),
            409,
        )
    visibility = existing["visibility"] if existing else "public"
    captured = doc.get("captured_at") or utc_now()
    conn.execute(
        """
        INSERT INTO profiles (steam_id, user_id, persona_name, captured_at, updated_at, visibility, data)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(steam_id) DO UPDATE SET
            persona_name = excluded.persona_name,
            captured_at = excluded.captured_at,
            updated_at = excluded.updated_at,
            data = excluded.data
        """,
        (
            steam_id,
            token_row["user_id"],
            persona,
            captured,
            utc_now(),
            visibility,
            json.dumps(doc, ensure_ascii=False),
        ),
    )
    conn.execute(
        "UPDATE upload_tokens SET last_used_at = ? WHERE id = ?",
        (utc_now(), token_row["id"]),
    )
    conn.commit()
    return jsonify(
        ok=True,
        steam_id=steam_id,
        persona=persona,
        url=_public_url("profile", steam_id=steam_id),
    )


@app.get("/players")
def players():
    query = (request.args.get("q") or "").strip()[:40]
    conn = get_db()
    if query:
        rows = conn.execute(
            """
            SELECT * FROM players
            WHERE persona_name LIKE ? OR real_name LIKE ?
            ORDER BY persona_name COLLATE NOCASE
            LIMIT 60
            """,
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM players ORDER BY persona_name COLLATE NOCASE LIMIT 60"
        ).fetchall()
    total = conn.execute("SELECT COUNT(*) AS n FROM players").fetchone()["n"]
    captured = {
        row["steam_id"]
        for row in conn.execute("SELECT steam_id FROM profiles WHERE visibility = 'public'")
    }
    return render_template(
        "players.html",
        players=rows,
        query=query,
        total=total,
        captured=captured,
    )


@app.post("/players/add")
def player_add():
    verify_csrf()
    allowed, retry = LIMITER.hit(
        f"playeradd:{request.remote_addr or '?'}", *PLAYER_ADD_LIMIT
    )
    if not allowed:
        return (
            render_template("429.html", retry=retry, scope="player lookup"),
            429,
            {"Retry-After": str(retry)},
        )
    raw = request.form.get("steam", "")
    try:
        steam_id = steam_profiles.resolve_steam_id(raw)
        steam_profiles.refresh_player(get_db(), steam_id, MEDIA_DIR)
    except steam_profiles.SteamError as exc:
        flash(str(exc), "error")
        return redirect(url_for("players"))
    flash("Steam profile added. Upload a capture to attach stats.", "ok")
    return redirect(url_for("profile", steam_id=steam_id))


@app.get("/p/<steam_id>")
def profile(steam_id: str):
    if not STEAM_ID_RE.match(steam_id):
        abort(404)
    row = _load_profile(steam_id)
    player = _load_player(steam_id)
    if not row:
        if not player:
            abort(404)
        owner = bool(current_user()) and current_user()["steam_id"] == steam_id
        return render_template(
            "player.html",
            player=player,
            is_owner=owner,
            captured=False,
        )
    user = current_user()
    if not _can_view(row, user):
        abort(404)
    data = _profile_data(row)
    progress = data.get("progress", {})
    derived = data.get("derived", {})
    classes = data.get("classes", {})
    weapons = [w for w in data.get("weapons", []) if w.get("kills") or w.get("extra")][:12]
    max_kills = max([w.get("kills", 0) for w in weapons] or [1])
    max_class_score = max([c.get("score", 0) for c in classes.values()] or [1])
    name = (
        row["display_name"]
        or (player["persona_name"] if player else "")
        or H.profile_name(row)
    )
    if row["avatar_path"]:
        avatar_path, avatar_kind = row["avatar_path"], "avatars"
    elif player and player["avatar_path"]:
        avatar_path, avatar_kind = player["avatar_path"], "steam"
    else:
        avatar_path, avatar_kind = None, "avatars"
    bio = row["bio"] or (player["summary"] if player else "")
    return render_template(
        "profile.html",
        row=row,
        player=player,
        name=name,
        avatar_path=avatar_path,
        avatar_kind=avatar_kind,
        bio=bio,
        captured=True,
        clan=H.profile_clan(get_db(), row["user_id"]),
        social_links=H.profile_socials(row),
        data=data,
        p=progress,
        d=derived,
        classes=classes,
        weapons=weapons,
        max_kills=max_kills or 1,
        max_class_score=max_class_score or 1,
        is_owner=bool(user) and user["id"] == row["user_id"],
    )


@app.get("/leaderboard")
def leaderboard():
    sort = request.args.get("sort", "kills")
    if sort not in ("kills", "kd", "score", "rank", "hours"):
        sort = "kills"
    rows = get_db().execute(
        "SELECT * FROM profiles WHERE visibility = 'public'"
    ).fetchall()
    entries = []
    for row in rows:
        data = _profile_data(row)
        p = data.get("progress", {})
        d = data.get("derived", {})
        entries.append(
            {
                "steam_id": row["steam_id"],
                "persona": H.profile_name(row),
                "avatar": row["avatar_path"],
                "clan": H.profile_clan(get_db(), row["user_id"]),
                "kills": p.get("kills", 0),
                "kd": d.get("kd", 0),
                "score": p.get("total_score", 0),
                "rank": p.get("rank", 0),
                "hours": d.get("hours_played", 0),
                "updated_at": row["updated_at"],
            }
        )
    key = {
        "kills": lambda e: e["kills"],
        "kd": lambda e: e["kd"],
        "score": lambda e: e["score"],
        "rank": lambda e: e["rank"],
        "hours": lambda e: e["hours"],
    }[sort]
    entries.sort(key=key, reverse=True)
    return render_template("leaderboard.html", entries=entries[:50], sort=sort)


@app.post("/profiles/<steam_id>/visibility")
@login_required
def set_visibility(steam_id: str):
    verify_csrf()
    user = current_user()
    row = _load_profile(steam_id)
    if not row or row["user_id"] != user["id"]:
        abort(404)
    visibility = request.form.get("visibility", "public")
    if visibility not in ("public", "private"):
        visibility = "public"
    conn = get_db()
    conn.execute(
        "UPDATE profiles SET visibility = ?, updated_at = ? WHERE steam_id = ?",
        (visibility, utc_now(), steam_id),
    )
    conn.commit()
    flash("Visibility updated.", "ok")
    return redirect(url_for("me"))


@app.post("/profiles/<steam_id>/delete")
@login_required
def delete_profile(steam_id: str):
    verify_csrf()
    user = current_user()
    row = _load_profile(steam_id)
    if not row or row["user_id"] != user["id"]:
        abort(404)
    conn = get_db()
    avatar = row["avatar_path"]
    conn.execute("DELETE FROM profiles WHERE steam_id = ?", (steam_id,))
    conn.commit()
    if avatar:
        media.delete_image("avatars", avatar, MEDIA_DIR)
    flash("Profile removed from the site.", "ok")
    return redirect(url_for("me"))


@app.get("/api/profiles/<steam_id>")
def api_profile(steam_id: str):
    if not STEAM_ID_RE.match(steam_id):
        abort(404)
    row = _load_profile(steam_id)
    if not row:
        abort(404)
    if not _can_view(row, current_user()):
        abort(404)
    data = _profile_data(row)
    clan = H.profile_clan(get_db(), row["user_id"])
    data["site"] = {
        "persona_name": row["persona_name"],
        "display_name": H.profile_name(row),
        "avatar_url": url_for("media_file", kind="avatars", filename=row["avatar_path"]) if row["avatar_path"] else None,
        "socials": socials.loads(row["social_json"]),
        "clan": (
            {"tag": clan["tag"], "name": clan["name"], "slug": clan["slug"]}
            if clan
            else None
        ),
        "visibility": row["visibility"],
        "updated_at": row["updated_at"],
    }
    return jsonify(data)


def _download_meta(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    stat = path.stat()
    cache = app.config.setdefault("_DOWNLOAD_CACHE", {})
    key = str(path)
    cached = cache.get(key)
    if cached and cached["mtime"] == stat.st_mtime and cached["size"] == stat.st_size:
        return cached
    meta = {
        "path": path,
        "name": path.name,
        "size": stat.st_size,
        "size_text": H.human_size(stat.st_size),
        "sha256": H.sha256_file(path),
        "mtime": stat.st_mtime,
    }
    cache[key] = meta
    return meta


@app.get("/download")
def download():
    return render_template(
        "download.html",
        exe=_download_meta(DOWNLOAD_PATH),
        archive=_download_meta(ZIP_PATH),
        version=RIPPER_VERSION,
    )


@app.get("/download/windows")
@app.get("/download/exe")
def download_windows():
    if not DOWNLOAD_PATH.is_file():
        abort(404)
    return send_file(
        DOWNLOAD_PATH,
        as_attachment=True,
        download_name="BattleBitStatRipper.exe",
        mimetype="application/vnd.microsoft.portable-executable",
    )


@app.get("/download/zip")
def download_zip():
    if not ZIP_PATH.is_file():
        abort(404)
    return send_file(
        ZIP_PATH,
        as_attachment=True,
        download_name="BattleBitStatRipper-windows-x64.zip",
        mimetype="application/zip",
    )


@app.get("/healthz")
def healthz():
    conn = get_db()
    return jsonify(
        {
            "ok": True,
            "profiles": conn.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"],
            "clans": conn.execute("SELECT COUNT(*) AS n FROM clans").fetchone()["n"],
            "version": app.config.get("BBR_RIPPER_VERSION"),
        }
    )


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html"), 404


@app.errorhandler(413)
def too_large(_error):
    flash("That upload is too large.", "error")
    return redirect(url_for("upload"))


@app.errorhandler(400)
def bad_request(error):
    return render_template("400.html", message=getattr(error, "description", "Bad request")), 400


@app.errorhandler(429)
def too_many_requests(error):
    retry = getattr(error, "retry_after", 60)
    return render_template("429.html", retry=retry, scope="request"), 429


import site_ext  # noqa: E402  (routes need the helpers above)

site_ext.register(
    app,
    {
        "get_db": get_db,
        "current_user": current_user,
        "login_required": login_required,
        "verify_csrf": verify_csrf,
        "utc_now": utc_now,
    },
)

init_db()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8099")), debug=False)
