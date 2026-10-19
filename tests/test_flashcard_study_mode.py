"""Flashcard-study-mode tests.

Mode is a third radio on /decks/N/study (Flashcards). Any card count >= 1
is valid. The study view shows a flip card (question → tap/space flips →
answer) with Right/Wrong buttons; the choice is recorded as is_correct and
student_answer stays NULL.
"""


def _register(client, invite, username="alice", password="correct-horse-1"):
    code = invite()
    return client.post("/register", data={
        "invite_code": code, "username": username,
        "password": password, "confirm": password,
        "submit": "Create account",
    })


def _mk_deck_with_cards(app, user_id, n, name="French"):
    d = app.Deck(user_id=user_id, name=name)
    app.db.session.add(d)
    app.db.session.flush()
    for i in range(n):
        app.db.session.add(app.Card(deck_id=d.id,
                                    question=f"q{i}", answer=f"a{i}"))
    app.db.session.commit()
    return d


def _start_flashcard_session(client, deck_id, n_cards):
    r = client.post(
        f"/decks/{deck_id}/study",
        data={"mode": "flashcard", "n_cards": n_cards, "order": "created",
              "submit": "Start"},
    )
    assert r.status_code == 302, r.data
    return r.headers["Location"]


# ---- Config page offers the Flashcards radio -----------------------

def test_config_page_shows_flashcards_radio(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 1)
    deck = app.Deck.query.filter_by(user_id=alice.id).one()

    r = client.get(f"/decks/{deck.id}/study")
    body = r.data.decode()
    assert r.status_code == 200
    assert 'value="flashcard"' in body
    assert "Flashcards" in body


def test_flashcard_radio_enabled_at_one_card(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 1)
    deck = app.Deck.query.filter_by(user_id=alice.id).one()

    r = client.get(f"/decks/{deck.id}/study")
    body = r.data.decode()
    # The flashcard radio must not be rendered with the disabled attribute.
    # (MC on a 1-card deck would be; flashcard never is.)
    assert 'value="flashcard"' in body
    # Crude but good enough: ensure the disabled MC pattern isn't being
    # applied to flashcard.
    assert 'value="flashcard" disabled' not in body


# ---- Starting a flashcard session renders the flashcard view --------

def test_start_flashcard_session_renders_flip_card(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 3)
    deck = app.Deck.query.filter_by(user_id=alice.id).one()

    loc = _start_flashcard_session(client, deck.id, 3)
    r = client.get(loc)
    body = r.data.decode()
    assert r.status_code == 200
    assert "flashcard-stage" in body
    assert "flashcard-front" in body
    assert "flashcard-back" in body
    # First card's question + answer should both be in the DOM (both faces rendered).
    assert "q0" in body
    assert "a0" in body
    # Grade buttons both present.
    assert 'name="self_grade" value="wrong"' in body
    assert 'name="self_grade" value="right"' in body
    # Written-mode text input must NOT render.
    assert 'name="answer"' not in body
    # Hint mentions Space.
    assert "Space" in body


def test_flashcard_session_db_shape(app, client, invite):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 3)
    deck = app.Deck.query.filter_by(user_id=alice.id).one()
    _start_flashcard_session(client, deck.id, 3)
    s = app.StudySession.query.filter_by(deck_id=deck.id).one()
    assert s.mode == "flashcard"
    assert s.n_cards == 3
    assert len(s.attempts) == 3


# ---- Submitting self-grades ----------------------------------------

def _attempt_id_for_next_card(app, session_id):
    att = (
        app.StudyAttempt.query
        .filter_by(session_id=session_id, is_correct=None)
        .order_by(app.StudyAttempt.position.asc())
        .first()
    )
    return att.id if att else None


def test_right_grade_records_correct_true(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 2)
    deck = app.Deck.query.filter_by(user_id=alice.id).one()
    _start_flashcard_session(client, deck.id, 2)
    s = app.StudySession.query.filter_by(deck_id=deck.id).one()
    aid = _attempt_id_for_next_card(app, s.id)
    r = client.post(
        f"/sessions/{s.id}/submit",
        data={"attempt_id": aid, "self_grade": "right"},
    )
    assert r.status_code == 302
    att = app.db.session.get(app.StudyAttempt, aid)
    assert att.is_correct is True
    assert att.student_answer is None
    assert att.attempted_at is not None


