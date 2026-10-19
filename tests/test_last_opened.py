"""M4 tests — last_opened_at bump behaviour.

The 'open a deck' event is GET /decks/<id>/cards. POST there is card
creation and MUST NOT bump last_opened_at. The home-page 'Recently
opened' section was removed in favour of folder-first navigation; the
column itself survives for any future surface that wants it.
"""
from datetime import datetime, timedelta


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


def _mk_deck(app, user, name, folder_id=None):
    d = app.Deck(user_id=user.id, name=name, folder_id=folder_id)
    app.db.session.add(d)
    app.db.session.commit()
    return d


# ---- last_opened_at bumping ---------------------------------------

def test_deck_created_has_null_last_opened_at(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice, "French")
    assert app.db.session.get(app.Deck, d.id).last_opened_at is None


def test_get_deck_cards_bumps_last_opened_at(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice, "French")
    assert app.db.session.get(app.Deck, d.id).last_opened_at is None

    before = datetime.utcnow()
    r = client.get(f"/decks/{d.id}/cards")
    assert r.status_code == 200

    app.db.session.expire_all()
    ts = app.db.session.get(app.Deck, d.id).last_opened_at
    assert ts is not None
    assert ts >= before - timedelta(seconds=2)


def test_post_deck_cards_does_not_bump_last_opened_at(client, invite, app):
    """POST to /decks/<id>/cards creates a card — that's not 'opening'."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice, "French")

    r = client.post(f"/decks/{d.id}/cards",
                    data={"question": "q", "answer": "a", "submit": "Add card"})
    assert r.status_code in (200, 302)
    app.db.session.expire_all()
    assert app.db.session.get(app.Deck, d.id).last_opened_at is None


def test_repeated_opens_update_last_opened_at(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice, "French")

    client.get(f"/decks/{d.id}/cards")
    app.db.session.expire_all()
    first = app.db.session.get(app.Deck, d.id).last_opened_at
    assert first is not None

    # Force a small delta.
    import time
    time.sleep(1.1)
    client.get(f"/decks/{d.id}/cards")
    app.db.session.expire_all()
    second = app.db.session.get(app.Deck, d.id).last_opened_at
    assert second > first


# ---- home() surface ------------------------------------------------

def test_home_has_no_recently_opened_section(client, invite, app):
    """The 'Recently opened' section is gone; the home page is folder-first."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice, "French")
    client.get(f"/decks/{d.id}/cards")   # bump last_opened_at
    r = client.get("/home")
    assert b"Recently opened" not in r.data
    assert b"French" not in r.data        # deck surfaces only inside its folder


def test_home_shows_unfiled_tile_with_count(client, invite, app):
    """Unfiled is a first-class tile on home so orphaned decks stay reachable."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck(app, alice, "Loose")
    r = client.get("/home")
    assert r.status_code == 200
    assert b"Unfiled" in r.data
    assert b"1 deck" in r.data


def test_home_has_new_folder_link(client, invite):
    """Home page exposes an entry point to the new-folder form."""
    _register(client, invite, "alice")
    r = client.get("/home")
    assert r.status_code == 200
    body = r.data.decode()
    assert "/folders/new" in body


def test_home_has_no_new_deck_entry_point(client, invite):
    """Deck creation lives inside a folder; home must not offer it."""
    _register(client, invite, "alice")
    r = client.get("/home")
    assert r.status_code == 200
    assert b"New deck" not in r.data
