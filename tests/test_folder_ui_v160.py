"""Follow-up tests for v1.6.0 folder-colour UI iterations.

Covers:
- swatch is nested *inside* the folder row box, not a sibling,
- CSS has the three tunable custom properties (--folder-row-pad,
  --folder-swatch-size, --folder-text-gap),
- open picker is layered above the rest of the page,
- sidebar renders the top 3 most-recently-opened folders as letter tiles,
  excludes Unfiled, caps at 3, and ignores folders with no opened decks,
- random_folder_color(user_id) samples without replacement until the
  palette is exhausted.
"""
from datetime import datetime, timedelta
from pathlib import Path


def _register(client, invite, username="alice", password="correct-horse-1"):
    code = invite()
    return client.post("/register", data={
        "invite_code": code, "username": username,
        "password": password, "confirm": password,
        "submit": "Create account",
    })


def _mk_folder(client, name):
    return client.post("/folders/new", data={
        "name": name, "submit": "Save folder",
    }, follow_redirects=True)


def _mk_deck(app, user_id, name, folder_id=None, last_opened=None):
    d = app.Deck(user_id=user_id, name=name, folder_id=folder_id)
    app.db.session.add(d)
    app.db.session.flush()
    if last_opened is not None:
        d.last_opened_at = last_opened
    app.db.session.commit()
    return d


# ---- Swatch nested inside the box (change 1) -----------------------

def test_home_swatch_nested_inside_folder_row_wrap(app, client, invite):
    _register(client, invite)
    _mk_folder(client, "Languages")
    body = client.get("/", follow_redirects=True).get_data(as_text=True)
    # The swatch and the row anchor must share one folder-row-wrap <li>.
    # Smoke-test by requiring the wrapper class and that the swatch class
    # appears before the next </li> that follows it.
    assert "folder-row-wrap" in body
    # Pull a slice around the first wrapper and check both tokens appear
    # before the closing </li>.
    idx = body.index("folder-row-wrap")
    end = body.index("</li>", idx)
    chunk = body[idx:end]
    assert "folder-swatch" in chunk
    assert "deck-row" in chunk or "folder-row" in chunk


def test_folders_list_swatch_nested_inside_folder_row_wrap(app, client, invite):
    _register(client, invite)
    _mk_folder(client, "Languages")
    body = client.get("/folders").get_data(as_text=True)
    # First wrapper = Unfiled (static swatch); second wrapper = Languages.
    assert body.count("folder-row-wrap") >= 2
    idx = body.index("folder-row-wrap", body.index("folder-row-wrap") + 1)
    end = body.index("</li>", idx)
    chunk = body[idx:end]
    assert "folder-swatch" in chunk
    assert "folder-row" in chunk


# ---- Tunable CSS custom properties (change 2) ----------------------

def test_folder_row_css_vars_declared():
    css = (Path(__file__).resolve().parent.parent
           / "static" / "style.css").read_text()
    assert "--folder-row-pad" in css
    assert "--folder-swatch-size" in css
    assert "--folder-text-gap" in css


def test_folder_row_padding_keys_off_vars():
    """Padding and min-height must be expressed as calc() over the vars
    so they stay in sync when any single dial moves."""
    css = (Path(__file__).resolve().parent.parent
           / "static" / "style.css").read_text()
    assert "var(--folder-row-pad)" in css
    assert "var(--folder-swatch-size)" in css
    assert "var(--folder-text-gap)" in css


# ---- Picker always above (change 3) --------------------------------

def test_open_picker_promotes_to_top_layer():
    css = (Path(__file__).resolve().parent.parent
           / "static" / "style.css").read_text()
    # Both the open <details> row and the popover itself must take the
    # top layer (z-index: 9999) and open rows must create their own
    # stacking context so sibling rows can't underlap.
    assert ".folder-swatch-picker[open]" in css
    # Grab the open-state block and the popover block, confirm both
    # explicitly set z-index: 9999 and the open row isolates.
    open_block = css.split(".folder-swatch-picker[open]", 1)[1].split("}", 1)[0]
    assert "z-index: 9999" in open_block
    assert "isolation: isolate" in open_block
    popover_block = css.split(".folder-swatch-popover", 1)[1].split("}", 1)[0]
    assert "z-index: 9999" in popover_block


def test_folder_row_overflow_is_visible():
    """Row/list ancestors can't clip the open popover."""
    css = (Path(__file__).resolve().parent.parent
           / "static" / "style.css").read_text()
    assert "overflow: visible" in css


# ---- Sidebar recent-folder tiles (change 4) ------------------------

def test_sidebar_blank_when_no_opened_decks(app, client, invite):
    _register(client, invite)
    _mk_folder(client, "Languages")
    body = client.get("/", follow_redirects=True).get_data(as_text=True)
    # No deck has been opened yet, so no sidebar folder tile should appear.
    assert "sidebar-folder" not in body


def test_sidebar_renders_recent_folder_tile(app, client, invite):
    _register(client, invite)
    alice = app.User.query.filter_by(username="alice").one()
    _mk_folder(client, "Languages")
    f = app.Folder.query.filter_by(name="Languages").one()
    _mk_deck(app, alice.id, "French", folder_id=f.id,
             last_opened=datetime.utcnow())
    body = client.get("/", follow_redirects=True).get_data(as_text=True)
    assert "sidebar-folder" in body
    assert f">{f.name[0].upper()}<" in body
    # And the tile is coloured with that folder's own hex.
    assert f.color in body


