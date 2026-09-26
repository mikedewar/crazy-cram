"""M4 tests — last_opened_at bump + landing 'Recently opened' section.

The 'open a deck' event is GET /decks/<id>/cards. POST there is card
creation and MUST NOT bump last_opened_at.
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


# ---- home() 'Recently opened' section ------------------------------

def test_home_never_opened_deck_not_in_recent(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck(app, alice, "NeverOpened")
    r = client.get("/home")
    # Deck exists but shouldn't be listed under Recently opened.
    # It still contributes to Unfiled's count.
    assert b"Recently opened" not in r.data
    assert b"NeverOpened" not in r.data
    assert b"1 deck" in r.data  # Unfiled count


def test_home_recent_orders_by_last_opened_desc(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    a = _mk_deck(app, alice, "First")
    b = _mk_deck(app, alice, "Second")
    c = _mk_deck(app, alice, "Third")

    # Open in order a, b, c → most-recent first should be c, b, a
    import time
    client.get(f"/decks/{a.id}/cards"); time.sleep(1.05)
    client.get(f"/decks/{b.id}/cards"); time.sleep(1.05)
    client.get(f"/decks/{c.id}/cards")

    r = client.get("/home")
    body = r.data.decode()
    pos_first = body.find("First")
    pos_second = body.find("Second")
    pos_third = body.find("Third")
    assert pos_third < pos_second < pos_first


def test_home_recent_caps_at_5(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()

    import time
    for i in range(7):
        d = _mk_deck(app, alice, f"D{i}")
        client.get(f"/decks/{d.id}/cards")
        time.sleep(1.05)

    r = client.get("/home")
    body = r.data.decode()
    # 5 most-recent (D2..D6) present; older two (D0, D1) not.
    for i in range(2, 7):
        assert f"D{i}" in body
    # Strip folder chips from consideration — none named D0/D1 exist.
    assert "D0" not in body
    assert "D1" not in body


def test_home_recent_shows_folder_chip(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    f = app.Folder(user_id=alice.id, name="Languages")
    app.db.session.add(f)
    app.db.session.commit()
    d = _mk_deck(app, alice, "French", folder_id=f.id)
    client.get(f"/decks/{d.id}/cards")
    r = client.get("/home")
    assert b"Recently opened" in r.data
    assert b"Languages" in r.data
    assert b"folder-chip" in r.data


def test_home_recent_unfiled_deck_shows_unfiled_chip(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice, "Loose")
    client.get(f"/decks/{d.id}/cards")
    r = client.get("/home")
    assert b"Recently opened" in r.data
    body = r.data.decode()
    # 'Unfiled' appears at least twice — once in the Folders list, once as the chip.
    assert body.count("Unfiled") >= 2


def test_home_recent_excludes_other_users_decks(client, invite, app):
    _register(client, invite, "alice", "correct-horse-1")
    client.post("/logout")
    _register(client, invite, "bob", "correct-horse-2")
    client.post("/logout")

    alice = app.User.query.filter_by(username="alice").one()
    bob = app.User.query.filter_by(username="bob").one()

    bd = _mk_deck(app, bob, "BobsSecret")
    # Bob opens his own deck
    _login(client, "bob", "correct-horse-2")
    client.get(f"/decks/{bd.id}/cards")
    client.post("/logout")

    _login(client, "alice", "correct-horse-1")
    r = client.get("/home")
    assert b"BobsSecret" not in r.data
