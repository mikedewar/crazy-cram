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
    return username, code


def _make_admin(app, username):
    u = app.User.query.filter_by(username=username).one()
    u.is_admin = True
    app.db.session.commit()


def test_admin_requires_login(client):
    r = client.get("/admin")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_admin_hidden_from_non_admin(client, invite):
    _register(client, invite, "alice")
    r = client.get("/admin")
    assert r.status_code == 404


def test_admin_overview_hidden_from_non_admin(client, invite):
    _register(client, invite, "alice")
    r = client.get("/admin/overview")
    assert r.status_code == 404


def test_admin_visible_to_admin_user(client, invite, app):
    _register(client, invite, "alice")
    _make_admin(app, "alice")
    r = client.get("/admin")
    assert r.status_code == 200
    assert b"Admin" in r.data


def test_admin_shows_users_and_their_invites(client, invite, app):
    _, bob_code = _register(client, invite, "bob")
    client.post("/logout", data={})
    _, alice_code = _register(client, invite, "alice")
    _make_admin(app, "alice")
    r = client.get("/admin")
    assert r.status_code == 200
    assert b"bob" in r.data
    assert b"alice" in r.data
    assert bob_code.encode() in r.data
    assert alice_code.encode() in r.data


def test_admin_shows_last_login_folders_and_decks(client, invite, app):
    _, _ = _register(client, invite, "bob", password="bob-pass-1")
    # bob now has 1 folder and 2 decks under it
    client.post("/folders/new", data={"name": "study", "submit": "Create folder"})
    folder = app.Folder.query.filter_by(name="study").one()
    client.post(
        "/decks/new",
        data={"name": "d1", "folder_id": folder.id, "submit": "Create deck"},
    )
    client.post(
        "/decks/new",
        data={"name": "d2", "folder_id": folder.id, "submit": "Create deck"},
    )
    client.post("/logout", data={})

    _register(client, invite, "alice")
    _make_admin(app, "alice")

    # Log bob back in so last_login_at is populated.
    client.post("/logout", data={})
    client.post(
        "/login",
        data={"username": "bob", "password": "bob-pass-1", "submit": "Log in"},
    )
    client.post("/logout", data={})
    client.post(
        "/login",
        data={"username": "alice", "password": "correct-horse-1", "submit": "Log in"},
    )

    r = client.get("/admin")
    assert r.status_code == 200
    body = r.data.decode()
    assert "Last login" in body
    assert "Folders" in body
    assert "Decks" in body
    # bob's row should carry 1 folder, 2 decks.
    bob = app.User.query.filter_by(username="bob").one()
    assert bob.last_login_at is not None
    assert app.Folder.query.filter_by(user_id=bob.id).count() == 1
    assert app.Deck.query.filter_by(user_id=bob.id).count() == 2


def test_admin_overview_lists_other_users_and_invites(client, invite, app):
    _register(client, invite, "bob")
    client.post("/logout", data={})
    unused_code = invite()
    _register(client, invite, "alice")
    _make_admin(app, "alice")
    r = client.get("/admin/overview")
    assert r.status_code == 200
    assert b"bob" in r.data
    assert b"alice" in r.data
    assert unused_code.encode() in r.data
    assert b"unused" in r.data
    assert b"used" in r.data
