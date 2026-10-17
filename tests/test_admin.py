def _register(client, invite, username="alice", password="correct-horse-1"):
    code = invite()
    r = client.post("/register", data={
        "invite_code": code,
        "username": username,
        "password": password,
        "confirm": password,
        "submit": "Create account",
    }, follow_redirects=False)
    assert r.status_code == 302
    return username


def test_admin_requires_login(client):
    r = client.get("/admin")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_admin_hidden_from_non_admin(client, invite):
    _register(client, invite, "alice")
    r = client.get("/admin")
    assert r.status_code == 404


def test_admin_visible_to_configured_admin(client, invite, app, monkeypatch):
    monkeypatch.setattr(app, "ADMIN_USERNAME", "alice")
    _register(client, invite, "alice")
    r = client.get("/admin")
    assert r.status_code == 200
    assert b"Admin" in r.data
    assert b"alice" in r.data
    assert b"Users" in r.data
    assert b"Invites" in r.data


def test_admin_lists_other_users_and_invites(client, invite, app, monkeypatch):
    monkeypatch.setattr(app, "ADMIN_USERNAME", "alice")
    _register(client, invite, "bob")
    client.post("/logout", data={})
    unused_code = invite()
    _register(client, invite, "alice")
    r = client.get("/admin")
    assert r.status_code == 200
    assert b"bob" in r.data
    assert b"alice" in r.data
    assert unused_code.encode() in r.data
    assert b"unused" in r.data
    assert b"used" in r.data
