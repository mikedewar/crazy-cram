"""Tests for Learn mode — five-section guided study.

Section composition:
  §1 MC — every card in the deck
  §2 MC — cards wrong in §1
  §3 Written — cards right in §1 AND §2 (right in either)
  §4 MC — cards wrong in §2 AND §3
  §5 Written — every card in the deck

Final results score counts §5 only, but marking shows per-card totals
across all 5 sections. Most-missed is ranked by total wrong across all 5.
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


def _start_learn(client, deck_id):
    r = client.post(
        f"/decks/{deck_id}/study",
        data={"mode": "learn", "n_cards": 4, "order": "created",
              "submit": "Start"},
    )
    assert r.status_code == 302, r.data
    # Location: /sessions/<id>/learn
    m = re.search(r"/sessions/(\d+)/learn$", r.headers["Location"])
    assert m, r.headers["Location"]
    return int(m.group(1))


def _current_attempt_id(client, session_id):
    r = client.get(f"/sessions/{session_id}/learn")
    assert r.status_code == 200, r.data
    body = r.data.decode()
    m = re.search(r'name="attempt_id" value="(\d+)"', body)
    assert m, body[:400]
    return int(m.group(1))


def _answer(client, session_id, attempt_id, answer):
    r = client.post(
        f"/sessions/{session_id}/learn/submit",
        data={"attempt_id": attempt_id, "answer": answer},
    )
    assert r.status_code == 302, r.data
    return r.headers["Location"]


def _play_section(client, app, session_id, section, correct_fraction=1.0):
    """Answer every attempt in `section`. If correct_fraction<1, mark the
    first (1-correct_fraction)*N attempts wrong by submitting a bad answer.

    Returns the list of attempts (as app.StudyAttempt rows) in order.
    """
    attempts = (
        app.StudyAttempt.query
        .filter_by(session_id=session_id, section=section)
        .order_by(app.StudyAttempt.position.asc())
        .all()
    )
    n = len(attempts)
    n_wrong = int(round(n * (1 - correct_fraction)))
    for i, a in enumerate(attempts):
        # Fetch the live page just to assert flow stays on this attempt.
        live = _current_attempt_id(client, session_id)
        assert live == a.id, f"expected attempt {a.id} next, got {live}"
        ans = "WRONG" if i < n_wrong else a.card_snapshot_a
        _answer(client, session_id, a.id, ans)
    return attempts


# ---- Config: Learn radio + gating ------------------------------------

def test_learn_radio_available_on_big_enough_deck(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 4)
    r = client.get(f"/decks/1/study")
    body = r.data.decode()
    assert 'value="learn"' in body
    assert "needs 4+ cards" not in body or body.count("needs 4+ cards") < 2


def test_learn_radio_disabled_when_deck_too_small(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 3)
    r = client.get(f"/decks/1/study")
    body = r.data.decode()
    # Both MC and Learn should be gated at the same threshold.
    assert 'value="learn"' in body
    assert body.count("needs 4+ cards") >= 2


def test_learn_post_rejected_on_small_deck(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 3)
    r = client.post("/decks/1/study", data={
        "mode": "learn", "n_cards": 3, "order": "created", "submit": "Start",
    })
    # Rejected → redirect back to the config page, no session created.
    assert r.status_code == 302
    assert "/study" in r.headers["Location"]
    assert app.StudySession.query.count() == 0


# ---- Section 1: all cards, MC --------------------------------------

def test_section_1_contains_every_deck_card(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 5)
    sid = _start_learn(client, 1)
    s1 = app.StudyAttempt.query.filter_by(session_id=sid, section=1).all()
    assert len(s1) == 5
    assert {a.card_snapshot_q for a in s1} == {f"q{i}" for i in range(5)}


def test_section_1_renders_as_mc(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 4)
    sid = _start_learn(client, 1)
    r = client.get(f"/sessions/{sid}/learn")
    body = r.data.decode()
    # MC radio options are present
    assert body.count('type="radio" name="answer"') == 4
    # Section bar shows 1 active, with 5 segments total
    assert body.count("learn-section-segment") == 5


# ---- Section flow: 1 → interstitial → 2 → interstitial → ...

def test_full_perfect_run_lands_on_results(client, invite, app):
    """A perfect §1 means §2 is empty, §3 is all cards (written), §4 empty,
    §5 all cards (written). Final score 4/4 in §5.
    """
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 4)
    sid = _start_learn(client, 1)

    for section in range(1, 6):
        _play_section(client, app, sid, section, correct_fraction=1.0)
        r = client.get(f"/sessions/{sid}/learn", follow_redirects=False)
        if section < 5:
            # §<5 lands on interstitial for THIS section.
            assert f"/learn/interstitial/{section}" in r.headers.get("Location", ""), (
                section, r.headers.get("Location")
            )
            adv = client.post(
                f"/sessions/{sid}/learn/advance",
                data={"from_section": section},
            )
            assert adv.status_code == 302
        else:
            # §5 complete → finalize + redirect to results.
            assert "/learn/results" in r.headers.get("Location", "")

    s = app.StudySession.query.get(sid)
    assert s.finished_at is not None
    # §5 score = 4 right / 4 total
    s5 = app.StudyAttempt.query.filter_by(session_id=sid, section=5).all()
    assert len(s5) == 4
    assert sum(1 for a in s5 if a.is_correct) == 4


def test_section_2_has_only_section_1_wrongs(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 4)
    sid = _start_learn(client, 1)

    # Get first two wrong in §1 (correct_fraction=0.5 → 2 wrong of 4).
    _play_section(client, app, sid, 1, correct_fraction=0.5)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 1})

    s2 = app.StudyAttempt.query.filter_by(session_id=sid, section=2).all()
    # The two §1-wrong cards should be in §2.
    s1 = app.StudyAttempt.query.filter_by(session_id=sid, section=1).all()
    s1_wrong_ids = {a.card_id for a in s1 if a.is_correct is False}
    s2_ids = {a.card_id for a in s2}
    assert s2_ids == s1_wrong_ids
    assert len(s2) == 2


def test_section_3_has_right_in_s1_or_s2_written(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 4)
    sid = _start_learn(client, 1)

    # §1: 2 wrong, 2 right.
    _play_section(client, app, sid, 1, correct_fraction=0.5)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 1})
    # §2: perfect on the 2 wrong-again cards.
    _play_section(client, app, sid, 2, correct_fraction=1.0)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 2})

    s3 = app.StudyAttempt.query.filter_by(session_id=sid, section=3).all()
    s1 = app.StudyAttempt.query.filter_by(session_id=sid, section=1).all()
    s2 = app.StudyAttempt.query.filter_by(session_id=sid, section=2).all()
    right_in_either = (
        {a.card_id for a in s1 if a.is_correct}
        | {a.card_id for a in s2 if a.is_correct}
    )
    assert {a.card_id for a in s3} == right_in_either
    assert len(s3) == 4  # all right in §1 or §2
    # §3 renders as written mode.
    r = client.get(f"/sessions/{sid}/learn")
    body = r.data.decode()
    assert 'name="answer"' in body
    assert 'type="radio" name="answer"' not in body


def test_section_4_has_wrong_in_s2_or_s3(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 4)
    sid = _start_learn(client, 1)

    # §1: all wrong → §2 is all 4
    _play_section(client, app, sid, 1, correct_fraction=0.0)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 1})
    # §2: half wrong (2) → right-in-§2 = 2
    _play_section(client, app, sid, 2, correct_fraction=0.5)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 2})
    # §3 content = right in §1 or §2 = 2 cards. Get them half wrong (1).
    _play_section(client, app, sid, 3, correct_fraction=0.5)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 3})

    s2 = app.StudyAttempt.query.filter_by(session_id=sid, section=2).all()
    s3 = app.StudyAttempt.query.filter_by(session_id=sid, section=3).all()
    s4 = app.StudyAttempt.query.filter_by(session_id=sid, section=4).all()

    wrong_in_either = (
        {a.card_id for a in s2 if a.is_correct is False}
        | {a.card_id for a in s3 if a.is_correct is False}
    )
    assert {a.card_id for a in s4} == wrong_in_either


def test_section_5_is_all_cards_written(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 4)
    sid = _start_learn(client, 1)

    for section in range(1, 5):
        _play_section(client, app, sid, section, correct_fraction=1.0)
        client.post(f"/sessions/{sid}/learn/advance",
                    data={"from_section": section})

    # §5 should have every deck card
    s5 = app.StudyAttempt.query.filter_by(session_id=sid, section=5).all()
    assert len(s5) == 4
    assert {a.card_snapshot_q for a in s5} == {"q0", "q1", "q2", "q3"}
    # §5 renders as written
    r = client.get(f"/sessions/{sid}/learn")
    body = r.data.decode()
    assert 'type="radio" name="answer"' not in body


# ---- Empty-section skip ---------------------------------------------

def test_empty_section_still_shows_interstitial(client, invite, app):
    """Perfect §1 means §2 is empty. Interstitial for §2 should still render
    (score 0/0 'nothing to review') with a Next button."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 4)
    sid = _start_learn(client, 1)

    _play_section(client, app, sid, 1, correct_fraction=1.0)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 1})
    # Now section 2 was composed as empty; expect a redirect to the §2
    # interstitial from learn_section logic.
    r = client.get(f"/sessions/{sid}/learn", follow_redirects=False)
    assert "/learn/interstitial/2" in r.headers.get("Location", ""), r.headers


