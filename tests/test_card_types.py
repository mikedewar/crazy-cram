"""Card types extension: written / multiple-choice / true-false."""

import json


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


def _add_written(client, deck_id, q, a):
    return client.post(f"/decks/{deck_id}/cards", data={
        "card_type": "written",
        "question": q, "answer": a,
        "mc_mode": "random", "tf_correct": "true",
        "submit": "Save card",
    }, follow_redirects=False)


def _add_mc_random(client, deck_id, q, a):
    return client.post(f"/decks/{deck_id}/cards", data={
        "card_type": "mc",
        "question": q, "answer": a,
        "mc_mode": "random",
        "tf_correct": "true",
        "submit": "Save card",
    }, follow_redirects=False)


def _add_mc_fixed(client, deck_id, q, a, d1, d2, d3):
    return client.post(f"/decks/{deck_id}/cards", data={
        "card_type": "mc",
        "question": q, "answer": a,
        "mc_mode": "fixed",
        "distractor_1": d1, "distractor_2": d2, "distractor_3": d3,
        "tf_correct": "true",
        "submit": "Save card",
    }, follow_redirects=False)


def _add_tf(client, deck_id, q, correct):
    return client.post(f"/decks/{deck_id}/cards", data={
        "card_type": "tf",
        "question": q, "answer": "",
        "mc_mode": "random",
        "tf_correct": correct,
        "submit": "Save card",
    }, follow_redirects=False)


# ---- Migration / default ----------------------------------------------

