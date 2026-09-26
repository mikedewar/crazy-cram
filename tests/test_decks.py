"""M2 tests — Deck CRUD + cross-user isolation + home rendering."""


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


def _register_two_users(app, client, invite):
    _register(client, invite, "alice", "correct-horse-1")
    client.post("/logout")
    _register(client, invite, "bob", "correct-horse-2")
    client.post("/logout")
    alice = app.User.query.filter_by(username="alice").one()
    bob = app.User.query.filter_by(username="bob").one()
    return alice, bob


# ---- Home (empty state + populated) ----------------------------------

def test_home_empty_state_shows_prompt(client, invite):
    _register(client, invite, "alice")
    r = client.get("/home")
    assert r.status_code == 200
    assert b"don" in r.data and b"any decks" in r.data
    assert b"New deck" in r.data


def test_home_lists_recently_opened_decks_with_card_counts(client, invite, app):
    """Under the folders redesign, home's deck list is 'Recently opened' —
    only decks the user has actually opened (last_opened_at IS NOT NULL)."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d1 = app.Deck(user_id=alice.id, name="French")
    d2 = app.Deck(user_id=alice.id, name="Capitals")
    app.db.session.add_all([d1, d2])
    app.db.session.commit()
    app.db.session.add(app.Card(deck_id=d1.id, question="chat", answer="cat"))
    app.db.session.add(app.Card(deck_id=d1.id, question="chien", answer="dog"))
    app.db.session.commit()

    # Simulate opening both decks (bumps last_opened_at).
    client.get(f"/decks/{d1.id}/cards")
    client.get(f"/decks/{d2.id}/cards")

    r = client.get("/home")
    assert r.status_code == 200
    assert b"French" in r.data
    assert b"Capitals" in r.data
    assert b"2 cards" in r.data       # French
    assert b"0 cards" in r.data       # Capitals


def test_home_singular_card_count(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = app.Deck(user_id=alice.id, name="Solo")
    app.db.session.add(d)
    app.db.session.commit()
    app.db.session.add(app.Card(deck_id=d.id, question="q", answer="a"))
    app.db.session.commit()

    client.get(f"/decks/{d.id}/cards")   # open it so it surfaces on home
    r = client.get("/home")
    assert b"1 card" in r.data
    assert b"1 cards" not in r.data


# ---- Create ----------------------------------------------------------

def test_create_deck_happy_path(client, invite, app):
    _register(client, invite, "alice")
    r = client.post("/decks/new", data={"name": "French", "submit": "Save deck"},
                    follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/home")

    alice = app.User.query.filter_by(username="alice").one()
    assert app.Deck.query.filter_by(user_id=alice.id).count() == 1
    assert app.Deck.query.first().name == "French"


def test_create_deck_requires_name(client, invite):
    _register(client, invite, "alice")
    r = client.post("/decks/new", data={"name": "", "submit": "Save deck"})
    assert r.status_code == 200
    assert b"This field is required" in r.data or b"field is required" in r.data.lower()


def test_create_deck_strips_whitespace(client, invite, app):
    _register(client, invite, "alice")
    client.post("/decks/new", data={"name": "  French  ", "submit": "Save deck"})
    assert app.Deck.query.first().name == "French"


def test_create_deck_rejects_over_120_chars(client, invite, app):
    _register(client, invite, "alice")
    r = client.post("/decks/new",
                    data={"name": "x" * 121, "submit": "Save deck"})
    assert r.status_code == 200
    # WTForms Length error message contains the max value
    assert b"120" in r.data
    assert app.Deck.query.count() == 0


def test_create_deck_accepts_exactly_120_chars(client, invite, app):
    _register(client, invite, "alice")
    r = client.post("/decks/new",
                    data={"name": "x" * 120, "submit": "Save deck"},
                    follow_redirects=False)
    assert r.status_code == 302
    assert app.Deck.query.count() == 1


def test_create_deck_requires_login(client):
    r = client.post("/decks/new", data={"name": "French", "submit": "Save deck"},
                    follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_new_deck_page_requires_login(client):
    r = client.get("/decks/new", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


# ---- Rename ---------------------------------------------------------

def test_rename_deck_happy_path(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = app.Deck(user_id=alice.id, name="Old")
    app.db.session.add(d)
    app.db.session.commit()

    r = client.post(f"/decks/{d.id}/edit",
                    data={"name": "New", "submit": "Save deck"},
                    follow_redirects=False)
    assert r.status_code == 302
    assert app.db.session.get(app.Deck, d.id).name == "New"


def test_edit_page_prefills_current_name(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = app.Deck(user_id=alice.id, name="French")
    app.db.session.add(d)
    app.db.session.commit()
    r = client.get(f"/decks/{d.id}/edit")
    assert r.status_code == 200
    assert b'value="French"' in r.data


def test_edit_nonexistent_deck_404(client, invite):
    _register(client, invite, "alice")
    assert client.get("/decks/9999/edit").status_code == 404
    assert client.post("/decks/9999/edit",
                       data={"name": "x", "submit": "Save deck"}).status_code == 404


# ---- Delete ----------------------------------------------------------

def test_delete_deck_happy_path(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = app.Deck(user_id=alice.id, name="Gone")
    app.db.session.add(d)
    app.db.session.commit()
    d_id = d.id

    r = client.post(f"/decks/{d_id}/delete", follow_redirects=False)
    assert r.status_code == 302
    assert app.db.session.get(app.Deck, d_id) is None


def test_delete_get_shows_confirmation_page(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = app.Deck(user_id=alice.id, name="ConfirmMe")
    app.db.session.add(d)
    app.db.session.commit()

    r = client.get(f"/decks/{d.id}/delete")
    assert r.status_code == 200
    assert b"ConfirmMe" in r.data
    assert b"Delete deck" in r.data
    assert app.db.session.get(app.Deck, d.id) is not None  # not yet gone


def test_delete_nonexistent_deck_404(client, invite):
    _register(client, invite, "alice")
    assert client.get("/decks/9999/delete").status_code == 404
    assert client.post("/decks/9999/delete").status_code == 404


def test_delete_cascades_to_cards(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = app.Deck(user_id=alice.id, name="Doomed")
    app.db.session.add(d)
    app.db.session.commit()
    app.db.session.add(app.Card(deck_id=d.id, question="q", answer="a"))
    app.db.session.commit()
    assert app.Card.query.count() == 1

    client.post(f"/decks/{d.id}/delete")
    assert app.Card.query.count() == 0


# ---- Cross-user isolation -------------------------------------------

def test_alice_cannot_see_bobs_deck_on_home(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    app.db.session.add(app.Deck(user_id=bob.id, name="BobsSecret"))
    app.db.session.commit()

    _login(client, "alice", "correct-horse-1")
    r = client.get("/home")
    assert r.status_code == 200
    assert b"BobsSecret" not in r.data


def test_alice_cannot_edit_bobs_deck(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    bobs = app.Deck(user_id=bob.id, name="BobsSecret")
    app.db.session.add(bobs)
    app.db.session.commit()

    _login(client, "alice", "correct-horse-1")
    assert client.get(f"/decks/{bobs.id}/edit").status_code == 404
    r = client.post(f"/decks/{bobs.id}/edit",
                    data={"name": "hijacked", "submit": "Save deck"})
    assert r.status_code == 404
    # Bob's deck untouched
    assert app.db.session.get(app.Deck, bobs.id).name == "BobsSecret"


def test_alice_cannot_delete_bobs_deck(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    bobs = app.Deck(user_id=bob.id, name="BobsSecret")
    app.db.session.add(bobs)
    app.db.session.commit()
    bobs_id = bobs.id

    _login(client, "alice", "correct-horse-1")
    assert client.get(f"/decks/{bobs_id}/delete").status_code == 404
    assert client.post(f"/decks/{bobs_id}/delete").status_code == 404
    assert app.db.session.get(app.Deck, bobs_id) is not None


def test_two_students_can_have_same_deck_name(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)

    _login(client, "alice", "correct-horse-1")
    r1 = client.post("/decks/new", data={"name": "French", "submit": "Save deck"})
    assert r1.status_code == 302
    client.post("/logout")

    _login(client, "bob", "correct-horse-2")
    r2 = client.post("/decks/new", data={"name": "French", "submit": "Save deck"})
    assert r2.status_code == 302

    assert app.Deck.query.filter_by(name="French").count() == 2
