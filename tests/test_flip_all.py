"""Flip All Cards — swap question/answer across every card in a deck."""


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


def test_flip_all_swaps_every_card(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    app.db.session.add(app.Card(deck_id=d.id, question="chat", answer="cat"))
    app.db.session.add(app.Card(deck_id=d.id, question="chien", answer="dog"))
    app.db.session.commit()

    r = client.post(f"/decks/{d.id}/flip-all", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/decks/{d.id}/cards")

    cards = app.Card.query.filter_by(deck_id=d.id).order_by(app.Card.id.asc()).all()
    assert (cards[0].question, cards[0].answer) == ("cat", "chat")
    assert (cards[1].question, cards[1].answer) == ("dog", "chien")


def test_flip_all_persists_across_requests(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    app.db.session.add(app.Card(deck_id=d.id, question="chat", answer="cat"))
    app.db.session.commit()

    client.post(f"/decks/{d.id}/flip-all")
    r = client.get(f"/decks/{d.id}/cards")
    assert r.status_code == 200
    body = r.data.decode()
    # The Q/A labels sit in separate spans; check the swapped text appears
    # next to the Q label by looking at document order.
    q_idx = body.find(">Q<")
    a_idx = body.find(">A<")
    assert q_idx < body.find("cat") < a_idx
    assert a_idx < body.find("chat")


def test_flip_all_empty_deck_no_error(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = client.post(f"/decks/{d.id}/flip-all", follow_redirects=False)
    assert r.status_code == 302


def test_flip_all_get_not_allowed(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    assert client.get(f"/decks/{d.id}/flip-all").status_code == 405


def test_flip_all_nonexistent_deck_404(client, invite):
    _register(client, invite, "alice")
    assert client.post("/decks/9999/flip-all").status_code == 404


def test_flip_all_published_deck_returns_403(client, invite, app):
    from datetime import datetime, timezone
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    app.db.session.add(app.Card(deck_id=d.id, question="chat", answer="cat"))
    d.published_at = datetime.now(timezone.utc)
    app.db.session.commit()

    r = client.post(f"/decks/{d.id}/flip-all")
    assert r.status_code == 403
    c = app.Card.query.filter_by(deck_id=d.id).one()
    assert (c.question, c.answer) == ("chat", "cat")


def test_alice_cannot_flip_bobs_deck(client, invite, app):
    _register(client, invite, "alice", "correct-horse-1")
    client.post("/logout")
    _register(client, invite, "bob", "correct-horse-2")
    alice = app.User.query.filter_by(username="alice").one()
    bob = app.User.query.filter_by(username="bob").one()
    bobs = _mk_deck(app, bob.id, "BobsDeck")
    app.db.session.add(app.Card(deck_id=bobs.id, question="q", answer="a"))
    app.db.session.commit()
    bobs_deck_id = bobs.id

    client.post("/logout")
    _login(client, "alice", "correct-horse-1")
    r = client.post(f"/decks/{bobs_deck_id}/flip-all")
    assert r.status_code == 404
    c = app.Card.query.filter_by(deck_id=bobs_deck_id).one()
    assert (c.question, c.answer) == ("q", "a")


def test_flip_all_button_present_when_cards_exist(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    app.db.session.add(app.Card(deck_id=d.id, question="q", answer="a"))
    app.db.session.commit()
    r = client.get(f"/decks/{d.id}/cards")
    assert r.status_code == 200
    assert b"Flip All Cards" in r.data
    assert f"/decks/{d.id}/flip-all".encode() in r.data


def test_flip_all_button_hidden_when_no_cards(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = client.get(f"/decks/{d.id}/cards")
    assert r.status_code == 200
    assert b"Flip All Cards" not in r.data


def test_flip_all_button_hidden_on_published_deck(client, invite, app):
    from datetime import datetime, timezone
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    app.db.session.add(app.Card(deck_id=d.id, question="q", answer="a"))
    d.published_at = datetime.now(timezone.utc)
    app.db.session.commit()
    r = client.get(f"/decks/{d.id}/cards")
    assert r.status_code == 200
    assert b"Flip All Cards" not in r.data
