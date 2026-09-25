"""M6 tests — account self-service (change password + delete account)."""
import pytest


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
        app.db.session.add(app.Card(deck_id=d.id, question=f"q{i}", answer=f"a{i}"))
    app.db.session.commit()
    return d


# ---- /account page --------------------------------------------------

def test_account_requires_login(client):
    r = client.get("/account", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_account_renders_both_panels(client, invite, app):
    _register(client, invite, "alice")
    r = client.get("/account")
    assert r.status_code == 200
    assert b"Change password" in r.data
    assert b"Delete account" in r.data
    assert b"alice" in r.data


# ---- Change password ------------------------------------------------

def test_change_password_wrong_current_rejected(client, invite, app):
    _register(client, invite, "alice")
    r = client.post("/account/password", data={
        "current_password": "wrong",
        "new_password": "new-password-12",
        "confirm": "new-password-12",
        "submit": "Change password",
    })
    assert r.status_code == 200
    assert b"Current password is incorrect" in r.data
    # Password unchanged: original still works.
    client.post("/logout")
    r = _login(client, "alice", "correct-horse-1")
    # 200 rendered form with error means still logged out.
    with client.session_transaction() as s:
        assert "_user_id" in s


def test_change_password_confirm_mismatch_rejected(client, invite, app):
    _register(client, invite, "alice")
    r = client.post("/account/password", data={
        "current_password": "correct-horse-1",
        "new_password": "new-password-12",
        "confirm": "nope-nope-nope",
        "submit": "Change password",
    })
    assert r.status_code == 200
    assert b"Passwords must match" in r.data


def test_change_password_too_short_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    old_hash = alice.password_hash

    r = client.post("/account/password", data={
        "current_password": "correct-horse-1",
        "new_password": "short",
        "confirm": "short",
        "submit": "Change password",
    })
    assert r.status_code == 200
    # Form rejected (no redirect); hash unchanged.
    app.db.session.expire_all()
    fresh = app.User.query.filter_by(username="alice").one()
    assert fresh.password_hash == old_hash
    # Still logged in — form re-rendered.
    with client.session_transaction() as s:
        assert "_user_id" in s


def test_change_password_success_forces_relogin(client, invite, app):
    _register(client, invite, "alice")
    r = client.post("/account/password", data={
        "current_password": "correct-horse-1",
        "new_password": "brand-new-passphrase",
        "confirm": "brand-new-passphrase",
        "submit": "Change password",
    }, follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]

    # Logged out.
    with client.session_transaction() as s:
        assert "_user_id" not in s

    # Old password no longer works.
    r = _login(client, "alice", "correct-horse-1")
    with client.session_transaction() as s:
        assert "_user_id" not in s

    # New password works.
    _login(client, "alice", "brand-new-passphrase")
    with client.session_transaction() as s:
        assert "_user_id" in s


def test_change_password_hash_actually_changes(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    old_hash = alice.password_hash

    client.post("/account/password", data={
        "current_password": "correct-horse-1",
        "new_password": "brand-new-passphrase",
        "confirm": "brand-new-passphrase",
        "submit": "Change password",
    })
    app.db.session.expire_all()
    fresh = app.User.query.filter_by(username="alice").one()
    assert fresh.password_hash != old_hash


# ---- Delete account -------------------------------------------------

def test_delete_wrong_username_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice_id = app.User.query.filter_by(username="alice").one().id

    r = client.post("/account/delete", data={
        "confirm_username": "not-alice",
        "password": "correct-horse-1",
        "submit": "Delete my account",
    })
    assert r.status_code == 200
    assert b"doesn" in r.data or b"match" in r.data
    assert app.db.session.get(app.User, alice_id) is not None


def test_delete_wrong_password_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice_id = app.User.query.filter_by(username="alice").one().id

    r = client.post("/account/delete", data={
        "confirm_username": "alice",
        "password": "wrong",
        "submit": "Delete my account",
    })
    assert r.status_code == 200
    assert b"Password is incorrect" in r.data
    assert app.db.session.get(app.User, alice_id) is not None


def test_delete_success_removes_user(client, invite, app):
    _register(client, invite, "alice")
    alice_id = app.User.query.filter_by(username="alice").one().id

    r = client.post("/account/delete", data={
        "confirm_username": "alice",
        "password": "correct-horse-1",
        "submit": "Delete my account",
    }, follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]

    assert app.db.session.get(app.User, alice_id) is None
    with client.session_transaction() as s:
        assert "_user_id" not in s


def test_delete_cascades_decks_cards_sessions_attempts(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    alice_id = alice.id
    d = _mk_deck_with_cards(app, alice_id, 3)

    # Run a session so we've got StudySession + StudyAttempt rows.
    import re
    r = client.post(f"/decks/{d.id}/study",
                    data={"n_cards": 3, "order": "created", "submit": "Start"},
                    follow_redirects=False)
    sid = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))
    for pos in range(3):
        a = app.StudyAttempt.query.filter_by(session_id=sid, position=pos).one()
        client.post(f"/sessions/{sid}/submit",
                    data={"attempt_id": a.id, "answer": f"a{pos}"})

    assert app.Deck.query.count() == 1
    assert app.Card.query.count() == 3
    assert app.StudySession.query.count() == 1
    assert app.StudyAttempt.query.count() == 3

    client.post("/account/delete", data={
        "confirm_username": "alice",
        "password": "correct-horse-1",
        "submit": "Delete my account",
    })
    assert app.User.query.count() == 0
    assert app.Deck.query.count() == 0
    assert app.Card.query.count() == 0
    assert app.StudySession.query.count() == 0
    assert app.StudyAttempt.query.count() == 0


def test_delete_succeeds_when_user_has_used_invite(client, invite, app):
    """Regression: pre-M6 this failed with FK error because invite_code.used_by
    had no ON DELETE clause. 0003 migration set that to SET NULL."""
    _register(client, invite, "alice")
    alice_id = app.User.query.filter_by(username="alice").one().id

    linked = app.InviteCode.query.filter_by(used_by=alice_id).all()
    assert len(linked) == 1, "smoke: register should link exactly one invite"
    invite_id = linked[0].id

    r = client.post("/account/delete", data={
        "confirm_username": "alice",
        "password": "correct-horse-1",
        "submit": "Delete my account",
    }, follow_redirects=False)
    assert r.status_code == 302

    assert app.db.session.get(app.User, alice_id) is None
    ic = app.db.session.get(app.InviteCode, invite_id)
    assert ic is not None
    assert ic.used_by is None
    assert ic.used_at is not None  # audit trail preserved


def test_deleted_user_cannot_log_back_in(client, invite, app):
    _register(client, invite, "alice")

    client.post("/account/delete", data={
        "confirm_username": "alice",
        "password": "correct-horse-1",
        "submit": "Delete my account",
    })
    r = _login(client, "alice", "correct-horse-1")
    with client.session_transaction() as s:
        assert "_user_id" not in s


def test_delete_requires_login(client):
    r = client.post("/account/delete", data={
        "confirm_username": "alice",
        "password": "x",
        "submit": "Delete my account",
    }, follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_change_password_requires_login(client):
    r = client.post("/account/password", data={
        "current_password": "x", "new_password": "yyyyyyyy", "confirm": "yyyyyyyy",
        "submit": "Change password",
    }, follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_username_confirm_is_case_insensitive(client, invite, app):
    """Users register case-preserving, log in case-insensitive — delete should match too."""
    _register(client, invite, "Alice")
    r = client.post("/account/delete", data={
        "confirm_username": "alice",
        "password": "correct-horse-1",
        "submit": "Delete my account",
    }, follow_redirects=False)
    assert r.status_code == 302
    assert app.User.query.count() == 0
