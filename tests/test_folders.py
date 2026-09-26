"""Folder CRUD, uniqueness, delete semantics, cross-user isolation."""


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


def _register_two_users(app, client, invite):
    _register(client, invite, "alice", "correct-horse-1")
    client.post("/logout")
    _register(client, invite, "bob", "correct-horse-2")
    client.post("/logout")
    alice = app.User.query.filter_by(username="alice").one()
    bob = app.User.query.filter_by(username="bob").one()
    return alice, bob


def _mk_deck(app, user, name="French", folder_id=None):
    d = app.Deck(user_id=user.id, name=name, folder_id=folder_id)
    app.db.session.add(d)
    app.db.session.commit()
    return d


def _mk_folder(app, user, name="Languages"):
    f = app.Folder(user_id=user.id, name=name)
    app.db.session.add(f)
    app.db.session.commit()
    return f


# ---- Auth gates -----------------------------------------------------

def test_folders_index_requires_login(client):
    r = client.get("/folders", follow_redirects=False)
    assert r.status_code in (301, 302)
    assert "/login" in r.headers["Location"]


def test_folder_detail_requires_login(client):
    r = client.get("/folders/1", follow_redirects=False)
    assert r.status_code in (301, 302)
    assert "/login" in r.headers["Location"]


# ---- Empty state ----------------------------------------------------

def test_folders_page_empty_state(client, invite):
    _register(client, invite, "alice")
    r = client.get("/folders")
    assert r.status_code == 200
    assert b"don" in r.data.lower() or b"folder" in r.data.lower()


# ---- Create ---------------------------------------------------------

def test_create_folder_happy_path(client, invite, app):
    _register(client, invite, "alice")
    r = client.post("/folders", data={"name": "Languages", "submit": "Save folder"},
                    follow_redirects=True)
    assert r.status_code == 200
    alice = app.User.query.filter_by(username="alice").one()
    assert app.Folder.query.filter_by(user_id=alice.id).count() == 1
    assert app.Folder.query.first().name == "Languages"


def test_create_folder_requires_name(client, invite):
    _register(client, invite, "alice")
    r = client.post("/folders", data={"name": "", "submit": "Save folder"})
    assert r.status_code == 200  # form re-renders with error


def test_create_folder_strips_whitespace(client, invite, app):
    _register(client, invite, "alice")
    client.post("/folders", data={"name": "  Latin  ", "submit": "Save folder"})
    assert app.Folder.query.first().name == "Latin"


def test_create_folder_rejects_over_64_chars(client, invite, app):
    _register(client, invite, "alice")
    client.post("/folders", data={"name": "x" * 65, "submit": "Save folder"})
    assert app.Folder.query.count() == 0


def test_create_folder_accepts_exactly_64_chars(client, invite, app):
    _register(client, invite, "alice")
    client.post("/folders", data={"name": "y" * 64, "submit": "Save folder"})
    assert app.Folder.query.count() == 1


# ---- Uniqueness (per-user) ------------------------------------------

def test_folder_name_unique_per_user(client, invite, app):
    _register(client, invite, "alice")
    r1 = client.post("/folders", data={"name": "Latin", "submit": "Save folder"})
    r2 = client.post("/folders", data={"name": "Latin", "submit": "Save folder"})
    assert r1.status_code in (200, 302)
    assert r2.status_code == 200  # rejected, form re-renders
    alice = app.User.query.filter_by(username="alice").one()
    assert app.Folder.query.filter_by(user_id=alice.id).count() == 1