def test_existing_cards_default_to_written(client, invite, app):
    """A card inserted directly without card_type gets 'written'."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    c = app.Card(deck_id=d.id, question="q", answer="a")
    app.db.session.add(c)
    app.db.session.commit()
    assert c.card_type == "written"
    assert c.mc_random is None


# ---- Create: written --------------------------------------------------

def test_create_written_card_defaults_to_written(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = _add_written(client, d.id, "chat", "cat")
    assert r.status_code in (301, 302)
    c = app.Card.query.filter_by(deck_id=d.id).one()
    assert c.card_type == "written"
    assert c.answer == "cat"
    assert c.mc_random is None
    assert c.distractors == []


def test_create_written_requires_answer(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = client.post(f"/decks/{d.id}/cards", data={
        "card_type": "written", "question": "chat", "answer": "",
        "mc_mode": "random", "tf_correct": "true",
        "submit": "Save card",
    })
    assert r.status_code == 200  # re-rendered form
    assert app.Card.query.count() == 0


# ---- Create: MC random ------------------------------------------------

def test_create_mc_random_card(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = _add_mc_random(client, d.id, "Capital of France?", "Paris")
    assert r.status_code in (301, 302)
    c = app.Card.query.filter_by(deck_id=d.id).one()
    assert c.card_type == "mc"
    assert c.mc_random is True
    assert c.answer == "Paris"
    assert c.distractors == []


def test_create_mc_fixed_card_persists_distractors(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = _add_mc_fixed(client, d.id, "Capital of France?", "Paris", "Rome", "Berlin", "Madrid")
    assert r.status_code in (301, 302)
    c = app.Card.query.filter_by(deck_id=d.id).one()
    assert c.card_type == "mc"
    assert c.mc_random is False
    assert [d.text for d in c.distractors] == ["Rome", "Berlin", "Madrid"]


def test_create_mc_fixed_rejects_missing_distractors(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = client.post(f"/decks/{d.id}/cards", data={
        "card_type": "mc", "question": "Q", "answer": "A",
        "mc_mode": "fixed",
        "distractor_1": "Rome", "distractor_2": "", "distractor_3": "Madrid",
        "tf_correct": "true", "submit": "Save card",
    })
    assert r.status_code == 200
    assert app.Card.query.count() == 0


def test_create_mc_fixed_rejects_distractor_equal_to_answer(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = _add_mc_fixed(client, d.id, "Q", "Paris", "Paris", "Berlin", "Madrid")
    assert r.status_code == 200
    assert app.Card.query.count() == 0


# ---- Create: TF -------------------------------------------------------

def test_create_tf_card(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    r = _add_tf(client, d.id, "The sky is blue", "true")
    assert r.status_code in (301, 302)
    c = app.Card.query.filter_by(deck_id=d.id).one()
    assert c.card_type == "tf"
    assert c.answer == "true"
    assert c.mc_random is None


def test_create_tf_card_false(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_tf(client, d.id, "The sky is green", "false")
    c = app.Card.query.filter_by(deck_id=d.id).one()
    assert c.answer == "false"


# ---- Edit: type immutability -----------------------------------------

def test_edit_cannot_change_card_type(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_written(client, d.id, "chat", "cat")
    c = app.Card.query.filter_by(deck_id=d.id).one()
    # Try to flip to MC — the server must ignore card_type and keep written.
    r = client.post(f"/cards/{c.id}/edit", data={
        "card_type": "mc", "question": "chat", "answer": "cat",
        "mc_mode": "random", "tf_correct": "true", "submit": "Save card",
    })
    assert r.status_code in (301, 302)
    app.db.session.refresh(c)
    assert c.card_type == "written"


def test_edit_mc_fixed_to_random_forgets_distractors(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_mc_fixed(client, d.id, "Q", "Paris", "Rome", "Berlin", "Madrid")
    c = app.Card.query.filter_by(deck_id=d.id).one()
    assert [x.text for x in c.distractors] == ["Rome", "Berlin", "Madrid"]
    # Flip to random
    r = client.post(f"/cards/{c.id}/edit", data={
        "card_type": "mc", "question": "Q", "answer": "Paris",
        "mc_mode": "random", "tf_correct": "true", "submit": "Save card",
    })
    assert r.status_code in (301, 302)
    app.db.session.refresh(c)
    assert c.mc_random is True
    assert c.distractors == []


# ---- Study: MC-random pool size -------------------------------------

def _start_session(client, deck_id, n):
    return client.post(f"/decks/{deck_id}/study", data={
        "n_cards": str(n), "order": "created", "submit": "Start",
    }, follow_redirects=False)


def test_mc_random_refuses_small_deck(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_mc_random(client, d.id, "Q1", "A1")
    _add_written(client, d.id, "Q2", "A2")
    _add_written(client, d.id, "Q3", "A3")
    # Only 3 cards; MC-random needs ≥4 for correct+3 distractors
    r = _start_session(client, d.id, 3)
    # Should re-render the config page with an error, not start a session
    assert r.status_code == 200
    assert app.StudySession.query.count() == 0


def test_mc_random_accepts_exactly_four_cards(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_mc_random(client, d.id, "Capital?", "Paris")
    _add_written(client, d.id, "Q2", "Rome")
    _add_written(client, d.id, "Q3", "Berlin")
    _add_written(client, d.id, "Q4", "Madrid")
    r = _start_session(client, d.id, 4)
    assert r.status_code in (301, 302)
    s = app.StudySession.query.one()
    assert s.n_cards == 4
    mc_attempt = next(a for a in s.attempts if a.card_type == "mc")
    opts = json.loads(mc_attempt.options_json)
    assert len(opts) == 4
    assert "Paris" in opts
    # Three distractors are drawn from the other three answers
    assert set(opts) - {"Paris"} <= {"Rome", "Berlin", "Madrid"}


# ---- Study: TF + MC options_json round-trip -------------------------

def test_tf_attempt_has_true_false_options(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_tf(client, d.id, "Sky blue?", "true")
    r = _start_session(client, d.id, 1)
    assert r.status_code in (301, 302)
    a = app.StudyAttempt.query.one()
    assert a.card_type == "tf"
    assert json.loads(a.options_json) == ["true", "false"]


# ---- Study: submit and scoring --------------------------------------

def test_mc_submit_correct_scores_right(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_mc_fixed(client, d.id, "Q", "Paris", "Rome", "Berlin", "Madrid")
    r = _start_session(client, d.id, 1)
    s = app.StudySession.query.one()
    a = s.attempts[0]
    client.post(f"/sessions/{s.id}/submit", data={
        "attempt_id": str(a.id), "answer": "Paris",
    })
    app.db.session.refresh(a)
    assert a.is_correct is True
    assert a.student_answer == "Paris"


def test_mc_submit_wrong_scores_wrong(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_mc_fixed(client, d.id, "Q", "Paris", "Rome", "Berlin", "Madrid")
    r = _start_session(client, d.id, 1)
    s = app.StudySession.query.one()
    a = s.attempts[0]
    client.post(f"/sessions/{s.id}/submit", data={
        "attempt_id": str(a.id), "answer": "Rome",
    })
    app.db.session.refresh(a)
    assert a.is_correct is False
    assert a.student_answer == "Rome"


def test_tf_submit_correct(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_tf(client, d.id, "Sky blue?", "true")
    r = _start_session(client, d.id, 1)
    s = app.StudySession.query.one()
    a = s.attempts[0]
    client.post(f"/sessions/{s.id}/submit", data={
        "attempt_id": str(a.id), "answer": "true",
    })
    app.db.session.refresh(a)
    assert a.is_correct is True


def test_mc_submit_option_not_in_pool_counts_as_skip(client, invite, app):
    """A tampered or stale POST with an option outside options_json is
    treated as a skip — never 400, so a confused student can keep going."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_mc_fixed(client, d.id, "Q", "Paris", "Rome", "Berlin", "Madrid")
    r = _start_session(client, d.id, 1)
    s = app.StudySession.query.one()
    a = s.attempts[0]
    client.post(f"/sessions/{s.id}/submit", data={
        "attempt_id": str(a.id), "answer": "Casablanca",
    })
    app.db.session.refresh(a)
    assert a.is_correct is False
    assert a.student_answer is None