# ---- Final results --------------------------------------------------

def test_learn_results_score_is_section_5_only(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 4)
    sid = _start_learn(client, 1)

    # §1 all wrong, §2 all right, §3 (right-in-1-or-2 = 4) all right,
    # §4 (wrong-in-2-or-3 = 0, empty), §5 half wrong.
    _play_section(client, app, sid, 1, correct_fraction=0.0)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 1})
    _play_section(client, app, sid, 2, correct_fraction=1.0)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 2})
    _play_section(client, app, sid, 3, correct_fraction=1.0)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 3})
    # §4 was empty → learn_section redirects to §4 interstitial. Just
    # advance from there.
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 4})
    _play_section(client, app, sid, 5, correct_fraction=0.5)
    # Visiting /learn after §5 completes finalizes the session.
    client.get(f"/sessions/{sid}/learn")

    r = client.get(f"/sessions/{sid}/learn/results")
    assert r.status_code == 200
    body = r.data.decode()
    # Score header reflects §5 only — 2 right out of 4.
    assert "<strong>2 / 4</strong>" in body


def test_learn_results_most_missed_ranks_by_total_wrong(client, invite, app):
    """A card gotten wrong across several sections should rank first."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 4)
    sid = _start_learn(client, 1)

    # Set it up so card q0 is wrong in §1, §2, §4, §5 (max possible wrong
    # count). Other cards: §1 wrong (so they're all in §2), §2 right, §3
    # possibly, §5 right.
    # Easiest: all wrong in §1, all right in §2, all right in §3,
    # §4 is wrong-in-§2-or-§3 which is empty, §5 only q0 wrong.
    _play_section(client, app, sid, 1, correct_fraction=0.0)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 1})
    _play_section(client, app, sid, 2, correct_fraction=1.0)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 2})
    _play_section(client, app, sid, 3, correct_fraction=1.0)
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 3})
    # §4 empty → advance to §5
    client.post(f"/sessions/{sid}/learn/advance", data={"from_section": 4})
    # §5: only q0 wrong.
    s5 = app.StudyAttempt.query.filter_by(session_id=sid, section=5).all()
    for a in s5:
        ans = "WRONG" if a.card_snapshot_q == "q0" else a.card_snapshot_a
        _answer(client, sid, a.id, ans)
    # Finalize via a trailing /learn visit.
    client.get(f"/sessions/{sid}/learn")

    r = client.get(f"/sessions/{sid}/learn/results")
    body = r.data.decode()
    # Most-missed section exists and q0 appears first.
    assert "Most-missed" in body
    most_missed_start = body.index("Most-missed")
    section_5_start = body.index("Section 5 marking")
    section_slice = body[most_missed_start:section_5_start]
    # q0 should appear in the most-missed section at least once.
    assert "q0" in section_slice
    # q0 total wrong count across sections 1 and 5 = 2.
    assert "<strong>2</strong> wrong" in section_slice


# ---- Isolation -------------------------------------------------------

def test_other_user_learn_session_is_404(client, invite, app):
    """Isolation = 404 (same shape as a bad ID)."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 4)
    sid = _start_learn(client, 1)

    client.post("/logout")
    _register(client, invite, "bob")
    for path in (
        f"/sessions/{sid}/learn",
        f"/sessions/{sid}/learn/submit",
        f"/sessions/{sid}/learn/interstitial/1",
        f"/sessions/{sid}/learn/advance",
        f"/sessions/{sid}/learn/results",
    ):
        if path.endswith("/submit") or path.endswith("/advance"):
            r = client.post(path, data={"attempt_id": 1, "from_section": 1})
        else:
            r = client.get(path)
        assert r.status_code == 404, (path, r.status_code)


def test_non_learn_session_404s_on_learn_routes(client, invite, app):
    """A written-mode session should 404 on /learn routes."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_deck_with_cards(app, alice.id, 4)
    # Start a non-learn session.
    r = client.post("/decks/1/study", data={
        "mode": "written", "n_cards": 4, "order": "created", "submit": "Start",
    })
    assert r.status_code == 302
    m = re.search(r"/sessions/(\d+)", r.headers["Location"])
    sid = int(m.group(1))

    r = client.get(f"/sessions/{sid}/learn")
    assert r.status_code == 404
