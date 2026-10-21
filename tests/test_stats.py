"""Stats page — per-user small-multiples of finished study sessions."""
from datetime import datetime, timezone, timedelta


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


def _mk_deck(app, user_id, name="French", folder_id=None, color="#ff8800"):
    d = app.Deck(user_id=user_id, name=name, folder_id=folder_id, color=color)
    app.db.session.add(d)
    app.db.session.flush()
    for i in range(3):
        app.db.session.add(app.Card(deck_id=d.id, question=f"q{i}", answer=f"a{i}"))
    app.db.session.commit()
    return d


def _mk_finished_session(app, user, deck, n_right, n_wrong, finished_at,
                        mode="written"):
    s = app.StudySession(
        user_id=user.id, deck_id=deck.id, n_cards=n_right + n_wrong,
        shuffled=False, mode=mode,
        started_at=finished_at - timedelta(minutes=5),
        finished_at=finished_at,
        score=n_right,
    )
    app.db.session.add(s)
    app.db.session.flush()
    pos = 0
    for _ in range(n_right):
        app.db.session.add(app.StudyAttempt(
            session_id=s.id, card_id=None,
            card_snapshot_q=f"q{pos}", card_snapshot_a=f"a{pos}",
            student_answer=f"a{pos}", is_correct=True, position=pos,
            attempted_at=finished_at,
        ))
        pos += 1
    for _ in range(n_wrong):
        app.db.session.add(app.StudyAttempt(
            session_id=s.id, card_id=None,
            card_snapshot_q=f"q{pos}", card_snapshot_a=f"a{pos}",
            student_answer="nope", is_correct=False, position=pos,
            attempted_at=finished_at,
        ))
        pos += 1
    app.db.session.commit()
    return s


def _mk_unfinished_session(app, user, deck):
    s = app.StudySession(
        user_id=user.id, deck_id=deck.id, n_cards=3,
        shuffled=False, mode="written",
        started_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        finished_at=None, score=None,
    )
    app.db.session.add(s)
    app.db.session.commit()
    return s


# ---- Access control --------------------------------------------------

