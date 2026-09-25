"""M4 tests — study config, session loop, submit, results, isolation."""
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


# ---- Study config page ----------------------------------------------

def test_config_page_renders(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 5)

    r = client.get(f"/decks/{d.id}/study")
    assert r.status_code == 200
    assert b"Start" in r.data
    assert b"Shuffle" in r.data
    assert b"Creation order" in r.data
    # n_cards default = deck size
    assert b'value="5"' in r.data


def test_config_page_empty_deck_blocks_start(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = app.Deck(user_id=alice.id, name="Empty")
    app.db.session.add(d)
    app.db.session.commit()

    r = client.get(f"/decks/{d.id}/study")
    assert r.status_code == 200
    assert b"no cards yet" in r.data
    assert b"Add cards first" in r.data
    # No Start submit button on empty-deck page.
    assert b"Start" not in r.data or b'type="submit"' not in r.data


def test_config_requires_login(client):
    r = client.get("/decks/1/study", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_config_on_others_deck_404(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    bobs = _mk_deck_with_cards(app, bob.id, 3, "BobsDeck")
    _login(client, "alice", "correct-horse-1")
    assert client.get(f"/decks/{bobs.id}/study").status_code == 404


# ---- Starting a session ---------------------------------------------

def test_starting_session_creates_attempts(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 4)

    r = client.post(f"/decks/{d.id}/study",
                    data={"n_cards": 4, "order": "created", "submit": "Start"},
                    follow_redirects=False)
    assert r.status_code == 302
    m = re.search(r"/sessions/(\d+)", r.headers["Location"])
    assert m
    sid = int(m.group(1))

    s = app.db.session.get(app.StudySession, sid)
    assert s.user_id == alice.id
    assert s.deck_id == d.id
    assert s.n_cards == 4
    assert s.shuffled is False
    assert s.finished_at is None
    assert s.score is None

    attempts = app.StudyAttempt.query.filter_by(session_id=sid).order_by(
        app.StudyAttempt.position.asc()
    ).all()
    assert len(attempts) == 4
    for i, a in enumerate(attempts):
        assert a.position == i
        assert a.card_snapshot_q == f"q{i}"
        assert a.card_snapshot_a == f"a{i}"
        assert a.student_answer is None
        assert a.is_correct is None


def test_starting_clamps_n_to_deck_size(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 3)

    r = client.post(f"/decks/{d.id}/study",
                    data={"n_cards": 99, "order": "created", "submit": "Start"},
                    follow_redirects=False)
    assert r.status_code == 302
    sid = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))
    s = app.db.session.get(app.StudySession, sid)
    assert s.n_cards == 3
    assert app.StudyAttempt.query.filter_by(session_id=sid).count() == 3


def test_starting_subset(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 10)

    r = client.post(f"/decks/{d.id}/study",
                    data={"n_cards": 3, "order": "created", "submit": "Start"},
                    follow_redirects=False)
    sid = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))
    s = app.db.session.get(app.StudySession, sid)
    assert s.n_cards == 3
    assert app.StudyAttempt.query.filter_by(session_id=sid).count() == 3


def test_starting_on_empty_deck_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = app.Deck(user_id=alice.id, name="Empty")
    app.db.session.add(d)
    app.db.session.commit()

    r = client.post(f"/decks/{d.id}/study",
                    data={"n_cards": 1, "order": "created", "submit": "Start"})
    # Empty deck path renders the empty-state page instead of accepting.
    assert r.status_code == 200
    assert b"no cards yet" in r.data
    assert app.StudySession.query.count() == 0


# ---- Loop / submit --------------------------------------------------

def _start_session(client, app, alice_id, n=3):
    d = _mk_deck_with_cards(app, alice_id, n)
    r = client.post(f"/decks/{d.id}/study",
                    data={"n_cards": n, "order": "created", "submit": "Start"},
                    follow_redirects=False)
    sid = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))
    return d, sid


def test_active_page_shows_first_question(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=3)
    r = client.get(f"/sessions/{sid}")
    assert r.status_code == 200
    assert b"q0" in r.data
    assert b"1 of 3" in r.data