def test_folder_name_can_repeat_across_users(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    _login(client, "alice", "correct-horse-1")
    client.post("/folders", data={"name": "Latin", "submit": "Save folder"})
    client.post("/logout")
    _login(client, "bob", "correct-horse-2")
    client.post("/folders", data={"name": "Latin", "submit": "Save folder"})
    assert app.Folder.query.filter_by(user_id=alice.id).count() == 1
    assert app.Folder.query.filter_by(user_id=bob.id).count() == 1


# ---- Rename ---------------------------------------------------------

def test_rename_folder_happy_path(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    f = _mk_folder(app, alice, "Old name")
    client.post(f"/folders/{f.id}/rename",
                data={"name": "New name", "submit": "Save folder"},
                follow_redirects=True)
    assert app.db.session.get(app.Folder, f.id).name == "New name"


def test_rename_folder_to_same_name_ok(client, invite, app):
    """A no-op rename must not trip the uniqueness validator."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    f = _mk_folder(app, alice, "Latin")
    r = client.post(f"/folders/{f.id}/rename",
                    data={"name": "Latin", "submit": "Save folder"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert app.db.session.get(app.Folder, f.id).name == "Latin"


def test_rename_folder_to_existing_name_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_folder(app, alice, "Latin")
    other = _mk_folder(app, alice, "Greek")
    client.post(f"/folders/{other.id}/rename",
                data={"name": "Latin", "submit": "Save folder"})
    assert app.db.session.get(app.Folder, other.id).name == "Greek"


# ---- Detail + Unfiled -----------------------------------------------

def test_folder_detail_shows_only_its_decks(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    langs = _mk_folder(app, alice, "Languages")
    _mk_deck(app, alice, "French", folder_id=langs.id)
    _mk_deck(app, alice, "Unfiled deck", folder_id=None)
    r = client.get(f"/folders/{langs.id}")
    assert r.status_code == 200
    assert b"French" in r.data
    assert b"Unfiled deck" not in r.data


def test_folder_unfiled_view_shows_only_unfiled_decks(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    langs = _mk_folder(app, alice, "Languages")
    _mk_deck(app, alice, "French", folder_id=langs.id)
    _mk_deck(app, alice, "Loose", folder_id=None)
    r = client.get("/folders/unfiled")
    assert r.status_code == 200
    assert b"Loose" in r.data
    assert b"French" not in r.data


# ---- Delete ---------------------------------------------------------

def test_delete_empty_folder_removes_it(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    f = _mk_folder(app, alice, "Empty")
    client.post(f"/folders/{f.id}/delete",
                data={"submit": "Delete folder"}, follow_redirects=True)
    assert app.Folder.query.count() == 0


def test_delete_folder_without_checkbox_orphans_decks(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    f = _mk_folder(app, alice, "Langs")
    d = _mk_deck(app, alice, "French", folder_id=f.id)
    client.post(f"/folders/{f.id}/delete",
                data={"submit": "Delete folder"}, follow_redirects=True)
    assert app.Folder.query.count() == 0
    survived = app.db.session.get(app.Deck, d.id)
    assert survived is not None
    assert survived.folder_id is None


def test_delete_folder_with_checkbox_cascades_decks(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    f = _mk_folder(app, alice, "Langs")
    d = _mk_deck(app, alice, "French", folder_id=f.id)
    card = app.Card(deck_id=d.id, question="q", answer="a")
    app.db.session.add(card)
    app.db.session.commit()
    card_id = card.id
    client.post(f"/folders/{f.id}/delete",
                data={"also_delete_decks": "y", "submit": "Delete folder"},
                follow_redirects=True)
    assert app.Folder.query.count() == 0
    assert app.db.session.get(app.Deck, d.id) is None
    # Cascade must also nuke the card via existing Deck→Card cascade.
    assert app.db.session.get(app.Card, card_id) is None


# ---- Cross-user isolation -------------------------------------------

def test_user_cannot_view_other_users_folder(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    f = _mk_folder(app, alice, "Alice's")
    _login(client, "bob", "correct-horse-2")
    r = client.get(f"/folders/{f.id}")
    assert r.status_code == 404


def test_user_cannot_rename_other_users_folder(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    f = _mk_folder(app, alice, "Alice's")
    _login(client, "bob", "correct-horse-2")
    r = client.post(f"/folders/{f.id}/rename",
                    data={"name": "Pwned", "submit": "Save folder"})
    assert r.status_code == 404
    assert app.db.session.get(app.Folder, f.id).name == "Alice's"


def test_user_cannot_delete_other_users_folder(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    f = _mk_folder(app, alice, "Alice's")
    _login(client, "bob", "correct-horse-2")
    r = client.post(f"/folders/{f.id}/delete",
                    data={"submit": "Delete folder"})
    assert r.status_code == 404
    assert app.db.session.get(app.Folder, f.id) is not None


def test_folder_index_only_shows_own(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    _mk_folder(app, alice, "Alice-secrets")
    _mk_folder(app, bob, "Bob-secrets")
    _login(client, "bob", "correct-horse-2")
    r = client.get("/folders")
    assert b"Bob-secrets" in r.data
    assert b"Alice-secrets" not in r.data


# ---- Deleting folder does NOT delete owner or independent decks -----

def test_delete_user_cascades_folders(client, invite, app):
    """User CASCADE on folder should sweep folders when user is deleted."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    _mk_folder(app, alice, "F1")
    _mk_folder(app, alice, "F2")
    app.db.session.delete(alice)
    app.db.session.commit()
    assert app.Folder.query.count() == 0
