"""M5 tests — restart + edit-from-results round-trip."""
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


def _mk_deck_with_cards(app, user_id, n, name="French"):
    d = app.Deck(user_id=user_id, name=name)
    app.db.session.add(d)
    app.db.session.flush()
    for i in range(n):
        app.db.session.add(app.Card(deck_id=d.id,
                                    question=f"q{i}", answer=f"a{i}"))
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


def _start_session(client, app, deck_id, n, order="created"):
    r = client.post(f"/decks/{deck_id}/study",
                    data={"n_cards": n, "order": order, "submit": "Start"},
                    follow_redirects=False)
    return int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))


def _finish_session(client, app, sid, answers):
    """answers: dict position -> answer text."""
    for pos, ans in answers.items():
        a = app.StudyAttempt.query.filter_by(session_id=sid, position=pos).one()
        client.post(f"/sessions/{sid}/submit",
                    data={"attempt_id": a.id, "answer": ans})


# ---- Restart --------------------------------------------------------

def test_restart_creates_new_session_with_same_config(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 4)
    sid = _start_session(client, app, d.id, n=3, order="created")
    _finish_session(client, app, sid, {0: "a0", 1: "a1", 2: "wrong"})

    r = client.post(f"/sessions/{sid}/restart", follow_redirects=False)
    assert r.status_code == 302
    m = re.search(r"/sessions/(\d+)", r.headers["Location"])
    assert m
    new_sid = int(m.group(1))
    assert new_sid != sid

    new = app.db.session.get(app.StudySession, new_sid)
    old = app.db.session.get(app.StudySession, sid)
    assert new.user_id == alice.id
    assert new.deck_id == d.id
    assert new.n_cards == old.n_cards
    assert new.shuffled == old.shuffled
    assert new.finished_at is None
    assert new.score is None


def test_restart_has_fresh_empty_attempts(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 3)
    sid = _start_session(client, app, d.id, n=3)
    _finish_session(client, app, sid, {0: "a0", 1: "a1", 2: "a2"})

    r = client.post(f"/sessions/{sid}/restart", follow_redirects=False)
    new_sid = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))

    attempts = app.StudyAttempt.query.filter_by(session_id=new_sid).all()
    assert len(attempts) == 3
    for a in attempts:
        assert a.student_answer is None
        assert a.is_correct is None
        assert a.attempted_at is None

    # Old attempts untouched.
    old_attempts = app.StudyAttempt.query.filter_by(session_id=sid).all()
    assert all(a.is_correct is not None for a in old_attempts)


def test_restart_reflects_current_cards_not_old_snapshot(client, invite, app):
    """If Mike edits a card between sessions, restart should use the NEW answer."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 2)
    sid = _start_session(client, app, d.id, n=2)
    _finish_session(client, app, sid, {0: "a0", 1: "a1"})

    # Rewrite card 0's answer.
    a0 = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()
    card = app.db.session.get(app.Card, a0.card_id)
    card.answer = "corrected"
    app.db.session.commit()

    r = client.post(f"/sessions/{sid}/restart", follow_redirects=False)
    new_sid = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))

    # New attempt for position 0 must snapshot the corrected answer.
    new_first = app.StudyAttempt.query.filter_by(session_id=new_sid, position=0).one()
    assert new_first.card_snapshot_a == "corrected"


def test_restart_clamps_when_deck_shrinks(client, invite, app):
    """If cards were deleted since, restart uses min(old.n_cards, current)."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 5)
    sid = _start_session(client, app, d.id, n=5)
    _finish_session(client, app, sid, {i: f"a{i}" for i in range(5)})

    # Delete two cards.
    to_delete = app.Card.query.filter_by(deck_id=d.id).limit(2).all()
    for c in to_delete:
        app.db.session.delete(c)
    app.db.session.commit()

    r = client.post(f"/sessions/{sid}/restart", follow_redirects=False)
    new_sid = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))
    new = app.db.session.get(app.StudySession, new_sid)
    assert new.n_cards == 3
    assert app.StudyAttempt.query.filter_by(session_id=new_sid).count() == 3


def test_restart_on_now_empty_deck_flashes_and_returns(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 2)
    sid = _start_session(client, app, d.id, n=2)
    _finish_session(client, app, sid, {0: "a0", 1: "a1"})

    for c in app.Card.query.filter_by(deck_id=d.id).all():
        app.db.session.delete(c)
    app.db.session.commit()

    r = client.post(f"/sessions/{sid}/restart", follow_redirects=False)
    assert r.status_code == 302
    assert f"/decks/{d.id}/cards" in r.headers["Location"]
    # No new session created.
    assert app.StudySession.query.filter_by(deck_id=d.id).count() == 1


