"""M7 tests — rate limiting, /health, structured event logging."""
import json
import logging

import pytest


def _register(client, invite, username="alice", password="correct-horse-1"):
    code = invite()
    return client.post("/register", data={
        "invite_code": code, "username": username,
        "password": password, "confirm": password,
        "submit": "Create account",
    })


# ---- /health --------------------------------------------------------

def test_health_returns_ok(client, app):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["version"] == app.VERSION


def test_health_no_auth_required(client):
    # /health must be reachable without a session — monitoring hits it cold.
    r = client.get("/health")
    assert r.status_code == 200


def test_health_reports_db_unreachable(client, app, monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(app.db.session, "execute", _boom)
    r = client.get("/health")
    assert r.status_code == 503
    body = r.get_json()
    assert body["status"] == "error"
    assert body["db"] == "unreachable"


def test_health_exempt_from_rate_limit(client, app):
    # Hit /health more than /login's limit — every one still 200.
    for _ in range(30):
        r = client.get("/health")
        assert r.status_code == 200


# ---- Rate limits ----------------------------------------------------

def test_login_rate_limited_after_ten_attempts(client, app):
    app.limiter.reset()
    for _ in range(10):
        r = client.post("/login", data={
            "username": "nobody", "password": "wrong", "submit": "Log in",
        })
        assert r.status_code == 200
    r = client.post("/login", data={
        "username": "nobody", "password": "wrong", "submit": "Log in",
    })
    assert r.status_code == 429
    app.limiter.reset()


def test_register_rate_limited_after_five_attempts(client, app):
    app.limiter.reset()
    for _ in range(5):
        r = client.post("/register", data={
            "invite_code": "bad", "username": "x",
            "password": "shortish-pw", "confirm": "shortish-pw",
            "submit": "Create account",
        })
        assert r.status_code == 200
    r = client.post("/register", data={
        "invite_code": "bad", "username": "x",
        "password": "shortish-pw", "confirm": "shortish-pw",
        "submit": "Create account",
    })
    assert r.status_code == 429
    app.limiter.reset()


def test_login_get_not_rate_limited(client, app):
    """The limit is on POST only — the login form itself should always render."""
    app.limiter.reset()
    for _ in range(20):
        r = client.get("/login")
        assert r.status_code == 200
    app.limiter.reset()


# ---- Structured event logging --------------------------------------

class _EventCapture(logging.Handler):
    """A minimal handler that keeps every JSON-parsed record in memory."""
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def clear(self):
        self.records.clear()


def _events(sink):
    out = []
    for rec in sink.records:
        try:
            out.append(json.loads(rec.getMessage()))
        except (ValueError, TypeError):
            continue
    return out


@pytest.fixture()
def logsink(app):
    """Attach an in-memory handler to app.logger.

    app.logger.propagate is False (production sends JSON events straight to
    stderr, not through the root handler), so caplog can't see them via the
    normal path. Attach directly.
    """
    sink = _EventCapture()
    app.app.logger.addHandler(sink)
    yield sink
    app.app.logger.removeHandler(sink)


def test_login_success_emits_event(client, invite, app, logsink):
    _register(client, invite, "alice")
    client.post("/logout")
    logsink.clear()
    client.post("/login", data={
        "username": "alice", "password": "correct-horse-1", "submit": "Log in",
    })
    evs = [e for e in _events(logsink) if e.get("event") == "login_success"]
    assert len(evs) == 1
    assert evs[0]["username"] == "alice"
    assert "user_id" in evs[0]


def test_login_fail_emits_same_shape_for_bad_user_and_bad_password(client, invite, app, logsink):
    """Log-line shape must not leak which of user-vs-password was wrong."""
    _register(client, invite, "alice")
    client.post("/logout")
    logsink.clear()
    app.limiter.reset()
    client.post("/login", data={
        "username": "nosuchuser", "password": "wrong", "submit": "Log in",
    })
    client.post("/login", data={
        "username": "alice", "password": "wrong", "submit": "Log in",
    })
    fails = [e for e in _events(logsink) if e.get("event") == "login_fail"]
    assert len(fails) == 2
    # Same keys in both — no field says "user_exists" vs "no_such_user".
    assert set(fails[0].keys()) == set(fails[1].keys())


def test_register_success_emits_event(client, invite, app, logsink):
    logsink.clear()
    _register(client, invite, "alice")
    evs = [e for e in _events(logsink) if e.get("event") == "register_success"]
    assert len(evs) == 1
    assert evs[0]["username"] == "alice"


def test_register_fail_bad_invite_logged(client, app, logsink):
    logsink.clear()
    app.limiter.reset()
    client.post("/register", data={
        "invite_code": "not-a-real-code", "username": "alice",
        "password": "correct-horse-1", "confirm": "correct-horse-1",
        "submit": "Create account",
    })
    evs = [e for e in _events(logsink) if e.get("event") == "register_fail"]
    assert len(evs) == 1
    assert evs[0]["reason"] == "bad_invite"


def test_logout_emits_event(client, invite, app, logsink):
    _register(client, invite, "alice")
    logsink.clear()
    client.post("/logout")
    evs = [e for e in _events(logsink) if e.get("event") == "logout"]
    assert len(evs) == 1
    assert evs[0]["username"] == "alice"


def test_account_password_change_emits_event(client, invite, app, logsink):
    _register(client, invite, "alice")
    logsink.clear()
    client.post("/account/password", data={
        "current_password": "correct-horse-1",
        "new_password": "brand-new-passphrase",
        "confirm": "brand-new-passphrase",
        "submit": "Change password",
    })
    evs = [e for e in _events(logsink) if e.get("event") == "account_password_change"]
    assert len(evs) == 1
    assert evs[0]["username"] == "alice"


def test_account_delete_emits_event(client, invite, app, logsink):
    _register(client, invite, "alice")
    logsink.clear()
    client.post("/account/delete", data={
        "confirm_username": "alice",
        "password": "correct-horse-1",
        "submit": "Delete my account",
    })
    evs = [e for e in _events(logsink) if e.get("event") == "account_delete"]
    assert len(evs) == 1
    assert evs[0]["username"] == "alice"


def test_study_session_start_and_finish_events(client, invite, app, logsink):
    _register(client, invite, "alice")
    # Build a 1-card deck.
    alice = app.User.query.filter_by(username="alice").one()
    d = app.Deck(user_id=alice.id, name="French")
    app.db.session.add(d)
    app.db.session.flush()
    app.db.session.add(app.Card(deck_id=d.id, question="chien", answer="dog"))
    app.db.session.commit()

    logsink.clear()
    r = client.post(f"/decks/{d.id}/study",
                    data={"n_cards": 1, "order": "created", "submit": "Start"},
                    follow_redirects=False)
    import re
    sid = int(re.search(r"/sessions/(\d+)", r.headers["Location"]).group(1))
    a = app.StudyAttempt.query.filter_by(session_id=sid, position=0).one()
    client.post(f"/sessions/{sid}/submit",
                data={"attempt_id": a.id, "answer": "dog"})

    starts = [e for e in _events(logsink) if e.get("event") == "study_session_start"]
    finishes = [e for e in _events(logsink) if e.get("event") == "study_session_finish"]
    assert len(starts) == 1
    assert starts[0]["deck_id"] == d.id
    assert starts[0]["n_cards"] == 1
    assert len(finishes) == 1
    assert finishes[0]["session_id"] == sid
    assert finishes[0]["score"] == 1
