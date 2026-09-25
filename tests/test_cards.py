"""M3 tests — Card CRUD + cross-user isolation + cascade."""


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


def _mk_deck(app, user_id, name="French"):
    d = app.Deck(user_id=user_id, name=name)
    app.db.session.add(d)
    app.db.session.commit()
    return d


def _register_two_users(app, client, invite):
    _register(client, invite, "alice", "correct-horse-1")
    client.post("/logout")
    _register(client, invite, "bob", "correct-horse-2")
    client.post("/logout")
    alice = app.User.query.filter_by(username="alice").one()
    bob = app.User.query.filter_by(username="bob").one()
    return alice, bob


# ---- Card-list page --------------------------------------------------

def test_card_list_page_renders_empty(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id, "French")
    r = client.get(f"/decks/{d.id}/cards")
    assert r.status_code == 200
    assert b"French" in r.data
    assert b"Cards (0)" in r.data
    assert b"no cards yet" in r.data
    assert b"Add a card" in r.data


def test_card_list_page_shows_cards(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    app.db.session.add(app.Card(deck_id=d.id, question="chat", answer="cat"))
    app.db.session.add(app.Card(deck_id=d.id, question="chien", answer="dog"))
    app.db.session.commit()

    r = client.get(f"/decks/{d.id}/cards")
    assert r.status_code == 200
    assert b"Cards (2)" in r.data
    assert b"chat" in r.data
    assert b"cat" in r.data
    assert b"chien" in r.data
    assert b"dog" in r.data


def test_card_list_requires_login(client):
    r = client.get("/decks/1/cards", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_card_list_on_nonexistent_deck_404(client, invite):
    _register(client, invite, "alice")
    assert client.get("/decks/9999/cards").status_code == 404


# ---- Create ----------------------------------------------------------

def test_add_card_happy_path(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = client.post(f"/decks/{d.id}/cards",
                    data={"question": "chat", "answer": "cat", "submit": "Save card"},
                    follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/decks/{d.id}/cards")
    assert app.Card.query.filter_by(deck_id=d.id).count() == 1
    c = app.Card.query.first()
    assert c.question == "chat"
    assert c.answer == "cat"


def test_add_card_requires_question(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = client.post(f"/decks/{d.id}/cards",
                    data={"question": "", "answer": "cat", "submit": "Save card"})
    assert r.status_code == 200
    assert b"field is required" in r.data.lower()
    assert app.Card.query.count() == 0


def test_add_card_requires_answer(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = client.post(f"/decks/{d.id}/cards",
                    data={"question": "chat", "answer": "", "submit": "Save card"})
    assert r.status_code == 200
    assert b"field is required" in r.data.lower()
    assert app.Card.query.count() == 0


def test_add_card_strips_whitespace(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    client.post(f"/decks/{d.id}/cards",
                data={"question": "  chat  ", "answer": "\n cat \t",
                      "submit": "Save card"})
    c = app.Card.query.first()
    assert c.question == "chat"
    assert c.answer == "cat"


def test_add_card_accepts_500_char_boundary(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    long_side = "x" * 500
    r = client.post(f"/decks/{d.id}/cards",
                    data={"question": long_side, "answer": long_side,
                          "submit": "Save card"},
                    follow_redirects=False)
    assert r.status_code == 302
    assert app.Card.query.count() == 1


def test_add_card_rejects_over_500(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = client.post(f"/decks/{d.id}/cards",
                    data={"question": "x" * 501, "answer": "a",
                          "submit": "Save card"})
    assert r.status_code == 200
    assert b"500" in r.data
    assert app.Card.query.count() == 0


# ---- Edit ------------------------------------------------------------

def test_edit_card_happy_path(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    c = app.Card(deck_id=d.id, question="q1", answer="a1")
    app.db.session.add(c)
    app.db.session.commit()

    r = client.post(f"/cards/{c.id}/edit",
                    data={"question": "q2", "answer": "a2", "submit": "Save card"},
                    follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/decks/{d.id}/cards")
    fresh = app.db.session.get(app.Card, c.id)
    assert fresh.question == "q2"
    assert fresh.answer == "a2"


def test_edit_card_page_prefills(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    c = app.Card(deck_id=d.id, question="original-q", answer="original-a")
    app.db.session.add(c)
    app.db.session.commit()
    r = client.get(f"/cards/{c.id}/edit")
    assert r.status_code == 200
    assert b"original-q" in r.data
    assert b"original-a" in r.data


def test_edit_nonexistent_card_404(client, invite):
    _register(client, invite, "alice")
    assert client.get("/cards/9999/edit").status_code == 404
    assert client.post("/cards/9999/edit",
                       data={"question": "q", "answer": "a",
                             "submit": "Save card"}).status_code == 404


# ---- Delete ----------------------------------------------------------

def test_delete_card_happy_path(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    c = app.Card(deck_id=d.id, question="q", answer="a")
    app.db.session.add(c)
    app.db.session.commit()
    c_id = c.id

    r = client.post(f"/cards/{c_id}/delete", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/decks/{d.id}/cards")
    assert app.db.session.get(app.Card, c_id) is None


def test_delete_card_get_not_allowed(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    c = app.Card(deck_id=d.id, question="q", answer="a")
    app.db.session.add(c)
    app.db.session.commit()
    r = client.get(f"/cards/{c.id}/delete")
    assert r.status_code == 405  # method not allowed
    assert app.db.session.get(app.Card, c.id) is not None


def test_delete_nonexistent_card_404(client, invite):
    _register(client, invite, "alice")
    assert client.post("/cards/9999/delete").status_code == 404


# ---- Cascade ---------------------------------------------------------

def test_deleting_deck_via_route_cascades_cards(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id, "Doomed")
    app.db.session.add(app.Card(deck_id=d.id, question="q1", answer="a1"))
    app.db.session.add(app.Card(deck_id=d.id, question="q2", answer="a2"))
    app.db.session.commit()
    assert app.Card.query.count() == 2

    r = client.post(f"/decks/{d.id}/delete")
    assert r.status_code == 302
    assert app.Card.query.count() == 0


# ---- Cross-user isolation -------------------------------------------

def test_alice_cannot_list_cards_in_bobs_deck(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    bobs = _mk_deck(app, bob.id, "BobsDeck")
    app.db.session.add(app.Card(deck_id=bobs.id, question="secret", answer="also-secret"))
    app.db.session.commit()

    _login(client, "alice", "correct-horse-1")
    r = client.get(f"/decks/{bobs.id}/cards")
    assert r.status_code == 404


def test_alice_cannot_add_cards_to_bobs_deck(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    bobs = _mk_deck(app, bob.id, "BobsDeck")

    _login(client, "alice", "correct-horse-1")
    r = client.post(f"/decks/{bobs.id}/cards",
                    data={"question": "hack", "answer": "hack", "submit": "Save card"})
    assert r.status_code == 404
    assert app.Card.query.count() == 0


def test_alice_cannot_edit_bobs_card(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    bobs = _mk_deck(app, bob.id, "BobsDeck")
    bobs_card = app.Card(deck_id=bobs.id, question="orig-q", answer="orig-a")
    app.db.session.add(bobs_card)
    app.db.session.commit()

    _login(client, "alice", "correct-horse-1")
    assert client.get(f"/cards/{bobs_card.id}/edit").status_code == 404
    r = client.post(f"/cards/{bobs_card.id}/edit",
                    data={"question": "hijack", "answer": "hijack",
                          "submit": "Save card"})
    assert r.status_code == 404
    fresh = app.db.session.get(app.Card, bobs_card.id)
    assert fresh.question == "orig-q"


def test_alice_cannot_delete_bobs_card(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    bobs = _mk_deck(app, bob.id, "BobsDeck")
    bobs_card = app.Card(deck_id=bobs.id, question="q", answer="a")
    app.db.session.add(bobs_card)
    app.db.session.commit()
    bobs_card_id = bobs_card.id

    _login(client, "alice", "correct-horse-1")
    r = client.post(f"/cards/{bobs_card_id}/delete")
    assert r.status_code == 404
    assert app.db.session.get(app.Card, bobs_card_id) is not None
