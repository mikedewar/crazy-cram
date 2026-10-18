"""MC-study-mode tests.

Mode is picked on the /decks/N/study page (radio in the config form). MC
needs >=4 cards in the deck; when the deck is smaller the MC radio renders
disabled. Options are 1 correct + 3 distractors drawn from other cards in
the deck. Scoring = exact match on the chosen option string.
"""
import re


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


def _start_mc_session(client, deck_id, n_cards):
    """Start an MC session via the config form and return redirect Location."""
    r = client.post(
        f"/decks/{deck_id}/study",
        data={"mode": "mc", "n_cards": n_cards, "order": "created",
              "submit": "Start"},
    )
    assert r.status_code == 302, r.data
    return r.headers["Location"]


# ---- Deck tiles -----------------------------------------------------

def test_home_shows_single_study_button(client, invite, app):
    """Deck tiles should show one 'Study' button regardless of card count."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 4)
    client.get(f"/decks/{d.id}/cards")  # bump last_opened_at so it appears in recent

    r = client.get("/home")
    assert r.status_code == 200
    body = r.data.decode()
    assert ">Study<" in body
    assert "Written study" not in body
    assert "Multiple choice" not in body


def test_home_single_study_button_small_deck(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 3)
    client.get(f"/decks/{d.id}/cards")

    r = client.get("/home")
    body = r.data.decode()
    assert ">Study<" in body
    assert "Multiple choice" not in body


# ---- Config page offers mode radio --------------------------------------

def _mc_radio_tag(body):
    """Return the <input> HTML for the mc mode radio, or None."""
    m = re.search(r'<input[^>]*value="mc"[^>]*>', body)
    return m.group(0) if m else None


def test_config_page_renders_mode_radio_when_deck_has_four_cards(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 5)

    r = client.get(f"/decks/{d.id}/study")
    assert r.status_code == 200
    body = r.data.decode()
    assert re.search(r'<input[^>]*value="written"[^>]*>', body)
    mc_tag = _mc_radio_tag(body)
    assert mc_tag is not None, "mc radio input should be rendered"
    assert "disabled" not in mc_tag, f"mc radio should be enabled: {mc_tag}"


def test_config_page_disables_mc_radio_when_deck_too_small(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 3)

    r = client.get(f"/decks/{d.id}/study")
    assert r.status_code == 200
    body = r.data.decode()
    assert re.search(r'<input[^>]*value="written"[^>]*>', body)
    mc_tag = _mc_radio_tag(body)
    assert mc_tag is not None, "mc radio input should still render (disabled)"
    assert "disabled" in mc_tag, f"mc radio should be disabled: {mc_tag}"
    assert "needs 4+ cards" in body


def test_config_post_mc_on_small_deck_redirects(client, invite, app):
    """Form submission with mode=mc on a <4-card deck must not start a session."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 3)

    r = client.post(f"/decks/{d.id}/study",
                    data={"mode": "mc", "n_cards": 3, "order": "created",
                          "submit": "Start"})
    assert r.status_code == 302
    assert f"/decks/{d.id}/study" in r.headers["Location"]
    # No session was created.
    assert app.StudySession.query.count() == 0


# ---- Starting a session via the form ---------------------------------

def test_start_mc_session_persists_mode(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 5)

    loc = _start_mc_session(client, d.id, 5)
    sess_id = int(re.search(r"/sessions/(\d+)", loc).group(1))
    s = app.db.session.get(app.StudySession, sess_id)
    assert s is not None
    assert s.mode == "mc"
    assert s.n_cards == 5


def test_written_session_default_mode(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 5)

    r = client.post(f"/decks/{d.id}/study",
                    data={"mode": "written", "n_cards": 5, "order": "created",
                          "submit": "Start"})
    assert r.status_code == 302
    sess_id = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))
    s = app.db.session.get(app.StudySession, sess_id)
    assert s.mode == "written"


# ---- MC question rendering ----------------------------------------

def test_mc_session_renders_four_radio_options(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 6)

    loc = _start_mc_session(client, d.id, 6)
    r = client.get(loc)
    assert r.status_code == 200
    body = r.data.decode()
    radios = re.findall(r'<input type="radio"\s+name="answer"\s+value="([^"]+)"', body)
    assert len(radios) == 4, f"expected 4 radios, got {len(radios)}: {radios!r}"
    # They must be unique.
    assert len(set(radios)) == 4


def test_mc_options_include_correct_answer(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 6)

    loc = _start_mc_session(client, d.id, 6)
    r = client.get(loc)
    body = r.data.decode()
    radios = re.findall(r'<input type="radio"\s+name="answer"\s+value="([^"]+)"', body)
    # The first attempt is q0 → correct answer a0.
    assert "a0" in radios


