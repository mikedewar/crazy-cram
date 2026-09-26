"""Deck creation-with-folder, edit-moves-folder, /decks/<id>/move,
cross-user move rejection."""


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


def _mk_folder(app, user, name="Langs"):
    f = app.Folder(user_id=user.id, name=name)
    app.db.session.add(f)
    app.db.session.commit()
    return f


def _mk_deck(app, user, name="French", folder_id=None):
    d = app.Deck(user_id=user.id, name=name, folder_id=folder_id)
    app.db.session.add(d)
    app.db.session.commit()
    return d


# ---- Create with folder --------------------------------------------

def test_create_deck_defaults_to_unfiled(client, invite, app):
    _register(client, invite, "alice")
    client.post("/decks/new", data={"name": "Loose", "folder_id": "", "submit": "Save deck"})
    d = app.Deck.query.filter_by(name="Loose").one()
    assert d.folder_id is None


def test_create_deck_into_folder(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    f = _mk_folder(app, alice, "Langs")
    r = client.post("/decks/new",
                    data={"name": "French", "folder_id": str(f.id), "submit": "Save deck"},
                    follow_redirects=False)
    d = app.Deck.query.filter_by(name="French").one()
    assert d.folder_id == f.id
    # Redirect should land on the folder detail so the user sees their new deck.
    assert r.status_code in (301, 302)
    assert f"/folders/{f.id}" in r.headers["Location"]


def test_new_deck_page_preselects_folder_from_query(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    f = _mk_folder(app, alice, "Langs")
    r = client.get(f"/decks/new?folder={f.id}")
    assert r.status_code == 200
    # Look for the option marked selected — WTForms renders `selected`
    # against the matching value.
    body = r.data.decode()
    assert f'value="{f.id}"' in body
    assert "selected" in body


def test_new_deck_ignores_invalid_folder_query(client, invite, app):
    _register(client, invite, "alice")
    r = client.get("/decks/new?folder=99999")
    assert r.status_code == 200  # doesn't crash, just no preselect


def test_create_deck_rejects_someone_elses_folder(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    f = _mk_folder(app, alice, "Alice's")
    _login(client, "bob", "correct-horse-2")
    r = client.post("/decks/new",
                    data={"name": "Sneaky", "folder_id": str(f.id), "submit": "Save deck"})
    # _resolve_folder_id → _owned_folder_or_404 → 404 for a foreign folder
    assert r.status_code == 404
    assert app.Deck.query.filter_by(name="Sneaky").count() == 0


# ---- Edit form updates folder --------------------------------------

def test_edit_deck_moves_folder(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    a = _mk_folder(app, alice, "A")
    b = _mk_folder(app, alice, "B")
    deck = _mk_deck(app, alice, "French", folder_id=a.id)
    client.post(f"/decks/{deck.id}/edit",
                data={"name": "French", "folder_id": str(b.id), "submit": "Save deck"})
    assert app.db.session.get(app.Deck, deck.id).folder_id == b.id


def test_edit_deck_unfiles(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    a = _mk_folder(app, alice, "A")
    deck = _mk_deck(app, alice, "French", folder_id=a.id)
    client.post(f"/decks/{deck.id}/edit",
                data={"name": "French", "folder_id": "", "submit": "Save deck"})
    assert app.db.session.get(app.Deck, deck.id).folder_id is None


def test_edit_page_preselects_current_folder(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    f = _mk_folder(app, alice, "Langs")
    deck = _mk_deck(app, alice, "French", folder_id=f.id)
    r = client.get(f"/decks/{deck.id}/edit")
    body = r.data.decode()
    # The current folder's option must be selected.
    import re
    m = re.search(rf'<option[^>]*value="{f.id}"[^>]*>', body)
    assert m is not None and "selected" in m.group(0)


# ---- POST /decks/<id>/move -----------------------------------------

def test_move_deck_between_folders(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    a = _mk_folder(app, alice, "A")
    b = _mk_folder(app, alice, "B")
    deck = _mk_deck(app, alice, "French", folder_id=a.id)
    client.post(f"/decks/{deck.id}/move",
                data={"folder_id": str(b.id), "submit": "Move"})
    assert app.db.session.get(app.Deck, deck.id).folder_id == b.id


def test_move_deck_to_unfiled(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    a = _mk_folder(app, alice, "A")
    deck = _mk_deck(app, alice, "French", folder_id=a.id)
    client.post(f"/decks/{deck.id}/move",
                data={"folder_id": "", "submit": "Move"})
    assert app.db.session.get(app.Deck, deck.id).folder_id is None


def test_move_deck_rejects_foreign_folder(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    alice_folder = _mk_folder(app, alice, "Alice's")
    bob_deck = _mk_deck(app, bob, "Bob's deck")
    _login(client, "bob", "correct-horse-2")
    r = client.post(f"/decks/{bob_deck.id}/move",
                    data={"folder_id": str(alice_folder.id), "submit": "Move"})
    assert r.status_code == 404
    assert app.db.session.get(app.Deck, bob_deck.id).folder_id is None


def test_move_someone_elses_deck_404(client, invite, app):
    alice, bob = _register_two_users(app, client, invite)
    alice_deck = _mk_deck(app, alice, "Alice's deck")
    _login(client, "bob", "correct-horse-2")
    r = client.post(f"/decks/{alice_deck.id}/move",
                    data={"folder_id": "", "submit": "Move"})
    assert r.status_code == 404


def test_move_requires_login(client):
    r = client.post("/decks/1/move", data={"folder_id": ""}, follow_redirects=False)
    assert r.status_code in (301, 302)
    assert "/login" in r.headers["Location"]