def test_submit_correct_advances(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=3)
    first = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()

    r = client.post(f"/sessions/{sid}/submit",
                    data={"attempt_id": first.id, "answer": "a0"},
                    follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/sessions/{sid}")

    a0 = app.db.session.get(app.StudyAttempt, first.id)
    assert a0.student_answer == "a0"
    assert a0.is_correct is True
    assert a0.attempted_at is not None


def test_submit_wrong_records_wrong(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=3)
    first = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()

    client.post(f"/sessions/{sid}/submit",
                data={"attempt_id": first.id, "answer": "nope"})
    a = app.db.session.get(app.StudyAttempt, first.id)
    assert a.student_answer == "nope"
    assert a.is_correct is False


def test_submit_blank_is_wrong(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=3)
    first = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()
    client.post(f"/sessions/{sid}/submit",
                data={"attempt_id": first.id, "answer": ""})
    a = app.db.session.get(app.StudyAttempt, first.id)
    assert a.student_answer == ""
    assert a.is_correct is False


def test_submit_whitespace_tolerant(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=3)
    first = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()
    client.post(f"/sessions/{sid}/submit",
                data={"attempt_id": first.id, "answer": "  a0  "})
    a = app.db.session.get(app.StudyAttempt, first.id)
    assert a.is_correct is True


def test_submit_case_sensitive(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=3)
    first = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()
    client.post(f"/sessions/{sid}/submit",
                data={"attempt_id": first.id, "answer": "A0"})
    a = app.db.session.get(app.StudyAttempt, first.id)
    assert a.is_correct is False


def test_full_session_flow_ends_at_results(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=3)

    # Answer all three: 2 right, 1 wrong.
    answers = {0: "a0", 1: "wrong", 2: "a2"}
    for pos in (0, 1, 2):
        a = app.StudyAttempt.query.filter_by(session_id=sid, position=pos).one()
        r = client.post(f"/sessions/{sid}/submit",
                        data={"attempt_id": a.id, "answer": answers[pos]},
                        follow_redirects=False)
        assert r.status_code == 302

    # After last submit, location should point at /results.
    assert r.headers["Location"].endswith(f"/sessions/{sid}/results")

    s = app.db.session.get(app.StudySession, sid)
    assert s.finished_at is not None
    assert s.score == 2


def test_visiting_finished_session_redirects_to_results(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=2)
    for pos in (0, 1):
        a = app.StudyAttempt.query.filter_by(session_id=sid, position=pos).one()
        client.post(f"/sessions/{sid}/submit",
                    data={"attempt_id": a.id, "answer": f"a{pos}"})
    r = client.get(f"/sessions/{sid}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/sessions/{sid}/results")


def test_submit_double_ignored(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=3)
    first = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()

    client.post(f"/sessions/{sid}/submit",
                data={"attempt_id": first.id, "answer": "a0"})
    # Try again — should not flip is_correct or overwrite answer.
    client.post(f"/sessions/{sid}/submit",
                data={"attempt_id": first.id, "answer": "changed"})
    a = app.db.session.get(app.StudyAttempt, first.id)
    assert a.student_answer == "a0"
    assert a.is_correct is True


def test_submit_paste_bomb_truncated(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=1)
    first = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()
    client.post(f"/sessions/{sid}/submit",
                data={"attempt_id": first.id, "answer": "x" * 5000})
    a = app.db.session.get(app.StudyAttempt, first.id)
    assert len(a.student_answer) == 500


# ---- Results page ---------------------------------------------------

def test_results_page_shows_score_and_diff(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=2)

    # answer 0: correct ("a0"). answer 1: wrong ("wrong" vs "a1")
    for pos, ans in [(0, "a0"), (1, "wrong")]:
        a = app.StudyAttempt.query.filter_by(session_id=sid, position=pos).one()
        client.post(f"/sessions/{sid}/submit",
                    data={"attempt_id": a.id, "answer": ans})

    r = client.get(f"/sessions/{sid}/results")
    assert r.status_code == 200
    assert b"1 / 2" in r.data
    assert b"q0" in r.data and b"q1" in r.data
    # Wrong row shows diff spans.
    assert b'class="diff-' in r.data
    # Wrong row shows an "Edit this card" link.
    assert b"Edit this card" in r.data


def test_results_unfinished_redirects_to_loop(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=3)
    r = client.get(f"/sessions/{sid}/results", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith(f"/sessions/{sid}")


def test_results_blank_answer_shown_as_blank(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=1)
    first = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()
    client.post(f"/sessions/{sid}/submit",
                data={"attempt_id": first.id, "answer": ""})
    r = client.get(f"/sessions/{sid}/results")
    assert r.status_code == 200
    assert b"(blank)" in r.data


# ---- Cross-user isolation -------------------------------------------

def test_alice_cannot_view_bobs_session(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    _login(client, "bob", "correct-horse-2")
    d = _mk_deck_with_cards(app, bob.id, 2, "BobsDeck")
    r = client.post(f"/decks/{d.id}/study",
                    data={"n_cards": 2, "order": "created", "submit": "Start"},
                    follow_redirects=False)
    sid = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))
    client.post("/logout")

    _login(client, "alice", "correct-horse-1")
    assert client.get(f"/sessions/{sid}").status_code == 404
    assert client.get(f"/sessions/{sid}/results").status_code == 404


def test_alice_cannot_submit_to_bobs_session(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    _login(client, "bob", "correct-horse-2")
    d = _mk_deck_with_cards(app, bob.id, 2, "BobsDeck")
    r = client.post(f"/decks/{d.id}/study",
                    data={"n_cards": 2, "order": "created", "submit": "Start"},
                    follow_redirects=False)
    sid = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))
    bobs_attempt = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()
    client.post("/logout")

    _login(client, "alice", "correct-horse-1")
    r = client.post(f"/sessions/{sid}/submit",
                    data={"attempt_id": bobs_attempt.id, "answer": "hijack"})
    assert r.status_code == 404
    fresh = app.db.session.get(app.StudyAttempt, bobs_attempt.id)
    assert fresh.student_answer is None
    assert fresh.is_correct is None


