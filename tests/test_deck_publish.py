"""v1.9.0 — Universal deck sharing: publish, unpublish, copy, edit-lock.

Behaviour contract (from Mike's spec):
  1. Global across all users, self-publish is instant.
  2. Snapshot copy on /universal/<id>/add; redirects to the new deck's
     /edit page.
  3. Published decks are immutable (name/colour/folder/cards). Deleting
     the original does NOT delete downstream copies.
  4. /universal groups by publisher. AliMonkeyBrains's group pinned on
     top, then publishers ordered by most-recent publish time. Decks
     within a group: youngest publish first.
  5. "Add To Decks" → "Already Added" once a copy exists. Cannot copy
     twice.
  6. Owner sees their own published decks alongside everyone else's
     with an "Unpublish" button.
  7. published_at = moment of flip; unpublish leaves existing copies
     intact (source_deck_id ON DELETE SET NULL at the schema level, but
     unpublish just NULLs published_at, which doesn't touch copies).
  8. Admins can unpublish anyone's deck.
"""
from datetime import datetime, timedelta, timezone


def _register(client, invite, username="alice", password="correct-horse-1"):
    code = invite()
    return client.post("/register", data={
        "invite_code": code, "username": username,
        "password": password, "confirm": password,
        "submit": "Create account",
    })


def _login(client, username, password="correct-horse-1"):
    return client.post("/login", data={
        "username": username, "password": password, "submit": "Log in",
    })