def test_sidebar_caps_at_three_tiles(app, client, invite):
    _register(client, invite)
    alice = app.User.query.filter_by(username="alice").one()
    now = datetime.utcnow()
    for i, name in enumerate(["A-folder", "B-folder", "C-folder",
                              "D-folder", "E-folder"]):
        _mk_folder(client, name)
        f = app.Folder.query.filter_by(name=name).one()
        _mk_deck(app, alice.id, f"deck-{name}", folder_id=f.id,
                 last_opened=now - timedelta(minutes=i))
    body = client.get("/", follow_redirects=True).get_data(as_text=True)
    # Three most recently-opened: A, B, C.
    assert body.count('class="sidebar-folder"') == 3
    for letter in ("A", "B", "C"):
        assert f">{letter}<" in body
    for letter in ("D", "E"):
        assert f">{letter}<" not in body or body.count(f">{letter}<") == 0


def test_sidebar_excludes_unfiled(app, client, invite):
    _register(client, invite)
    alice = app.User.query.filter_by(username="alice").one()
    # Deck in Unfiled (folder_id=None), freshly opened — must NOT appear
    # as a sidebar tile.
    _mk_deck(app, alice.id, "orphan", folder_id=None,
             last_opened=datetime.utcnow())
    body = client.get("/", follow_redirects=True).get_data(as_text=True)
    assert "sidebar-folder" not in body
    # Also must not render a "U" tile for Unfiled.
    assert '>U<' not in body


def test_sidebar_hidden_when_logged_out(app, client, invite):
    # Anonymous surface — must not try to query folders.
    r = client.get("/login")
    body = r.get_data(as_text=True)
    assert "sidebar-folder" not in body


def test_sidebar_orders_by_most_recent(app, client, invite):
    _register(client, invite)
    alice = app.User.query.filter_by(username="alice").one()
    now = datetime.utcnow()
    # Create oldest first; the newest-opened folder should sit on top.
    for i, name in enumerate(["Oldest", "Middle", "Newest"]):
        _mk_folder(client, name)
        f = app.Folder.query.filter_by(name=name).one()
        _mk_deck(app, alice.id, f"d-{name}", folder_id=f.id,
                 last_opened=now - timedelta(minutes=10 - i * 3))
    body = client.get("/", follow_redirects=True).get_data(as_text=True)
    # Newest tile appears before Oldest tile in document order.
    newest_idx = body.index(">N<")
    middle_idx = body.index(">M<")
    oldest_idx = body.index(">O<")
    assert newest_idx < middle_idx < oldest_idx


# ---- Sample without replacement (change 5) -------------------------

def test_random_folder_color_avoids_used_hues(app):
    """With N used colours, 100 draws must not pick any of them until
    the palette is exhausted."""
    from app import Folder, User, db, random_folder_color, FOLDER_PALETTE

    u = User(username="alice-crc", password_hash=b"x")
    db.session.add(u)
    db.session.commit()
    used = FOLDER_PALETTE[:3]
    for i, c in enumerate(used):
        db.session.add(Folder(user_id=u.id, name=f"f{i}", color=c))
    db.session.commit()

    for _ in range(100):
        c = random_folder_color(u.id)
        assert c in FOLDER_PALETTE
        assert c not in used


def test_random_folder_color_repeats_once_palette_exhausted(app):
    """When every palette hue is already in use, draws come back from
    the full palette (we don't crash / return None)."""
    from app import Folder, User, db, random_folder_color, FOLDER_PALETTE

    u = User(username="alice-exh", password_hash=b"x")
    db.session.add(u)
    db.session.commit()
    for i, c in enumerate(FOLDER_PALETTE):
        db.session.add(Folder(user_id=u.id, name=f"f{i}", color=c))
    db.session.commit()

    seen = {random_folder_color(u.id) for _ in range(50)}
    assert seen.issubset(set(FOLDER_PALETTE))
    assert len(seen) >= 1


def test_random_folder_color_scoped_per_user(app):
    """Alice's used colours must not constrain Bob's palette."""
    from app import Folder, User, db, random_folder_color, FOLDER_PALETTE

    alice = User(username="alice-s", password_hash=b"x")
    bob = User(username="bob-s", password_hash=b"x")
    db.session.add_all([alice, bob])
    db.session.commit()
    # Alice uses all 10 colours.
    for i, c in enumerate(FOLDER_PALETTE):
        db.session.add(Folder(user_id=alice.id, name=f"a{i}", color=c))
    db.session.commit()
    # Bob uses one.
    bob_used = FOLDER_PALETTE[0]
    db.session.add(Folder(user_id=bob.id, name="b0", color=bob_used))
    db.session.commit()
    # Bob's next draws must still avoid his one used colour.
    for _ in range(50):
        assert random_folder_color(bob.id) != bob_used


def test_random_folder_color_no_user_id_falls_back_to_uniform(app):
    """The no-user-context overload still works (used by the migration
    backfill helper and anywhere else that doesn't have a user yet)."""
    from app import random_folder_color, FOLDER_PALETTE

    for _ in range(20):
        assert random_folder_color() in FOLDER_PALETTE


def test_new_folders_via_route_sample_without_replacement(app, client, invite):
    """End-to-end: creating N folders back-to-back as the same user
    gives N distinct colours as long as N <= len(FOLDER_PALETTE)."""
    _register(client, invite)
    names = [f"folder-{i}" for i in range(len(app.FOLDER_PALETTE))]
    for name in names:
        _mk_folder(client, name)
    colors = [f.color for f in
              app.Folder.query.filter(app.Folder.name.in_(names)).all()]
    assert len(colors) == len(app.FOLDER_PALETTE)
    assert len(set(colors)) == len(app.FOLDER_PALETTE)
    assert set(colors) == set(app.FOLDER_PALETTE)