def test_wrong_grade_records_correct_false(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 2)
    deck = app.Deck.query.filter_by(user_id=alice.id).one()
    _start_flashcard_session(client, deck.id, 2)
    s = app.StudySession.query.filter_by(deck_id=deck.id).one()
    aid = _attempt_id_for_next_card(app, s.id)
    r = client.post(
        f"/sessions/{s.id}/submit",
        data={"attempt_id": aid, "self_grade": "wrong"},
    )
    assert r.status_code == 302
    att = app.db.session.get(app.StudyAttempt, aid)
    assert att.is_correct is False
    assert att.student_answer is None


def test_missing_self_grade_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 2)
    deck = app.Deck.query.filter_by(user_id=alice.id).one()
    _start_flashcard_session(client, deck.id, 2)
    s = app.StudySession.query.filter_by(deck_id=deck.id).one()
    aid = _attempt_id_for_next_card(app, s.id)
    r = client.post(
        f"/sessions/{s.id}/submit",
        data={"attempt_id": aid},
    )
    assert r.status_code == 400


def test_bogus_self_grade_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 2)
    deck = app.Deck.query.filter_by(user_id=alice.id).one()
    _start_flashcard_session(client, deck.id, 2)
    s = app.StudySession.query.filter_by(deck_id=deck.id).one()
    aid = _attempt_id_for_next_card(app, s.id)
    r = client.post(
        f"/sessions/{s.id}/submit",
        data={"attempt_id": aid, "self_grade": "maybe"},
    )
    assert r.status_code == 400


# ---- End-to-end session + results ---------------------------------

def test_full_flashcard_session_finishes_and_scores(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 3)
    deck = app.Deck.query.filter_by(user_id=alice.id).one()
    _start_flashcard_session(client, deck.id, 3)
    s = app.StudySession.query.filter_by(deck_id=deck.id).one()

    # 2 right, 1 wrong.
    grades = ["right", "wrong", "right"]
    for g in grades:
        aid = _attempt_id_for_next_card(app, s.id)
        assert aid is not None
        client.post(f"/sessions/{s.id}/submit",
                    data={"attempt_id": aid, "self_grade": g})

    app.db.session.refresh(s)
    assert s.finished_at is not None
    assert s.score == 2

    r = client.get(f"/sessions/{s.id}/results")
    body = r.data.decode()
    assert r.status_code == 200
    assert "2 / 3" in body
    assert "Got it right" in body
    assert "Got it wrong" in body


# ---- Restart carries flashcard mode -------------------------------

def test_restart_preserves_flashcard_mode(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 2)
    deck = app.Deck.query.filter_by(user_id=alice.id).one()
    _start_flashcard_session(client, deck.id, 2)
    s = app.StudySession.query.filter_by(deck_id=deck.id).one()
    for _ in range(2):
        aid = _attempt_id_for_next_card(app, s.id)
        client.post(f"/sessions/{s.id}/submit",
                    data={"attempt_id": aid, "self_grade": "right"})

    r = client.post(f"/sessions/{s.id}/restart")
    assert r.status_code == 302
    new = (
        app.StudySession.query
        .filter_by(deck_id=deck.id)
        .order_by(app.StudySession.id.desc())
        .first()
    )
    assert new.id != s.id
    assert new.mode == "flashcard"


# ---- Cross-user isolation (404) -----------------------------------

def test_other_user_cannot_submit_flashcard_grade(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 2)
    deck = app.Deck.query.filter_by(user_id=alice.id).one()
    _start_flashcard_session(client, deck.id, 2)
    s = app.StudySession.query.filter_by(deck_id=deck.id).one()
    aid = _attempt_id_for_next_card(app, s.id)

    client.post("/logout")
    _register(client, invite, "bob")

    r = client.post(f"/sessions/{s.id}/submit",
                    data={"attempt_id": aid, "self_grade": "right"})
    assert r.status_code == 404
