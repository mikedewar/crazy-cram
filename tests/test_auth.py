def test_root_redirects_anonymous_to_login(client):
    r = client.get("/")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/login")


def test_login_page_renders(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert b"Crazy-Cram" in r.data
    assert b"Log in" in r.data
    assert b'href="/register"' in r.data


def test_register_page_renders(client):
    r = client.get("/register")
    assert r.status_code == 200
    assert b"Invite code" in r.data


def test_register_requires_valid_invite(client):
    r = client.post("/register", data={
        "invite_code": "definitely-not-real",
        "username": "alice",
        "password": "correct-horse-1",
        "confirm": "correct-horse-1",
        "submit": "Create account",
    })
    assert r.status_code == 200
    assert b"Invalid or already-used invite code" in r.data


def test_register_valid_invite_creates_and_logs_in(client, invite, app):
    code = invite()
    r = client.post("/register", data={
        "invite_code": code,
        "username": "alice",
        "password": "correct-horse-1",
        "confirm": "correct-horse-1",
        "submit": "Create account",
    }, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/home")

    assert app.User.query.count() == 1
    user = app.User.query.first()
    assert user.username == "alice"
    assert user.password_hash != "correct-horse-1"

    used = app.InviteCode.query.filter_by(code=code).first()
    assert used.used_at is not None
    assert used.used_by == user.id

    home = client.get("/home")
    assert home.status_code == 200
    assert b"alice" in home.data


def test_invite_code_single_use(client, invite):
    code = invite()
    ok = client.post("/register", data={
        "invite_code": code, "username": "alice",
        "password": "correct-horse-1", "confirm": "correct-horse-1",
        "submit": "Create account",
    })
    assert ok.status_code == 302

    client.post("/logout")

    r = client.post("/register", data={
        "invite_code": code, "username": "bob",
        "password": "correct-horse-2", "confirm": "correct-horse-2",
        "submit": "Create account",
    })
    assert r.status_code == 200
    assert b"Invalid or already-used invite code" in r.data


def test_username_conflict_rejected(client, invite):
    c1, c2 = invite(), invite()
    client.post("/register", data={
        "invite_code": c1, "username": "alice",
        "password": "correct-horse-1", "confirm": "correct-horse-1",
        "submit": "Create account",
    })
    client.post("/logout")
    r = client.post("/register", data={
        "invite_code": c2, "username": "ALICE",
        "password": "correct-horse-2", "confirm": "correct-horse-2",
        "submit": "Create account",
    })
    assert r.status_code == 200
    assert b"username is taken" in r.data


def test_password_confirm_must_match(client, invite):
    code = invite()
    r = client.post("/register", data={
        "invite_code": code, "username": "alice",
        "password": "correct-horse-1", "confirm": "different-pass-1",
        "submit": "Create account",
    })
    assert r.status_code == 200
    assert b"Passwords must match" in r.data


def test_password_min_length(client, invite):
    code = invite()
    r = client.post("/register", data={
        "invite_code": code, "username": "alice",
        "password": "short", "confirm": "short",
        "submit": "Create account",
    })
    assert r.status_code == 200
    assert b"between 8 and 128" in r.data or b"Field must be" in r.data


def test_username_charset_enforced(client, invite):
    code = invite()
    r = client.post("/register", data={
        "invite_code": code, "username": "alice bob!",
        "password": "correct-horse-1", "confirm": "correct-horse-1",
        "submit": "Create account",
    })
    assert r.status_code == 200
    assert b"Letters, digits" in r.data


def test_user_cap_enforced(client, invite, app):
    for i in range(3):
        c = invite()
        client.post("/register", data={
            "invite_code": c, "username": f"user{i}",
            "password": "correct-horse-1", "confirm": "correct-horse-1",
            "submit": "Create account",
        })
        client.post("/logout")

    assert app.User.query.count() == 3
    c = invite()
    r = client.post("/register", data={
        "invite_code": c, "username": "overflow",
        "password": "correct-horse-1", "confirm": "correct-horse-1",
        "submit": "Create account",
    })
    assert r.status_code == 200
    assert b"Registration closed" in r.data
    assert app.User.query.count() == 3


def _register(client, invite, username="alice", password="correct-horse-1"):
    code = invite()
    return client.post("/register", data={
        "invite_code": code, "username": username,
        "password": password, "confirm": password,
        "submit": "Create account",
    })


def test_login_with_correct_credentials(client, invite):
    _register(client, invite, "alice", "correct-horse-1")
    client.post("/logout")

    r = client.post("/login", data={
        "username": "alice", "password": "correct-horse-1", "submit": "Log in",
    })
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/home")


def test_login_is_case_insensitive_on_username(client, invite):
    _register(client, invite, "Alice", "correct-horse-1")
    client.post("/logout")
    r = client.post("/login", data={
        "username": "ALICE", "password": "correct-horse-1", "submit": "Log in",
    })
    assert r.status_code == 302


def test_login_wrong_password_fails(client, invite):
    _register(client, invite, "alice", "correct-horse-1")
    client.post("/logout")
    r = client.post("/login", data={
        "username": "alice", "password": "wrong-password-1", "submit": "Log in",
    })
    assert r.status_code == 200
    assert b"Invalid username or password" in r.data


def test_login_unknown_user_fails(client):
    r = client.post("/login", data={
        "username": "ghost", "password": "correct-horse-1", "submit": "Log in",
    })
    assert r.status_code == 200
    assert b"Invalid username or password" in r.data


def test_home_requires_login(client):
    r = client.get("/home", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_logout_requires_login(client):
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_logout_ends_session(client, invite):
    _register(client, invite, "alice", "correct-horse-1")
    assert client.get("/home").status_code == 200
    client.post("/logout")
    r = client.get("/home", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_authenticated_user_hitting_root_goes_home(client, invite):
    _register(client, invite, "alice", "correct-horse-1")
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/home")


def test_authenticated_user_hitting_login_goes_home(client, invite):
    _register(client, invite, "alice", "correct-horse-1")
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/home")


def test_password_is_hashed_not_stored_plain(client, invite, app):
    _register(client, invite, "alice", "correct-horse-1")
    user = app.User.query.filter_by(username="alice").first()
    assert user.password_hash != "correct-horse-1"
    assert user.password_hash.startswith("$2")


def test_secret_key_file_created_and_locked(app):
    from pathlib import Path
    p = Path(app.__file__).parent / "instance" / "secret_key"
    assert p.exists()
    mode = p.stat().st_mode & 0o777
    assert mode == 0o600
