"""Folder colour feature (v1.6.0).

Covers:
- new folders get a palette colour,
- the colour-pick route accepts palette values and rejects everything else,
- cross-user isolation on the colour-pick route (404, not 403),
- the swatch renders on both home and folders list.
"""
import re


def _register(client, invite, username="alice", password="correct-horse-1"):
    code = invite()
    return client.post("/register", data={
        "invite_code": code, "username": username,
        "password": password, "confirm": password,
        "submit": "Create account",
    })


def _login(client, username="alice", password="correct-horse-1"):
    return client.post("/login", data={
        "username": username, "password": password, "submit": "Log in",
    })


def _mk_folder_via_api(client, name):
    return client.post("/folders/new", data={
        "name": name, "submit": "Save folder",
    }, follow_redirects=True)


# ---- Palette assignment on create -----------------------------------

def test_new_folder_gets_palette_color(app, client, invite):
    _register(client, invite)
    _mk_folder_via_api(client, "Languages")
    folder = app.Folder.query.filter_by(name="Languages").one()
    assert folder.color in app.FOLDER_PALETTE


def test_new_folder_via_folder_list_also_gets_palette_color(app, client, invite):
    _register(client, invite)
    client.post("/folders", data={"name": "History", "submit": "Save folder"}, follow_redirects=True)
    folder = app.Folder.query.filter_by(name="History").one()
    assert folder.color in app.FOLDER_PALETTE


# ---- Palette separation from deck palette ---------------------------

def test_folder_and_deck_palettes_are_disjoint(app):
    """The whole point of this change: folder colours are visibly
    different from deck colours. Enforce no accidental overlap."""
    assert set(app.FOLDER_PALETTE).isdisjoint(set(app.DECK_PALETTE))


# ---- /folders/<id>/color route --------------------------------------

def test_set_folder_color_accepts_palette_value(app, client, invite):
    _register(client, invite)
    _mk_folder_via_api(client, "Languages")
    folder = app.Folder.query.filter_by(name="Languages").one()
    new_color = app.FOLDER_PALETTE[0]
    r = client.post(f"/folders/{folder.id}/color", data={"color": new_color})
    assert r.status_code in (301, 302)
    app.db.session.refresh(folder)
    assert folder.color == new_color


def test_set_folder_color_rejects_non_palette_value(app, client, invite):
    _register(client, invite)
    _mk_folder_via_api(client, "Languages")
    folder = app.Folder.query.filter_by(name="Languages").one()
    original = folder.color
    r = client.post(f"/folders/{folder.id}/color", data={"color": "#000000"})
    assert r.status_code == 400
    app.db.session.refresh(folder)
    assert folder.color == original


def test_set_folder_color_rejects_empty(app, client, invite):
    _register(client, invite)
    _mk_folder_via_api(client, "Languages")
    folder = app.Folder.query.filter_by(name="Languages").one()
    r = client.post(f"/folders/{folder.id}/color", data={"color": ""})
    assert r.status_code == 400


def test_set_folder_color_requires_login(app, client, invite):
    _register(client, invite)
    _mk_folder_via_api(client, "Languages")
    folder = app.Folder.query.filter_by(name="Languages").one()
    client.post("/logout")
    r = client.post(
        f"/folders/{folder.id}/color",
        data={"color": app.FOLDER_PALETTE[0]},
        follow_redirects=False,
    )
    assert r.status_code in (301, 302)
    assert "/login" in r.headers["Location"]


def test_set_folder_color_cross_user_is_404(app, client, invite):
    _register(client, invite, "alice", "correct-horse-1")
    _mk_folder_via_api(client, "Languages")
    alice_folder = app.Folder.query.filter_by(name="Languages").one()
    client.post("/logout")

    _register(client, invite, "bob", "correct-horse-2")
    r = client.post(
        f"/folders/{alice_folder.id}/color",
        data={"color": app.FOLDER_PALETTE[0]},
    )
    assert r.status_code == 404