def test_mc_options_distractors_from_this_deck(client, invite, app):
    """Distractors are answers from other cards in the SAME deck."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    # Deck A has very specific answers; deck B has very different ones.
    da = app.Deck(user_id=alice.id, name="A")
    app.db.session.add(da)
    app.db.session.flush()
    for i in range(4):
        app.db.session.add(app.Card(deck_id=da.id,
                                    question=f"qA{i}", answer=f"ANSA{i}"))
    db_other = app.Deck(user_id=alice.id, name="B")
    app.db.session.add(db_other)
    app.db.session.flush()
    for i in range(4):
        app.db.session.add(app.Card(deck_id=db_other.id,
                                    question=f"qB{i}", answer=f"ANSB{i}"))
    app.db.session.commit()

    loc = _start_mc_session(client, da.id, 4)
    r = client.get(loc)
    body = r.data.decode()
    radios = re.findall(r'<input type="radio"\s+name="answer"\s+value="([^"]+)"', body)
    for opt in radios:
        assert opt.startswith("ANSA"), f"distractor {opt!r} leaked from other deck"


# ---- MC scoring ----------------------------------------------------

def test_mc_correct_pick_scores_right(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 5)
    loc = _start_mc_session(client, d.id, 5)
    sess_id = int(re.search(r"/sessions/(\d+)", loc).group(1))

    # Grab the first attempt's correct answer and submit it.
    s = app.db.session.get(app.StudySession, sess_id)
    first = s.attempts[0]
    r = client.post(
        f"/sessions/{sess_id}/submit",
        data={"attempt_id": first.id, "answer": first.card_snapshot_a},
    )
    assert r.status_code == 302
    app.db.session.expire_all()
    a = app.db.session.get(app.StudyAttempt, first.id)
    assert a.is_correct is True
    assert a.student_answer == first.card_snapshot_a


def test_mc_wrong_pick_scores_wrong(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 5)
    loc = _start_mc_session(client, d.id, 5)
    sess_id = int(re.search(r"/sessions/(\d+)", loc).group(1))

    s = app.db.session.get(app.StudySession, sess_id)
    first = s.attempts[0]
    # Submit any wrong answer that could plausibly be an option.
    wrong = "a1" if first.card_snapshot_a != "a1" else "a2"
    r = client.post(
        f"/sessions/{sess_id}/submit",
        data={"attempt_id": first.id, "answer": wrong},
    )
    assert r.status_code == 302
    app.db.session.expire_all()
    a = app.db.session.get(app.StudyAttempt, first.id)
    assert a.is_correct is False
    assert a.student_answer == wrong


# ---- Results page ---------------------------------------------------

def test_mc_results_show_picks_not_char_diff(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 5)
    loc = _start_mc_session(client, d.id, 5)
    sess_id = int(re.search(r"/sessions/(\d+)", loc).group(1))

    # Submit a wrong answer for every attempt, then view results.
    s = app.db.session.get(app.StudySession, sess_id)
    attempt_ids = [a.id for a in s.attempts]
    for aid in attempt_ids:
        a = app.db.session.get(app.StudyAttempt, aid)
        wrong = "a1" if a.card_snapshot_a != "a1" else "a2"
        client.post(f"/sessions/{sess_id}/submit",
                    data={"attempt_id": aid, "answer": wrong})

    r = client.get(f"/sessions/{sess_id}/results")
    assert r.status_code == 200
    body = r.data.decode()
    # Char-diff spans only appear for written mode.
    assert "diff-ins" not in body
    assert "diff-del" not in body


# ---- Restart carries mode -----------------------------------------

def test_mc_restart_carries_mode(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 5)
    loc = _start_mc_session(client, d.id, 5)
    sess_id = int(re.search(r"/sessions/(\d+)", loc).group(1))

    # Burn through the session with wrong picks to finalize it.
    s = app.db.session.get(app.StudySession, sess_id)
    attempt_ids = [a.id for a in s.attempts]
    for aid in attempt_ids:
        a = app.db.session.get(app.StudyAttempt, aid)
        wrong = "a1" if a.card_snapshot_a != "a1" else "a2"
        client.post(f"/sessions/{sess_id}/submit",
                    data={"attempt_id": aid, "answer": wrong})

    # Restart.
    r = client.post(f"/sessions/{sess_id}/restart")
    assert r.status_code == 302
    new_sess_id = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))
    new_s = app.db.session.get(app.StudySession, new_sess_id)
    assert new_s.mode == "mc"


def test_mc_restart_falls_back_to_written_if_deck_shrank(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 5)
    loc = _start_mc_session(client, d.id, 5)
    sess_id = int(re.search(r"/sessions/(\d+)", loc).group(1))

    # Burn through the session.
    s = app.db.session.get(app.StudySession, sess_id)
    attempt_ids = [a.id for a in s.attempts]
    for aid in attempt_ids:
        a = app.db.session.get(app.StudyAttempt, aid)
        client.post(f"/sessions/{sess_id}/submit",
                    data={"attempt_id": aid, "answer": a.card_snapshot_a})

    # Shrink the deck below MC floor.
    for c in list(app.Card.query.filter_by(deck_id=d.id)):
        app.db.session.delete(c)
    for i in range(3):
        app.db.session.add(app.Card(deck_id=d.id, question=f"nq{i}", answer=f"na{i}"))
    app.db.session.commit()

    r = client.post(f"/sessions/{sess_id}/restart")
    assert r.status_code == 302
    new_sess_id = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))
    new_s = app.db.session.get(app.StudySession, new_sess_id)
    assert new_s.mode == "written"
