"""Clan, profile-media, and profile-social routes.

Registered by ``app.py`` after the core routes. Kept separate so the original
upload/leaderboard flow stays readable and the new surface is easy to audit.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

import media
import site_helpers as H
import socials
from rate_limit import LIMITER

NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-\[\]]{0,32}$")
TAG_RE = re.compile(r"^[A-Za-z0-9]{2,5}$")
STEAM_ID_RE = re.compile(r"^\d{16,18}$")

# scope: (requests, window seconds)
RATE_LIMITS = {
    "profile_edit": (20, 3600),
    "clan_create": (3, 86400),
    "clan_join": (8, 3600),
    "clan_settings": (12, 3600),
    "clan_action": (60, 3600),
    "clan_disband": (3, 3600),
}


def register(app, helpers) -> None:
    get_db = helpers["get_db"]
    current_user = helpers["current_user"]
    login_required = helpers["login_required"]
    verify_csrf = helpers["verify_csrf"]
    utc_now = helpers["utc_now"]
    media_dir = Path(app.config["BBR_MEDIA_DIR"])

    def too_many(scope: str, user_id: int):
        limit, window = RATE_LIMITS[scope]
        allowed, retry = LIMITER.hit(f"{scope}:{user_id}", limit, window)
        if allowed:
            return None
        return (
            render_template("429.html", retry=retry, scope=scope),
            429,
            {"Retry-After": str(retry)},
        )

    def load_profile(steam_id: str):
        return get_db().execute(
            "SELECT * FROM profiles WHERE steam_id = ?", (steam_id,)
        ).fetchone()

    def clan_or_404(slug: str):
        clan = H.clan_by_slug(get_db(), slug)
        if not clan:
            abort(404)
        return clan

    # ------------------------------------------------------------------
    # Profile editing: portrait, display name, bio, socials, visibility
    # ------------------------------------------------------------------
    @app.route("/p/<steam_id>/edit", methods=["GET", "POST"])
    @login_required
    def profile_edit(steam_id: str):
        row = load_profile(steam_id)
        user = current_user()
        if not row or row["user_id"] != user["id"]:
            abort(404)
        values = socials.loads(row["social_json"])
        form = {
            "display_name": row["display_name"] or "",
            "bio": row["bio"] or "",
        }
        if request.method == "POST":
            limited = too_many("profile_edit", user["id"])
            if limited:
                return limited
            verify_csrf()
            display_name = " ".join((request.form.get("display_name") or "").split())
            bio = (request.form.get("bio") or "").strip()
            form = {"display_name": display_name, "bio": bio}
            visibility = request.form.get("visibility", row["visibility"])
            if visibility not in ("public", "private"):
                visibility = row["visibility"]
            if display_name and not NAME_RE.match(display_name):
                flash("Display name: 32 characters max, letters/numbers/space/._-[] only.", "error")
                return render_template(
                    "profile_edit.html", row=row, form=form, social_values=values,
                    social_specs=socials.SOCIALS, avatar_error=None,
                ), 400
            if len(bio) > 280:
                flash("Bio must be 280 characters or less.", "error")
                return render_template(
                    "profile_edit.html", row=row, form=form, social_values=values,
                    social_specs=socials.SOCIALS, avatar_error=None,
                ), 400
            try:
                social_values = socials.parse_socials(request.form)
            except ValueError as exc:
                flash(str(exc), "error")
                return render_template(
                    "profile_edit.html", row=row, form=form, social_values=values,
                    social_specs=socials.SOCIALS, avatar_error=None,
                ), 400

            conn = get_db()
            new_avatar = row["avatar_path"]
            avatar_file = request.files.get("avatar")
            old_avatar = row["avatar_path"]
            if request.form.get("remove_avatar"):
                new_avatar = None
            if avatar_file and avatar_file.filename:
                try:
                    new_avatar = media.save_image(avatar_file, "avatars", media_dir)
                except media.ImageError as exc:
                    flash(str(exc), "error")
                    return render_template(
                        "profile_edit.html", row=row, form=form,
                        social_values=social_values, social_specs=socials.SOCIALS,
                        avatar_error=str(exc),
                    ), 400
                if old_avatar and old_avatar != new_avatar:
                    media.delete_image("avatars", old_avatar, media_dir)
            conn.execute(
                """
                UPDATE profiles
                SET display_name = ?, bio = ?, avatar_path = ?, social_json = ?,
                    visibility = ?, updated_at = ?
                WHERE steam_id = ?
                """,
                (
                    display_name or None,
                    bio,
                    new_avatar,
                    socials.dumps(social_values),
                    visibility,
                    utc_now(),
                    steam_id,
                ),
            )
            conn.commit()
            flash("Profile updated.", "ok")
            return redirect(url_for("profile", steam_id=steam_id))
        return render_template(
            "profile_edit.html",
            row=row,
            form=form,
            social_values=values,
            social_specs=socials.SOCIALS,
            avatar_error=None,
        )

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------
    @app.get("/media/<kind>/<path:filename>")
    def media_file(kind: str, filename: str):
        if kind not in ("avatars", "clans"):
            abort(404)
        if Path(filename).name != filename:
            abort(404)
        folder = media_dir / kind
        if not (folder / filename).is_file():
            abort(404)
        return send_from_directory(
            folder, filename, max_age=86400, mimetype="image/webp"
        )

    # ------------------------------------------------------------------
    # Clan directory + creation
    # ------------------------------------------------------------------
    @app.get("/clans")
    def clans():
        query = (request.args.get("q") or "").strip()[:40]
        sort = request.args.get("sort", "members")
        if sort not in ("members", "kills", "kd", "newest"):
            sort = "members"
        items = H.clan_directory(get_db(), query, sort)
        return render_template("clans.html", items=items, query=query, sort=sort)

    @app.route("/clans/new", methods=["GET", "POST"])
    @login_required
    def clan_new():
        user = current_user()
        conn = get_db()
        existing = H.profile_clan(conn, user["id"])
        if request.method == "GET":
            return render_template(
                "clan_new.html",
                form={"name": "", "tag": "", "description": "", "join_mode": "open",
                      "color": H.CLAN_COLORS[0]},
                social_specs=socials.SOCIALS,
                social_values={},
                colors=H.CLAN_COLORS,
                existing=existing,
            )
        limited = too_many("clan_create", user["id"])
        if limited:
            return limited
        verify_csrf()
        if existing:
            flash("You are already in a clan. Leave it before creating another.", "error")
            return redirect(url_for("clan_page", slug=existing["slug"]))

        name = " ".join((request.form.get("name") or "").split())[:40]
        tag = (request.form.get("tag") or "").strip().upper()
        description = (request.form.get("description") or "").strip()[:500]
        join_mode = request.form.get("join_mode", "open")
        color = request.form.get("color", H.CLAN_COLORS[0])
        form = {"name": name, "tag": tag, "description": description,
                "join_mode": join_mode, "color": color}
        try:
            social_values = socials.parse_socials(request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template(
                "clan_new.html", form=form, social_specs=socials.SOCIALS,
                social_values={}, colors=H.CLAN_COLORS, existing=existing,
            ), 400
        if len(name) < 3:
            flash("Clan name must be at least 3 characters.", "error")
            return render_template(
                "clan_new.html", form=form, social_specs=socials.SOCIALS,
                social_values=social_values, colors=H.CLAN_COLORS, existing=existing,
            ), 400
        if not TAG_RE.match(tag):
            flash("Clan tag must be 2-5 letters or numbers.", "error")
            return render_template(
                "clan_new.html", form=form, social_specs=socials.SOCIALS,
                social_values=social_values, colors=H.CLAN_COLORS, existing=existing,
            ), 400
        if join_mode not in ("open", "request", "closed"):
            join_mode = "open"
        if color not in H.CLAN_COLORS:
            color = H.CLAN_COLORS[0]
        if conn.execute("SELECT 1 FROM clans WHERE tag = ? COLLATE NOCASE", (tag,)).fetchone():
            flash("That clan tag is already taken.", "error")
            return render_template(
                "clan_new.html", form=form, social_specs=socials.SOCIALS,
                social_values=social_values, colors=H.CLAN_COLORS, existing=existing,
            ), 400

        emblem = request.files.get("emblem")
        emblem_name = None
        if emblem and emblem.filename:
            try:
                emblem_name = media.save_image(emblem, "clans", media_dir)
            except media.ImageError as exc:
                flash(str(exc), "error")
                return render_template(
                    "clan_new.html", form=form, social_specs=socials.SOCIALS,
                    social_values=social_values, colors=H.CLAN_COLORS, existing=existing,
                ), 400

        slug = H.unique_slug(conn, name, tag)
        now = utc_now()
        try:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO clans (name, tag, slug, description, emblem_path, color,
                                       join_mode, social_json, owner_user_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (name, tag, slug, description, emblem_name, color, join_mode,
                     socials.dumps(social_values), user["id"], now, now),
                )
                conn.execute(
                    "INSERT INTO clan_members (clan_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
                    (cur.lastrowid, user["id"], now),
                )
        except sqlite3.IntegrityError:
            if emblem_name:
                media.delete_image("clans", emblem_name, media_dir)
            flash("That clan name or tag is already taken.", "error")
            return render_template(
                "clan_new.html", form=form, social_specs=socials.SOCIALS,
                social_values=social_values, colors=H.CLAN_COLORS, existing=existing,
            ), 400
        flash(f"[{tag}] {name} is live.", "ok")
        return redirect(url_for("clan_page", slug=slug))

    # ------------------------------------------------------------------
    # Clan page + membership
    # ------------------------------------------------------------------
    @app.get("/c/<slug>")
    def clan_page(slug: str):
        conn = get_db()
        clan = clan_or_404(slug)
        members = H.member_rows(conn, clan["id"])
        stats = H.roster_stats(conn, clan["id"])
        user = current_user()
        role = H.user_role_in_clan(conn, clan["id"], user["id"] if user else None)
        pending = None
        if user:
            pending = conn.execute(
                "SELECT * FROM clan_requests WHERE clan_id = ? AND user_id = ?",
                (clan["id"], user["id"]),
            ).fetchone()
        requests_rows = []
        if H.can_manage(role):
            requests_rows = conn.execute(
                """
                SELECT r.*, u.username, p.persona_name, p.display_name, p.avatar_path
                FROM clan_requests r JOIN users u ON u.id = r.user_id
                LEFT JOIN profiles p ON p.steam_id = (
                    SELECT steam_id FROM profiles WHERE user_id = r.user_id
                    ORDER BY updated_at DESC LIMIT 1
                )
                WHERE r.clan_id = ? ORDER BY r.created_at
                """,
                (clan["id"],),
            ).fetchall()
        return render_template(
            "clan.html",
            clan=clan,
            members=members,
            stats=stats,
            role=role,
            pending=pending,
            requests=requests_rows,
            social_links=socials.links(clan["social_json"]),
            can_manage=H.can_manage(role),
        )

    @app.post("/c/<slug>/join")
    @login_required
    def clan_join(slug: str):
        user = current_user()
        conn = get_db()
        clan = clan_or_404(slug)
        limited = too_many("clan_join", user["id"])
        if limited:
            return limited
        verify_csrf()
        current = H.profile_clan(conn, user["id"])
        if current:
            if current["id"] == clan["id"]:
                flash("You are already in this clan.", "info")
            else:
                flash("Leave your current clan before joining another.", "error")
            return redirect(url_for("clan_page", slug=slug))
        if clan["join_mode"] == "closed":
            flash("This clan is not accepting new members.", "error")
            return redirect(url_for("clan_page", slug=slug))
        if clan["join_mode"] == "request":
            conn.execute(
                """
                INSERT INTO clan_requests (clan_id, user_id, message, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(clan_id, user_id) DO UPDATE SET
                    message = excluded.message, created_at = excluded.created_at
                """,
                (clan["id"], user["id"], (request.form.get("message") or "").strip()[:200], utc_now()),
            )
            conn.commit()
            flash("Join request sent. The clan officers will review it.", "ok")
        else:
            conn.execute(
                "INSERT INTO clan_members (clan_id, user_id, role, joined_at) VALUES (?, ?, 'member', ?)",
                (clan["id"], user["id"], utc_now()),
            )
            conn.execute(
                "DELETE FROM clan_requests WHERE clan_id = ? AND user_id = ?",
                (clan["id"], user["id"]),
            )
            conn.commit()
            flash(f"You joined [{clan['tag']}].", "ok")
        return redirect(url_for("clan_page", slug=slug))

    @app.post("/c/<slug>/leave")
    @login_required
    def clan_leave(slug: str):
        user = current_user()
        conn = get_db()
        clan = clan_or_404(slug)
        verify_csrf()
        role = H.user_role_in_clan(conn, clan["id"], user["id"])
        if not role:
            flash("You are not in this clan.", "error")
            return redirect(url_for("clan_page", slug=slug))
        if role == "owner":
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM clan_members WHERE clan_id = ?", (clan["id"],)
            ).fetchone()["n"]
            if count > 1:
                flash("You own this clan. Disband it before leaving, or remove the other members.", "error")
                return redirect(url_for("clan_page", slug=slug))
            emblem = clan["emblem_path"]
            conn.execute("DELETE FROM clans WHERE id = ?", (clan["id"],))
            conn.commit()
            if emblem:
                media.delete_image("clans", emblem, media_dir)
            flash("You left the clan and it was disbanded.", "ok")
            return redirect(url_for("clans"))
        conn.execute(
            "DELETE FROM clan_members WHERE clan_id = ? AND user_id = ?",
            (clan["id"], user["id"]),
        )
        conn.commit()
        flash(f"You left [{clan['tag']}].", "ok")
        return redirect(url_for("clans"))

    # ------------------------------------------------------------------
    # Clan management
    # ------------------------------------------------------------------
    @app.get("/c/<slug>/manage")
    @login_required
    def clan_manage(slug: str):
        conn = get_db()
        clan = clan_or_404(slug)
        user = current_user()
        role = H.user_role_in_clan(conn, clan["id"], user["id"])
        if not H.can_manage(role):
            abort(404)
        members = H.member_rows(conn, clan["id"])
        requests_rows = conn.execute(
            """
            SELECT r.*, u.username, p.persona_name, p.display_name, p.avatar_path
            FROM clan_requests r JOIN users u ON u.id = r.user_id
            LEFT JOIN profiles p ON p.steam_id = (
                SELECT steam_id FROM profiles WHERE user_id = r.user_id
                ORDER BY updated_at DESC LIMIT 1
            )
            WHERE r.clan_id = ? ORDER BY r.created_at
            """,
            (clan["id"],),
        ).fetchall()
        return render_template(
            "clan_manage.html",
            clan=clan,
            members=members,
            requests=requests_rows,
            role=role,
            is_owner=role == "owner",
            social_values=socials.loads(clan["social_json"]),
            social_specs=socials.SOCIALS,
            colors=H.CLAN_COLORS,
        )

    @app.post("/c/<slug>/settings")
    @login_required
    def clan_settings(slug: str):
        conn = get_db()
        clan = clan_or_404(slug)
        user = current_user()
        role = H.user_role_in_clan(conn, clan["id"], user["id"])
        if role != "owner":
            abort(404)
        limited = too_many("clan_settings", user["id"])
        if limited:
            return limited
        verify_csrf()
        name = " ".join((request.form.get("name") or "").split())[:40]
        tag = (request.form.get("tag") or "").strip().upper()
        description = (request.form.get("description") or "").strip()[:500]
        join_mode = request.form.get("join_mode", clan["join_mode"])
        color = request.form.get("color", clan["color"])
        try:
            social_values = socials.parse_socials(request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("clan_manage", slug=slug))
        if len(name) < 3 or not TAG_RE.match(tag):
            flash("Clan name must be 3+ characters and tag 2-5 letters/numbers.", "error")
            return redirect(url_for("clan_manage", slug=slug))
        if join_mode not in ("open", "request", "closed"):
            join_mode = clan["join_mode"]
        if color not in H.CLAN_COLORS:
            color = clan["color"]
        if conn.execute(
            "SELECT 1 FROM clans WHERE tag = ? COLLATE NOCASE AND id != ?", (tag, clan["id"])
        ).fetchone():
            flash("That clan tag is already taken.", "error")
            return redirect(url_for("clan_manage", slug=slug))

        old_emblem = clan["emblem_path"]
        new_emblem = old_emblem
        if request.form.get("remove_emblem"):
            new_emblem = None
        emblem = request.files.get("emblem")
        if emblem and emblem.filename:
            try:
                new_emblem = media.save_image(emblem, "clans", media_dir)
            except media.ImageError as exc:
                flash(str(exc), "error")
                return redirect(url_for("clan_manage", slug=slug))
        conn.execute(
            """
            UPDATE clans SET name = ?, tag = ?, description = ?, emblem_path = ?,
                             color = ?, join_mode = ?, social_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, tag, description, new_emblem, color, join_mode,
             socials.dumps(social_values), utc_now(), clan["id"]),
        )
        conn.commit()
        if old_emblem and old_emblem != new_emblem:
            media.delete_image("clans", old_emblem, media_dir)
        flash("Clan settings saved.", "ok")
        return redirect(url_for("clan_manage", slug=slug))

    @app.post("/c/<slug>/requests/<int:request_id>/<action>")
    @login_required
    def clan_request_action(slug: str, request_id: int, action: str):
        conn = get_db()
        clan = clan_or_404(slug)
        user = current_user()
        role = H.user_role_in_clan(conn, clan["id"], user["id"])
        if not H.can_manage(role):
            abort(404)
        verify_csrf()
        limited = too_many("clan_action", user["id"])
        if limited:
            return limited
        row = conn.execute(
            "SELECT * FROM clan_requests WHERE id = ? AND clan_id = ?",
            (request_id, clan["id"]),
        ).fetchone()
        if not row:
            abort(404)
        if action not in ("approve", "reject"):
            abort(404)
        if action == "reject":
            conn.execute("DELETE FROM clan_requests WHERE id = ?", (request_id,))
            conn.commit()
            flash("Request declined.", "ok")
            return redirect(url_for("clan_manage", slug=slug))
        if H.profile_clan(conn, row["user_id"]):
            flash("That player is already in a clan.", "error")
            conn.execute("DELETE FROM clan_requests WHERE id = ?", (request_id,))
            conn.commit()
            return redirect(url_for("clan_manage", slug=slug))
        try:
            with conn:
                conn.execute(
                    "INSERT INTO clan_members (clan_id, user_id, role, joined_at) VALUES (?, ?, 'member', ?)",
                    (clan["id"], row["user_id"], utc_now()),
                )
                conn.execute("DELETE FROM clan_requests WHERE id = ?", (request_id,))
        except sqlite3.IntegrityError:
            flash("That player could not be added.", "error")
            return redirect(url_for("clan_manage", slug=slug))
        flash("Member approved.", "ok")
        return redirect(url_for("clan_manage", slug=slug))

    @app.post("/c/<slug>/members/<int:user_id>/kick")
    @login_required
    def clan_kick(slug: str, user_id: int):
        conn = get_db()
        clan = clan_or_404(slug)
        user = current_user()
        role = H.user_role_in_clan(conn, clan["id"], user["id"])
        if not H.can_manage(role):
            abort(404)
        verify_csrf()
        limited = too_many("clan_action", user["id"])
        if limited:
            return limited
        target = conn.execute(
            "SELECT role FROM clan_members WHERE clan_id = ? AND user_id = ?",
            (clan["id"], user_id),
        ).fetchone()
        if not target or target["role"] == "owner":
            abort(404)
        if role == "officer" and target["role"] == "officer":
            flash("Officers cannot remove other officers.", "error")
            return redirect(url_for("clan_manage", slug=slug))
        conn.execute(
            "DELETE FROM clan_members WHERE clan_id = ? AND user_id = ?",
            (clan["id"], user_id),
        )
        conn.commit()
        flash("Member removed.", "ok")
        return redirect(url_for("clan_manage", slug=slug))

    @app.post("/c/<slug>/members/<int:user_id>/role")
    @login_required
    def clan_role(slug: str, user_id: int):
        conn = get_db()
        clan = clan_or_404(slug)
        user = current_user()
        role = H.user_role_in_clan(conn, clan["id"], user["id"])
        if role != "owner":
            abort(404)
        verify_csrf()
        limited = too_many("clan_action", user["id"])
        if limited:
            return limited
        new_role = request.form.get("role", "member")
        if new_role not in ("officer", "member"):
            abort(400)
        target = conn.execute(
            "SELECT role FROM clan_members WHERE clan_id = ? AND user_id = ?",
            (clan["id"], user_id),
        ).fetchone()
        if not target or target["role"] == "owner":
            abort(404)
        conn.execute(
            "UPDATE clan_members SET role = ? WHERE clan_id = ? AND user_id = ?",
            (new_role, clan["id"], user_id),
        )
        conn.commit()
        flash("Role updated.", "ok")
        return redirect(url_for("clan_manage", slug=slug))

    @app.post("/c/<slug>/disband")
    @login_required
    def clan_disband(slug: str):
        conn = get_db()
        clan = clan_or_404(slug)
        user = current_user()
        role = H.user_role_in_clan(conn, clan["id"], user["id"])
        if role != "owner":
            abort(404)
        verify_csrf()
        limited = too_many("clan_disband", user["id"])
        if limited:
            return limited
        conn.execute("DELETE FROM clans WHERE id = ?", (clan["id"],))
        conn.commit()
        if clan["emblem_path"]:
            media.delete_image("clans", clan["emblem_path"], media_dir)
        flash(f"[{clan['tag']}] {clan['name']} was disbanded.", "ok")
        return redirect(url_for("clans"))