def test_alice_cannot_start_session_on_bobs_deck(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    bobs = _mk_deck_with_cards(app, bob.id, 3, "BobsDeck")
    _login(client, "alice", "correct-horse-1")
    r = client.post(f"/decks/{bobs.id}/study",
                    data={"n_cards": 3, "order": "created", "submit": "Start"})
    assert r.status_code == 404
    assert app.StudySession.query.count() == 0


def test_submit_with_alien_attempt_id_404(client, invite, app):
    """Alice starts her own session but tries to submit against Bob's attempt id."""
    alice, bob = _register_two_users(app, client, invite)

    _login(client, "bob", "correct-horse-2")
    bobs_deck = _mk_deck_with_cards(app, bob.id, 1, "BobsDeck")
    r = client.post(f"/decks/{bobs_deck.id}/study",
                    data={"n_cards": 1, "order": "created", "submit": "Start"},
                    follow_redirects=False)
    bobs_sid = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))
    bobs_attempt = app.StudyAttempt.query.filter_by(session_id=bobs_sid, position=0).one()
    client.post("/logout")

    _login(client, "alice", "correct-horse-1")
    alice_deck = _mk_deck_with_cards(app, alice.id, 1, "AliceDeck")
    r = client.post(f"/decks/{alice_deck.id}/study",
                    data={"n_cards": 1, "order": "created", "submit": "Start"},
                    follow_redirects=False)
    alice_sid = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))

    # Alice's session, but Bob's attempt id — should 404.
    r = client.post(f"/sessions/{alice_sid}/submit",
                    data={"attempt_id": bobs_attempt.id, "answer": "hack"})
    assert r.status_code == 404


# ---- Snapshot survives card edits/deletes ---------------------------

def test_editing_card_mid_session_does_not_rewrite_snapshot(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=2)

    # Find the card behind position 0 and edit its answer.
    a0 = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()
    card = app.db.session.get(app.Card, a0.card_id)
    card.answer = "totally-changed"
    app.db.session.commit()

    # Snapshot on the attempt must be unchanged.
    fresh = app.db.session.get(app.StudyAttempt, a0.id)
    assert fresh.card_snapshot_a == "a0"


def test_deleting_card_mid_session_keeps_snapshot(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _, sid = _start_session(client, app, alice.id, n=2)

    a0 = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()
    card_id = a0.card_id
    app.db.session.delete(app.db.session.get(app.Card, card_id))
    app.db.session.commit()

    fresh = app.db.session.get(app.StudyAttempt, a0.id)
    assert fresh.card_id is None  # SET NULL
    assert fresh.card_snapshot_q == "q0"
    assert fresh.card_snapshot_a == "a0"