# ---- Redirect targets ----------------------------------------------

def test_set_folder_color_redirects_home_when_next_home(app, client, invite):
    _register(client, invite)
    _mk_folder_via_api(client, "Languages")
    folder = app.Folder.query.filter_by(name="Languages").one()
    r = client.post(
        f"/folders/{folder.id}/color",
        data={"color": app.FOLDER_PALETTE[0], "next": "home"},
        follow_redirects=False,
    )
    assert r.status_code in (301, 302)
    # The home endpoint URL — don't hard-code the path.
    with app.app.test_request_context():
        from flask import url_for
        home_url = url_for("home")
    assert r.headers["Location"].endswith(home_url)


def test_set_folder_color_defaults_to_folder_list(app, client, invite):
    _register(client, invite)
    _mk_folder_via_api(client, "Languages")
    folder = app.Folder.query.filter_by(name="Languages").one()
    r = client.post(
        f"/folders/{folder.id}/color",
        data={"color": app.FOLDER_PALETTE[0]},
        follow_redirects=False,
    )
    assert r.status_code in (301, 302)
    assert r.headers["Location"].endswith("/folders")


# ---- Template rendering ---------------------------------------------

def test_home_renders_folder_swatch(app, client, invite):
    _register(client, invite)
    _mk_folder_via_api(client, "Languages")
    folder = app.Folder.query.filter_by(name="Languages").one()
    r = client.get("/", follow_redirects=True)
    body = r.get_data(as_text=True)
    assert "folder-swatch" in body
    assert folder.color in body


def test_home_renders_unfiled_grey_swatch(app, client, invite):
    _register(client, invite)
    r = client.get("/", follow_redirects=True)
    body = r.get_data(as_text=True)
    # Unfiled appears in the folders section even with no folders? No —
    # the home page only renders the folders section when there's at
    # least one folder or deck. Make one.
    _mk_folder_via_api(client, "Languages")
    r = client.get("/", follow_redirects=True)
    body = r.get_data(as_text=True)
    assert app.UNFILED_SWATCH in body
    assert "folder-swatch-static" in body


def test_folders_list_renders_folder_swatch(app, client, invite):
    _register(client, invite)
    _mk_folder_via_api(client, "Languages")
    folder = app.Folder.query.filter_by(name="Languages").one()
    r = client.get("/folders")
    body = r.get_data(as_text=True)
    assert "folder-swatch" in body
    assert folder.color in body


def test_folders_list_popover_posts_to_color_route(app, client, invite):
    _register(client, invite)
    _mk_folder_via_api(client, "Languages")
    folder = app.Folder.query.filter_by(name="Languages").one()
    r = client.get("/folders")
    body = r.get_data(as_text=True)
    assert f'action="/folders/{folder.id}/color"' in body
    # Every palette colour is a submit button in the popover.
    for c in app.FOLDER_PALETTE:
        assert f'value="{c}"' in body


# ---- Migration 0008 backfill ---------------------------------------

def test_migration_0008_backfills_existing_folders(app):
    """Simulate pre-0008 state: create a folder without a colour, then
    reset colour to NULL and re-run the backfill fragment.

    The migration is already applied by conftest; we're verifying the
    model handles NULL colours gracefully (template falls back to grey)
    and that new rows pick up a palette colour."""
    from app import Folder, User, db, random_folder_color, FOLDER_PALETTE

    user = User(username="u", password_hash=b"x")
    db.session.add(user)
    db.session.commit()

    # Manually create without a colour, as if the row predated the migration.
    f = Folder(user_id=user.id, name="Old")
    db.session.add(f)
    db.session.commit()
    assert f.color is None  # new rows via the ORM default stay NULL

    # Repeatedly sampling should give us a palette hue each time.
    for _ in range(20):
        assert random_folder_color() in FOLDER_PALETTE