def test_restart_requires_login(client):
    r = client.post("/sessions/1/restart", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_alice_cannot_restart_bobs_session(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    _login(client, "bob", "correct-horse-2")
    d = _mk_deck_with_cards(app, bob.id, 2, "BobsDeck")
    sid = _start_session(client, app, d.id, n=2)
    _finish_session(client, app, sid, {0: "a0", 1: "a1"})
    client.post("/logout")

    _login(client, "alice", "correct-horse-1")
    r = client.post(f"/sessions/{sid}/restart", follow_redirects=False)
    assert r.status_code == 404
    # No leaked session created.
    assert app.StudySession.query.count() == 1


# ---- Edit from results ---------------------------------------------

def test_edit_card_with_return_to_redirects_to_results(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 2)
    sid = _start_session(client, app, d.id, n=2)
    _finish_session(client, app, sid, {0: "a0", 1: "wrong"})

    wrong = app.StudyAttempt.query.filter_by(session_id=sid, position=1).one()
    card_id = wrong.card_id

    r = client.post(f"/cards/{card_id}/edit?return_to={sid}",
                    data={"question": "q1", "answer": "corrected", "submit": "Save"},
                    follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/sessions/{sid}/results")


def test_edit_card_without_return_to_goes_to_cards(client, invite, app):
    """Sanity-check the default still works."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 1)
    card = app.Card.query.filter_by(deck_id=d.id).one()

    r = client.post(f"/cards/{card.id}/edit",
                    data={"question": "q0", "answer": "still-a0", "submit": "Save"},
                    follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/decks/{d.id}/cards")


def test_edit_from_results_preserves_historical_snapshot(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 2)
    sid = _start_session(client, app, d.id, n=2)
    _finish_session(client, app, sid, {0: "a0", 1: "wrong"})

    wrong = app.StudyAttempt.query.filter_by(session_id=sid, position=1).one()
    original_snap = wrong.card_snapshot_a
    card_id = wrong.card_id

    client.post(f"/cards/{card_id}/edit?return_to={sid}",
                data={"question": "q1", "answer": "corrected", "submit": "Save"})

    fresh = app.db.session.get(app.StudyAttempt, wrong.id)
    assert fresh.card_snapshot_a == original_snap
    assert fresh.is_correct is False  # historical result unchanged
    # But the card itself is updated.
    updated_card = app.db.session.get(app.Card, card_id)
    assert updated_card.answer == "corrected"


def test_edit_get_with_return_to_renders_form(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 2)
    sid = _start_session(client, app, d.id, n=2)
    _finish_session(client, app, sid, {0: "a0", 1: "wrong"})

    wrong = app.StudyAttempt.query.filter_by(session_id=sid, position=1).one()
    r = client.get(f"/cards/{wrong.card_id}/edit?return_to={sid}")
    assert r.status_code == 200
    # Form action should carry return_to so POST preserves it.
    assert f"return_to={sid}".encode() in r.data


def test_edit_ignores_return_to_from_other_user(client, invite, app):
    """If Alice sends return_to pointing at Bob's session, we should silently
    fall back to the deck's card list — not redirect her to Bob's results."""
    alice, bob = _register_two_users(app, client, invite)

    _login(client, "bob", "correct-horse-2")
    bobs_deck = _mk_deck_with_cards(app, bob.id, 1, "BobsDeck")
    bobs_sid = _start_session(client, app, bobs_deck.id, n=1)
    _finish_session(client, app, bobs_sid, {0: "a0"})
    client.post("/logout")

    _login(client, "alice", "correct-horse-1")
    alice_deck = _mk_deck_with_cards(app, alice.id, 1, "AliceDeck")
    alice_card = app.Card.query.filter_by(deck_id=alice_deck.id).one()

    r = client.post(f"/cards/{alice_card.id}/edit?return_to={bobs_sid}",
                    data={"question": "q0", "answer": "ok", "submit": "Save"},
                    follow_redirects=False)
    assert r.status_code == 302
    # Bob's results MUST NOT be the redirect target.
    assert f"/sessions/{bobs_sid}/results" not in r.headers["Location"]
    assert r.headers["Location"].endswith(f"/decks/{alice_deck.id}/cards")
