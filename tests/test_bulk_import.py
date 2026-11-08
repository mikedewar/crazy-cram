"""Bulk Import — paste Q/A columns, create one card per paired line."""


def _register(client, invite, username="alice", password="correct-horse-1"):
    code = invite()
    return client.post("/register", data={
        "invite_code": code, "username": username,
        "password": password, "confirm": password,
        "submit": "Create account",
    })


def _mk_deck(app, user_id, name="French"):
    d = app.Deck(user_id=user_id, name=name)
    app.db.session.add(d)
    app.db.session.commit()
    return d


def _post_bulk(client, deck_id, questions, answers):
    return client.post(
        f"/decks/{deck_id}/cards/bulk-import",
        data={"questions": questions, "answers": answers, "submit": "Import"},
        follow_redirects=False,
    )


# ---- Button + page render --------------------------------------------

def test_bulk_import_button_rendered_on_card_list(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = client.get(f"/decks/{d.id}/cards")
    assert r.status_code == 200
    assert b"Bulk Import" in r.data
    assert f"/decks/{d.id}/cards/bulk-import".encode() in r.data


def test_bulk_import_page_renders(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id, "Spanish")
    r = client.get(f"/decks/{d.id}/cards/bulk-import")
    assert r.status_code == 200
    assert b"Bulk Import" in r.data
    assert b"Spanish" in r.data
    assert b"id=\"bi-questions\"" in r.data
    assert b"id=\"bi-answers\"" in r.data


def test_bulk_import_requires_login(client):
    r = client.get("/decks/1/cards/bulk-import", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_bulk_import_other_users_deck_404(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    client.post("/logout")
    _register(client, invite, "bob")
    assert client.get(f"/decks/{d.id}/cards/bulk-import").status_code == 404
    assert _post_bulk(client, d.id, "x", "y").status_code == 404


def test_bulk_import_published_deck_blocked(client, invite, app):
    from datetime import datetime, timezone
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    d.published_at = datetime.now(timezone.utc)
    app.db.session.commit()
    r = client.get(f"/decks/{d.id}/cards/bulk-import", follow_redirects=False)
    assert r.status_code in (302, 403, 410)


# ---- Happy path ------------------------------------------------------

def test_bulk_import_happy_path(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)

    r = _post_bulk(
        client, d.id,
        questions="chat\nchien\nchevre",
        answers="cat\ndog\ngoat",
    )
    assert r.status_code == 302
    assert f"/decks/{d.id}/cards" in r.headers["Location"]

    cards = app.Card.query.filter_by(deck_id=d.id).order_by(app.Card.id.asc()).all()
    assert [(c.question, c.answer) for c in cards] == [
        ("chat", "cat"), ("chien", "dog"), ("chevre", "goat"),
    ]


def test_bulk_import_blank_lines_tolerated(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)

    r = _post_bulk(
        client, d.id,
        questions="\n\nchat\n\nchien\n\n",
        answers="cat\n\n\ndog\n",
    )
    assert r.status_code == 302
    cards = app.Card.query.filter_by(deck_id=d.id).order_by(app.Card.id.asc()).all()
    assert [(c.question, c.answer) for c in cards] == [("chat", "cat"), ("chien", "dog")]


def test_bulk_import_trims_whitespace(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)

    r = _post_bulk(client, d.id, questions="  chat  ", answers="\tcat\t")
    assert r.status_code == 302
    c = app.Card.query.filter_by(deck_id=d.id).one()
    assert (c.question, c.answer) == ("chat", "cat")


# ---- Validation ------------------------------------------------------

def test_bulk_import_mismatched_counts_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)

    r = _post_bulk(client, d.id, questions="a\nb\nc", answers="1\n2")
    assert r.status_code == 200
    assert b"Mismatched line counts" in r.data
    assert app.Card.query.filter_by(deck_id=d.id).count() == 0


def test_bulk_import_empty_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)

    r = _post_bulk(client, d.id, questions="", answers="")
    assert r.status_code == 200
    assert app.Card.query.filter_by(deck_id=d.id).count() == 0


def test_bulk_import_only_blanks_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)

    r = _post_bulk(client, d.id, questions="\n\n", answers="\n\n")
    assert r.status_code == 200
    assert app.Card.query.filter_by(deck_id=d.id).count() == 0


def test_bulk_import_over_length_row_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    long_q = "x" * (app.CARD_SIDE_MAX + 1)

    r = _post_bulk(client, d.id, questions=f"ok\n{long_q}", answers="a\nb")
    assert r.status_code == 200
    assert b"character limit" in r.data
    assert app.Card.query.filter_by(deck_id=d.id).count() == 0


def test_bulk_import_over_max_rows_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    n = app.BULK_IMPORT_MAX_ROWS + 1
    qs = "\n".join(f"q{i}" for i in range(n))
    as_ = "\n".join(f"a{i}" for i in range(n))

    r = _post_bulk(client, d.id, questions=qs, answers=as_)
    assert r.status_code == 200
    assert b"Too many rows" in r.data
    assert app.Card.query.filter_by(deck_id=d.id).count() == 0


def test_bulk_import_at_max_rows_succeeds(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    n = app.BULK_IMPORT_MAX_ROWS
    qs = "\n".join(f"q{i}" for i in range(n))
    as_ = "\n".join(f"a{i}" for i in range(n))

    r = _post_bulk(client, d.id, questions=qs, answers=as_)
    assert r.status_code == 302
    assert app.Card.query.filter_by(deck_id=d.id).count() == n