def test_skip_button_marks_wrong_all_types(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_written(client, d.id, "Q1", "A1")
    _add_mc_fixed(client, d.id, "Q2", "Paris", "Rome", "Berlin", "Madrid")
    _add_tf(client, d.id, "Q3", "true")
    r = _start_session(client, d.id, 3)
    s = app.StudySession.query.one()
    for a in s.attempts:
        client.post(f"/sessions/{s.id}/submit", data={
            "attempt_id": str(a.id), "skip": "1",
        })
    for a in s.attempts:
        app.db.session.refresh(a)
        assert a.is_correct is False
        assert a.student_answer is None


# ---- Study page renders -------------------------------------------

def test_study_page_renders_mc_options(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_mc_fixed(client, d.id, "Capital?", "Paris", "Rome", "Berlin", "Madrid")
    _start_session(client, d.id, 1)
    s = app.StudySession.query.one()
    r = client.get(f"/sessions/{s.id}")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Paris" in body
    assert "Rome" in body
    assert "Skip" in body
    assert 'class="mc-option"' in body


def test_study_page_renders_tf_buttons(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_tf(client, d.id, "Sky blue?", "true")
    _start_session(client, d.id, 1)
    s = app.StudySession.query.one()
    r = client.get(f"/sessions/{s.id}")
    assert r.status_code == 200
    body = r.data.decode()
    assert 'class="tf-option tf-true"' in body
    assert 'class="tf-option tf-false"' in body


# ---- Results page -------------------------------------------------

def test_results_show_options_for_mc(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_mc_fixed(client, d.id, "Q", "Paris", "Rome", "Berlin", "Madrid")
    _start_session(client, d.id, 1)
    s = app.StudySession.query.one()
    a = s.attempts[0]
    client.post(f"/sessions/{s.id}/submit", data={
        "attempt_id": str(a.id), "answer": "Rome",
    })
    r = client.get(f"/sessions/{s.id}/results")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Paris" in body and "Rome" in body
    assert "is-correct" in body
    assert "was-picked" in body


# ---- Mixed-type deck ---------------------------------------------

def test_mixed_type_deck_session_runs(client, invite, app):
    """A deck with written + MC-fixed + TF cards can be studied end-to-end."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_written(client, d.id, "chat", "cat")
    _add_mc_fixed(client, d.id, "Capital?", "Paris", "Rome", "Berlin", "Madrid")
    _add_tf(client, d.id, "Sky blue?", "true")
    r = _start_session(client, d.id, 3)
    assert r.status_code in (301, 302)
    s = app.StudySession.query.one()
    types = {a.card_type for a in s.attempts}
    assert types == {"written", "mc", "tf"}


# ---- Cascade: deck delete cascades distractors --------------------

def test_deck_delete_cascades_distractors(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)
    _add_mc_fixed(client, d.id, "Q", "Paris", "Rome", "Berlin", "Madrid")
    assert app.CardDistractor.query.count() == 3
    client.post(f"/decks/{d.id}/delete")
    assert app.Card.query.count() == 0
    assert app.CardDistractor.query.count() == 0