def _make_deck(client, name="French", cards=((("q1", "a1"), ("q2", "a2")))):
    r = client.post(
        "/decks/new",
        data={"name": name, "submit": "Save deck"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    deck_id = int(r.headers["Location"].rstrip("/").split("/")[-2])
    for q, a in cards:
        client.post(
            f"/decks/{deck_id}/cards",
            data={"question": q, "answer": a, "submit": "Add card"},
        )
    return deck_id


# ------------------------------------------------------------------ 1.

def test_publish_flips_published_at_to_a_timestamp(client, invite, app):
    _register(client, invite, "alice")
    did = _make_deck(client)
    r = client.post(f"/decks/{did}/publish")
    assert r.status_code == 302
    with app.app.app_context():
        deck = app.db.session.get(app.Deck, did)
        assert deck.published_at is not None
        # Within a minute of now (UTC) — self-publish is instant.
        now = datetime.now(timezone.utc)
        pub = deck.published_at
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        assert abs((now - pub).total_seconds()) < 60


def test_publish_is_idempotent(client, invite, app):
    _register(client, invite, "alice")
    did = _make_deck(client)
    client.post(f"/decks/{did}/publish")
    with app.app.app_context():
        first = app.db.session.get(app.Deck, did).published_at
    client.post(f"/decks/{did}/publish")
    with app.app.app_context():
        second = app.db.session.get(app.Deck, did).published_at
    assert first == second


def test_publish_is_owner_only(client, invite, app):
    """Non-owner POST /decks/<id>/publish must not flip anyone else's deck."""
    _register(client, invite, "alice")
    did = _make_deck(client, "French")
    client.post("/logout")
    _register(client, invite, "bob")
    r = client.post(f"/decks/{did}/publish")
    # _owned_deck_or_404 is 404 for cross-user; the deck must stay personal.
    assert r.status_code in (302, 404)
    with app.app.app_context():
        assert app.db.session.get(app.Deck, did).published_at is None


# ------------------------------------------------------------------ 2.

def test_universal_add_snapshots_cards_and_redirects_to_edit(client, invite, app):
    _register(client, invite, "alice")
    source = _make_deck(client, "French", cards=[("q1", "a1"), ("q2", "a2")])
    client.post(f"/decks/{source}/publish")
    client.post("/logout")

    _register(client, invite, "bob")
    r = client.post(f"/universal/{source}/add", follow_redirects=False)
    assert r.status_code == 302
    # Redirect to /decks/<new_id>/edit per spec.
    assert "/edit" in r.headers["Location"]
    with app.app.app_context():
        bob = app.User.query.filter_by(username="bob").one()
        copies = app.Deck.query.filter_by(user_id=bob.id, source_deck_id=source).all()
        assert len(copies) == 1
        copy = copies[0]
        assert copy.name == "French"
        assert copy.folder_id is None  # lands in Unfiled
        card_qs = {c.question for c in app.Card.query.filter_by(deck_id=copy.id)}
        assert card_qs == {"q1", "q2"}
        # The copy itself is personal, not published.
        assert copy.published_at is None


# ------------------------------------------------------------------ 3.

def test_published_deck_edit_returns_403(client, invite, app):
    _register(client, invite, "alice")
    did = _make_deck(client)
    client.post(f"/decks/{did}/publish")
    r = client.post(
        f"/decks/{did}/edit",
        data={"name": "Edited", "submit": "Save deck"},
    )
    assert r.status_code == 403
    with app.app.app_context():
        assert app.db.session.get(app.Deck, did).name == "French"


def test_published_deck_add_card_returns_403(client, invite, app):
    _register(client, invite, "alice")
    did = _make_deck(client, cards=[("q1", "a1")])
    client.post(f"/decks/{did}/publish")
    r = client.post(
        f"/decks/{did}/cards",
        data={"question": "q2", "answer": "a2", "submit": "Add card"},
    )
    assert r.status_code == 403
    with app.app.app_context():
        assert app.Card.query.filter_by(deck_id=did).count() == 1


def test_published_deck_card_edit_returns_403(client, invite, app):
    _register(client, invite, "alice")
    did = _make_deck(client, cards=[("q1", "a1")])
    client.post(f"/decks/{did}/publish")
    with app.app.app_context():
        card_id = app.Card.query.filter_by(deck_id=did).first().id
    r = client.post(
        f"/cards/{card_id}/edit",
        data={"question": "edited", "answer": "a1", "submit": "Save card"},
    )
    assert r.status_code == 403


def test_published_deck_card_delete_returns_403(client, invite, app):
    _register(client, invite, "alice")
    did = _make_deck(client, cards=[("q1", "a1")])
    client.post(f"/decks/{did}/publish")
    with app.app.app_context():
        card_id = app.Card.query.filter_by(deck_id=did).first().id
    r = client.post(f"/cards/{card_id}/delete")
    assert r.status_code == 403
    with app.app.app_context():
        assert app.Card.query.filter_by(deck_id=did).count() == 1


def test_published_deck_delete_still_works(client, invite, app):
    """Delete remains available on published decks per spec clause 3."""
    _register(client, invite, "alice")
    did = _make_deck(client)
    client.post(f"/decks/{did}/publish")
    r = client.post(f"/decks/{did}/delete")
    assert r.status_code == 302
    with app.app.app_context():
        assert app.db.session.get(app.Deck, did) is None


def test_delete_source_leaves_copies_intact(client, invite, app):
    """Deleting the original must not cascade to downstream copies."""
    _register(client, invite, "alice")
    source = _make_deck(client, "French", cards=[("q1", "a1"), ("q2", "a2")])
    client.post(f"/decks/{source}/publish")
    client.post("/logout")

    _register(client, invite, "bob")
    client.post(f"/universal/{source}/add")
    with app.app.app_context():
        bob = app.User.query.filter_by(username="bob").one()
        copy = app.Deck.query.filter_by(user_id=bob.id, source_deck_id=source).one()
        copy_id = copy.id
    client.post("/logout")

    _login(client, "alice")
    r = client.post(f"/decks/{source}/delete")
    assert r.status_code == 302

    with app.app.app_context():
        surviving = app.db.session.get(app.Deck, copy_id)
        assert surviving is not None
        assert surviving.source_deck_id is None  # ON DELETE SET NULL
        assert app.Card.query.filter_by(deck_id=copy_id).count() == 2


# ------------------------------------------------------------------ 4.

def test_universal_grouping_pins_alimonkeybrains_then_recency(client, invite, app):
    _register(client, invite, "charlie")
    did_charlie = _make_deck(client, "Charlie-1")
    client.post(f"/decks/{did_charlie}/publish")
    client.post("/logout")

    _register(client, invite, "AliMonkeyBrains")
    did_ali = _make_deck(client, "Ali-1")
    client.post(f"/decks/{did_ali}/publish")
    client.post("/logout")

    _register(client, invite, "dora")
    did_dora = _make_deck(client, "Dora-1")
    client.post(f"/decks/{did_dora}/publish")

    # Backdate charlie's publish to prove the ordering is time-based,
    # not insertion-based.
    with app.app.app_context():
        charlie_deck = app.db.session.get(app.Deck, did_charlie)
        charlie_deck.published_at = datetime.now(timezone.utc) - timedelta(days=7)
        ali_deck = app.db.session.get(app.Deck, did_ali)
        ali_deck.published_at = datetime.now(timezone.utc) - timedelta(days=3)
        app.db.session.commit()

    r = client.get("/universal")
    assert r.status_code == 200
    body = r.data.decode()
    pos_ali = body.find("AliMonkeyBrains")
    pos_dora = body.find("dora")
    pos_charlie = body.find("charlie")
    # AliMonkeyBrains pinned first, even though her publish is older than dora's.
    assert 0 <= pos_ali < pos_dora < pos_charlie


# ------------------------------------------------------------------ 5.

def test_cannot_add_the_same_source_twice(client, invite, app):
    _register(client, invite, "alice")
    source = _make_deck(client, "French")
    client.post(f"/decks/{source}/publish")
    client.post("/logout")

    _register(client, invite, "bob")
    client.post(f"/universal/{source}/add")
    client.post(f"/universal/{source}/add")
    with app.app.app_context():
        bob = app.User.query.filter_by(username="bob").one()
        copies = app.Deck.query.filter_by(user_id=bob.id, source_deck_id=source).count()
        assert copies == 1


def test_universal_renders_already_added_button(client, invite, app):
    _register(client, invite, "alice")
    source = _make_deck(client, "French")
    client.post(f"/decks/{source}/publish")
    client.post("/logout")

    _register(client, invite, "bob")
    # First visit: Add To Decks is present.
    r1 = client.get("/universal")
    assert b"Add To Decks" in r1.data
    assert b"Already Added" not in r1.data

    client.post(f"/universal/{source}/add")
    r2 = client.get("/universal")
    assert b"Already Added" in r2.data


# ------------------------------------------------------------------ 6.

def test_owner_sees_unpublish_button_on_universal(client, invite, app):
    _register(client, invite, "alice")
    did = _make_deck(client, "French")
    client.post(f"/decks/{did}/publish")
    r = client.get("/universal")
    assert r.status_code == 200
    assert b"Unpublish" in r.data
    # Should NOT also show the Add To Decks button on your own deck.
    # (Loose check: Add To Decks button text absent.)
    assert b"Add To Decks" not in r.data


# ------------------------------------------------------------------ 7.

def test_unpublish_nulls_published_at_but_leaves_copies(client, invite, app):
    _register(client, invite, "alice")
    source = _make_deck(client, "French")
    client.post(f"/decks/{source}/publish")
    client.post("/logout")

    _register(client, invite, "bob")
    client.post(f"/universal/{source}/add")
    with app.app.app_context():
        bob = app.User.query.filter_by(username="bob").one()
        copy = app.Deck.query.filter_by(user_id=bob.id, source_deck_id=source).one()
        copy_id = copy.id
    client.post("/logout")

    _login(client, "alice")
    r = client.post(f"/decks/{source}/unpublish")
    assert r.status_code == 302
    with app.app.app_context():
        assert app.db.session.get(app.Deck, source).published_at is None
        # Copy survives, still points at the source (which still exists
        # — just no longer published).
        surviving = app.db.session.get(app.Deck, copy_id)
        assert surviving is not None
        assert surviving.source_deck_id == source
        assert app.Card.query.filter_by(deck_id=copy_id).count() == 2


# ------------------------------------------------------------------ 8.

def _make_admin(app, username):
    with app.app.app_context():
        u = app.User.query.filter_by(username=username).one()
        u.is_admin = True
        app.db.session.commit()


def test_admin_can_unpublish_someone_elses_deck(client, invite, app):
    _register(client, invite, "alice")
    did = _make_deck(client, "French")
    client.post(f"/decks/{did}/publish")
    client.post("/logout")

    _register(client, invite, "bob")
    _make_admin(app, "bob")
    client.post("/logout")
    _login(client, "bob", "correct-horse-1")
    r = client.post(f"/decks/{did}/unpublish")
    assert r.status_code == 302
    with app.app.app_context():
        assert app.db.session.get(app.Deck, did).published_at is None


def test_non_admin_cannot_unpublish_someone_elses_deck(client, invite, app):
    _register(client, invite, "alice")
    did = _make_deck(client, "French")
    client.post(f"/decks/{did}/publish")
    client.post("/logout")

    _register(client, invite, "bob")
    r = client.post(f"/decks/{did}/unpublish")
    # Non-owner, non-admin: 404 (don't leak existence).
    assert r.status_code == 404
    with app.app.app_context():
        assert app.db.session.get(app.Deck, did).published_at is not None


# ----- Slider + /home universal tile ---------------------------------

def test_new_deck_slider_creates_published_when_universal_selected(client, invite, app):
    _register(client, invite, "alice")
    r = client.post("/decks/new", data={
        "name": "French", "publish": "1", "submit": "Save deck",
    })
    assert r.status_code == 302
    with app.app.app_context():
        deck = app.Deck.query.filter_by(name="French").one()
        assert deck.published_at is not None


def test_new_deck_defaults_to_personal(client, invite, app):
    _register(client, invite, "alice")
    r = client.post("/decks/new", data={
        "name": "French", "submit": "Save deck",
    })
    assert r.status_code == 302
    with app.app.app_context():
        assert app.Deck.query.filter_by(name="French").one().published_at is None


def test_home_renders_universal_tile_with_global_count(client, invite, app):
    _register(client, invite, "alice")
    _make_deck(client, "A")
    _make_deck(client, "B")
    with app.app.app_context():
        a = app.Deck.query.filter_by(name="A").one()
        b = app.Deck.query.filter_by(name="B").one()
    client.post(f"/decks/{a.id}/publish")
    client.post(f"/decks/{b.id}/publish")
    r = client.get("/home")
    assert r.status_code == 200
    assert b"Universal" in r.data
    assert b"2 deck" in r.data  # the global count flows into the tile


def test_home_universal_tile_counts_across_users(client, invite, app):
    _register(client, invite, "alice")
    did = _make_deck(client, "A")
    client.post(f"/decks/{did}/publish")
    client.post("/logout")

    _register(client, invite, "bob")
    r = client.get("/home")
    # Bob sees the GLOBAL count, including alice's deck.
    assert b"Universal" in r.data
    assert b"1 deck" in r.data


def test_published_deck_cards_page_is_read_only(client, invite, app):
    _register(client, invite, "alice")
    did = _make_deck(client, cards=[("q1", "a1")])
    client.post(f"/decks/{did}/publish")
    r = client.get(f"/decks/{did}/cards")
    assert r.status_code == 200
    # Add-card form absent on a published deck.
    assert b"Add a card" not in r.data
    # Banner reminds the user.
    assert b"published to Universal" in r.data


# ---------------- v1.9.1 — slider fetch, no nested form ------------

def test_deck_edit_slider_is_not_a_nested_form(client, invite, app):
    """The Personal/Universal slider on /edit must NOT be inside a nested
    <form>. Nested forms are invalid HTML and v1.9.0 shipped exactly that
    bug — browsers submitted the outer deck form on toggle, redirecting
    to /home without ever hitting /publish."""
    _register(client, invite, "alice")
    did = _make_deck(client)
    r = client.get(f"/decks/{did}/edit")
    assert r.status_code == 200
    body = r.data.decode()
    # The deck form opens exactly once per page; count '<form' before the
    # first </form> to make sure nothing else opens inside it.
    first_open = body.index("<form")
    first_close = body.index("</form>", first_open)
    inside = body[first_open:first_close]
    assert inside.count("<form") == 1, "nested <form> inside deck form"
    # The slider must have a fetch-handler hook, not an inline submit.
    assert 'id="pub-toggle-' in body
    assert "data-publish-url" in body
    assert "data-unpublish-url" in body


def test_publish_endpoint_accepts_empty_body(client, invite, app):
    """The fetch() slider handler sends an empty POST body with no form
    fields — just the X-CSRFToken header. The publish/unpublish routes
    must not require any form payload."""
    _register(client, invite, "alice")
    did = _make_deck(client)
    # Empty body, no content-type form fields: this is what fetch() sends.
    r = client.post(f"/decks/{did}/publish", data={})
    assert r.status_code in (200, 302)
    with app.app.app_context():
        assert app.Deck.query.get(did).published_at is not None
    # And unpublish from empty body too.
    r = client.post(f"/decks/{did}/unpublish", data={})
    assert r.status_code in (200, 302)
    with app.app.app_context():
        assert app.Deck.query.get(did).published_at is None


def test_edit_slider_data_attrs_point_at_correct_routes(client, invite, app):
    """The edit-mode slider renders data-publish-url + data-unpublish-url
    on the checkbox so the fetch handler can POST to the right endpoint
    on toggle. These URLs must resolve to /decks/<id>/publish and
    /decks/<id>/unpublish respectively."""
    _register(client, invite, "alice")
    did = _make_deck(client)
    r = client.get(f"/decks/{did}/edit")
    body = r.data.decode()
    assert f'data-publish-url="/decks/{did}/publish"' in body
    assert f'data-unpublish-url="/decks/{did}/unpublish"' in body