def test_stats_requires_login(client):
    r = client.get("/stats", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_stats_empty_renders(client, invite, app):
    _register(client, invite, "alice")
    r = client.get("/stats")
    assert r.status_code == 200
    assert b"No finished study sessions yet" in r.data


# ---- Per-user isolation ---------------------------------------------

def test_bob_cannot_see_alices_sessions(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    af = app.Folder(user_id=alice.id, name="A-Folder", color="#112233")
    app.db.session.add(af); app.db.session.commit()
    adeck = _mk_deck(app, alice.id, "AliceDeck", folder_id=af.id)
    _mk_finished_session(app, alice, adeck, 2, 1,
                         datetime(2026, 2, 1, tzinfo=timezone.utc))
    client.post("/logout")

    _register(client, invite, "bob", "correct-horse-2")
    r = client.get("/stats")
    assert r.status_code == 200
    assert b"AliceDeck" not in r.data
    assert b"A-Folder" not in r.data
    assert b"No finished study sessions yet" in r.data


# ---- Rendering: table-per-folder, row-per-deck, column-per-session --

def test_folder_table_rendered_with_sessions_in_order(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    f = app.Folder(user_id=alice.id, name="Languages", color="#223344")
    app.db.session.add(f); app.db.session.commit()
    d = _mk_deck(app, alice.id, "French", folder_id=f.id, color="#ff8800")

    _mk_finished_session(app, alice, d, 2, 1,
                         datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc))
    _mk_finished_session(app, alice, d, 3, 0,
                         datetime(2026, 2, 3, 10, 0, tzinfo=timezone.utc))

    r = client.get("/stats")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Languages" in body
    assert "French" in body
    # Two donuts for two sessions.
    assert body.count("stats-donut") == 2
    # Oldest first in the DOM.
    i_old = body.index("2026-02-01")
    i_new = body.index("2026-02-03")
    assert i_old < i_new
    # Bright colour used; dull colour is a desaturated version of #ff8800.
    assert "#ff8800" in body
    # Dull: 0xff*0.35 + 0xff*0.65 = 255 -> ff; 0x88*0.35 + 0xff*0.65 ≈ 213 -> d5; 0 + ff*0.65 ≈ 166 -> a6
    assert "#ffd5a6" in body


def test_partial_sessions_ignored(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id, "French")
    _mk_unfinished_session(app, alice, d)

    r = client.get("/stats")
    assert r.status_code == 200
    assert b"No finished study sessions yet" in r.data
    assert b"stats-donut" not in r.data


def test_ragged_right_edge_per_deck(client, invite, app):
    """Deck B has fewer sessions than deck A — B's row is shorter, not padded."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    f = app.Folder(user_id=alice.id, name="L", color="#223344")
    app.db.session.add(f); app.db.session.commit()
    a = _mk_deck(app, alice.id, "A", folder_id=f.id)
    b = _mk_deck(app, alice.id, "B", folder_id=f.id)

    for day in (1, 2, 3):
        _mk_finished_session(app, alice, a, 1, 1,
            datetime(2026, 3, day, tzinfo=timezone.utc))
    _mk_finished_session(app, alice, b, 2, 0,
        datetime(2026, 3, 1, tzinfo=timezone.utc))

    r = client.get("/stats")
    body = r.data.decode()
    assert body.count("stats-donut") == 4  # 3 for A, 1 for B — not padded to 3


def test_unfiled_decks_grouped_separately(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id, "Loose", folder_id=None)
    _mk_finished_session(app, alice, d, 1, 2,
        datetime(2026, 4, 1, tzinfo=timezone.utc))

    r = client.get("/stats")
    body = r.data.decode()
    assert "Unfiled" in body
    assert "Loose" in body


def test_decks_with_no_finished_sessions_hidden(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    f = app.Folder(user_id=alice.id, name="L", color="#223344")
    app.db.session.add(f); app.db.session.commit()
    with_sessions = _mk_deck(app, alice.id, "Studied", folder_id=f.id)
    _mk_deck(app, alice.id, "Untouched", folder_id=f.id)
    _mk_finished_session(app, alice, with_sessions, 1, 0,
        datetime(2026, 5, 1, tzinfo=timezone.utc))

    r = client.get("/stats")
    body = r.data.decode()
    assert "Studied" in body
    assert "Untouched" not in body


# ---- Learn mode: only final run-through counts ----------------------

def test_learn_mode_uses_only_final_section(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id, "L", color="#112233")

    # Build a Learn session by hand so we control section numbers.
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    s = app.StudySession(
        user_id=alice.id, deck_id=d.id, n_cards=3,
        shuffled=False, mode="learn",
        started_at=now - timedelta(minutes=10),
        finished_at=now, score=2,
    )
    app.db.session.add(s); app.db.session.flush()
    # Noise in sections 1..4 — these should NOT count toward the donut.
    for sect in (1, 2, 3, 4):
        app.db.session.add(app.StudyAttempt(
            session_id=s.id, card_id=None,
            card_snapshot_q="q", card_snapshot_a="a",
            student_answer="nope", is_correct=False, position=sect * 10,
            attempted_at=now, section=sect,
        ))
    # Final section (5): 2 right, 1 wrong.
    app.db.session.add(app.StudyAttempt(
        session_id=s.id, card_id=None,
        card_snapshot_q="q", card_snapshot_a="a",
        student_answer="a", is_correct=True, position=50, section=5,
        attempted_at=now,
    ))
    app.db.session.add(app.StudyAttempt(
        session_id=s.id, card_id=None,
        card_snapshot_q="q", card_snapshot_a="a",
        student_answer="a", is_correct=True, position=51, section=5,
        attempted_at=now,
    ))
    app.db.session.add(app.StudyAttempt(
        session_id=s.id, card_id=None,
        card_snapshot_q="q", card_snapshot_a="a",
        student_answer="nope", is_correct=False, position=52, section=5,
        attempted_at=now,
    ))
    app.db.session.commit()

    r = client.get("/stats")
    body = r.data.decode()
    # aria-label on the single donut: "2 correct, 1 wrong on …"
    assert "2 correct, 1 wrong" in body
    assert body.count("stats-donut") == 1


# ---- Skipped (is_correct is NULL) counts as wrong -------------------

def test_skipped_counts_as_wrong(client, invite, app):
    """is_correct=None (skipped) is bucketed into 'wrong' for the donut."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id, "D")
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    s = app.StudySession(
        user_id=alice.id, deck_id=d.id, n_cards=3,
        shuffled=False, mode="written",
        started_at=now - timedelta(minutes=1),
        finished_at=now, score=1,
    )
    app.db.session.add(s); app.db.session.flush()
    app.db.session.add(app.StudyAttempt(
        session_id=s.id, card_id=None, card_snapshot_q="q0",
        card_snapshot_a="a0", student_answer="a0", is_correct=True, position=0,
        attempted_at=now,
    ))
    # Skipped: is_correct intentionally left NULL.
    app.db.session.add(app.StudyAttempt(
        session_id=s.id, card_id=None, card_snapshot_q="q1",
        card_snapshot_a="a1", student_answer=None, is_correct=None, position=1,
        attempted_at=now,
    ))
    app.db.session.add(app.StudyAttempt(
        session_id=s.id, card_id=None, card_snapshot_q="q2",
        card_snapshot_a="a2", student_answer="wrong", is_correct=False, position=2,
        attempted_at=now,
    ))
    app.db.session.commit()

    r = client.get("/stats")
    body = r.data.decode()
    assert "1 correct, 2 wrong" in body


# ---- Sidebar icon ----------------------------------------------------

def test_sidebar_shows_stats_icon_when_logged_in(client, invite, app):
    _register(client, invite, "alice")
    r = client.get("/home")
    assert r.status_code == 200
    assert b'aria-label="Stats"' in r.data
    assert b'href="/stats"' in r.data


def test_sidebar_hides_stats_icon_when_logged_out(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert b'aria-label="Stats"' not in r.data
