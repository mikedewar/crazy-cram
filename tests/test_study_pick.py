"""Tests for 'Select specific questions' subset-picker on /study."""


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


# ---- Config page exposes the new option ----------------------------

def test_config_page_shows_select_specific_option(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 5)
    r = client.get(f"/decks/{d.id}/study")
    assert r.status_code == 200
    assert b"Select specific questions" in r.data
    # Picker link is in the DOM even before select is chosen (JS toggles it).
    assert f"/decks/{d.id}/study/pick".encode() in r.data


# ---- Picker page ---------------------------------------------------

def test_picker_renders_one_checkbox_per_card(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 4)
    r = client.get(f"/decks/{d.id}/study/pick")
    assert r.status_code == 200
    # Four checkboxes (one per card).
    assert r.data.count(b'name="card_ids"') == 4
    assert b"Select all" in r.data
    assert b"Deselect all" in r.data
    assert b"Confirm" in r.data


def test_picker_requires_login(client):
    r = client.get("/decks/1/study/pick", follow_redirects=False)
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_picker_on_others_deck_404(client, invite, app):
    _register(client, invite, "alice")
    client.post("/logout")
    _register(client, invite, "bob")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 3, "AlicesDeck")
    # Bob is logged in.
    r = client.get(f"/decks/{d.id}/study/pick")
    assert r.status_code == 404


def test_picker_empty_deck_redirects_to_study_config(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = app.Deck(user_id=alice.id, name="Empty")
    app.db.session.add(d)
    app.db.session.commit()
    r = client.get(f"/decks/{d.id}/study/pick", follow_redirects=False)
    assert r.status_code == 302
    assert f"/decks/{d.id}/study" in r.headers["Location"]


# ---- Confirm saves and reflects on /study --------------------------

def test_confirm_saves_pick_and_shows_count_on_study(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 5)
    cards = app.Card.query.filter_by(deck_id=d.id).order_by(app.Card.id).all()
    chosen = [cards[0].id, cards[2].id]

    r = client.post(f"/decks/{d.id}/study/pick",
                    data={"card_ids": [str(i) for i in chosen]},
                    follow_redirects=False)
    assert r.status_code == 302
    assert f"/decks/{d.id}/study" in r.headers["Location"]

    r = client.get(f"/decks/{d.id}/study")
    assert r.status_code == 200
    assert b"2 cards picked" in r.data


def test_confirm_empty_rerenders_with_error(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 3)
    r = client.post(f"/decks/{d.id}/study/pick", data={})
    assert r.status_code == 200
    assert b"Pick at least one card" in r.data


def test_clear_picks_removes_count(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 4)
    cards = app.Card.query.filter_by(deck_id=d.id).order_by(app.Card.id).all()
    client.post(f"/decks/{d.id}/study/pick",
                data={"card_ids": [str(cards[0].id)]})
    r = client.get(f"/decks/{d.id}/study")
    assert b"1 card picked" in r.data
    r = client.post(f"/decks/{d.id}/study/pick/clear",
                    follow_redirects=False)
    assert r.status_code == 302
    r = client.get(f"/decks/{d.id}/study")
    assert b"picked" not in r.data


# ---- Start with order=select builds a subset session ----------------

def test_start_with_select_builds_subset_session(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 6)
    cards = app.Card.query.filter_by(deck_id=d.id).order_by(app.Card.id).all()
    picked = [cards[1].id, cards[3].id, cards[5].id]
    client.post(f"/decks/{d.id}/study/pick",
                data={"card_ids": [str(i) for i in picked]})

    r = client.post(f"/decks/{d.id}/study", data={
        "mode": "written", "n_cards": "99",
        "order": "select", "submit": "Start",
    }, follow_redirects=False)
    assert r.status_code == 302
    sess = app.StudySession.query.order_by(app.StudySession.id.desc()).first()
    assert sess is not None
    assert sess.n_cards == 3
    attempt_cards = [a.card_id for a in sess.attempts]
    assert set(attempt_cards) == set(picked)
    # Picks cleared after session start.
    r = client.get(f"/decks/{d.id}/study")
    assert b"picked" not in r.data


def test_start_with_select_no_picks_bounces_to_picker(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 4)
    r = client.post(f"/decks/{d.id}/study", data={
        "mode": "written", "n_cards": "4",
        "order": "select", "submit": "Start",
    }, follow_redirects=False)
    assert r.status_code == 302
    assert "/study/pick" in r.headers["Location"]


def test_picks_pruned_when_card_deleted(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 3)
    cards = app.Card.query.filter_by(deck_id=d.id).order_by(app.Card.id).all()
    client.post(f"/decks/{d.id}/study/pick",
                data={"card_ids": [str(c.id) for c in cards]})
    # Delete one card out from under the saved pick.
    victim = cards[1]
    app.db.session.delete(victim)
    app.db.session.commit()
    r = client.get(f"/decks/{d.id}/study")
    assert r.status_code == 200
    assert b"2 cards picked" in r.data


# ---- Learn mode honours the pick ------------------------------------

def test_learn_with_select_scopes_section1_to_subset(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    # Need >= LEARN_MIN_DECK_SIZE picked cards.
    d = _mk_deck_with_cards(app, alice.id, 12)
    cards = app.Card.query.filter_by(deck_id=d.id).order_by(app.Card.id).all()
    picked = [c.id for c in cards[:5]]  # subset
    client.post(f"/decks/{d.id}/study/pick",
                data={"card_ids": [str(i) for i in picked]})

    r = client.post(f"/decks/{d.id}/study", data={
        "mode": "learn", "n_cards": "99",
        "order": "select", "submit": "Start",
    }, follow_redirects=False)
    assert r.status_code == 302
    sess = app.StudySession.query.order_by(app.StudySession.id.desc()).first()
    assert sess.mode == "learn"
    sec1_card_ids = {
        a.card_id for a in sess.attempts if a.section == 1
    }
    assert sec1_card_ids == set(picked)


def test_learn_select_below_floor_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 20)
    cards = app.Card.query.filter_by(deck_id=d.id).order_by(app.Card.id).all()
    # Pick fewer than LEARN_MIN_DECK_SIZE.
    picked = [cards[0].id, cards[1].id]
    client.post(f"/decks/{d.id}/study/pick",
                data={"card_ids": [str(i) for i in picked]})
    r = client.post(f"/decks/{d.id}/study", data={
        "mode": "learn", "n_cards": "99",
        "order": "select", "submit": "Start",
    }, follow_redirects=True)
    # No session created — we're back on /study.
    assert r.status_code == 200
    sess = app.StudySession.query.first()
    assert sess is None


def test_learn_section_5_scoped_to_picked_subset(client, invite, app):
    """Section 5 (review-all) must re-review only the picked cards, not
    the whole deck — otherwise 'study specific questions' leaks back to
    the full deck halfway through Learn."""
    import re

    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 20)
    cards = app.Card.query.filter_by(deck_id=d.id).order_by(app.Card.id).all()
    picked = [c.id for c in cards[:6]]
    client.post(f"/decks/{d.id}/study/pick",
                data={"card_ids": [str(i) for i in picked]})

    r = client.post(f"/decks/{d.id}/study", data={
        "mode": "learn", "n_cards": "99",
        "order": "select", "submit": "Start",
    }, follow_redirects=False)
    assert r.status_code == 302
    m = re.search(r"/sessions/(\d+)/learn$", r.headers["Location"])
    assert m
    sid = int(m.group(1))

    # Play perfectly through sections 1-4, advancing between each.
    for section in range(1, 5):
        attempts = (
            app.StudyAttempt.query
            .filter_by(session_id=sid, section=section)
            .order_by(app.StudyAttempt.position.asc())
            .all()
        )
        for a in attempts:
            client.post(f"/sessions/{sid}/learn/submit",
                        data={"attempt_id": a.id, "answer": a.card_snapshot_a})
        client.get(f"/sessions/{sid}/learn")
        client.post(f"/sessions/{sid}/learn/advance",
                    data={"from_section": section})

    # Section 5 attempts must be exactly the picked subset.
    s5 = app.StudyAttempt.query.filter_by(session_id=sid, section=5).all()
    assert {a.card_id for a in s5} == set(picked)


def test_mc_select_below_floor_rejected(client, invite, app):
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck_with_cards(app, alice.id, 10)
    cards = app.Card.query.filter_by(deck_id=d.id).order_by(app.Card.id).all()
    picked = [cards[0].id, cards[1].id]  # < MC_MIN_DECK_SIZE
    client.post(f"/decks/{d.id}/study/pick",
                data={"card_ids": [str(i) for i in picked]})
    r = client.post(f"/decks/{d.id}/study", data={
        "mode": "mc", "n_cards": "99",
        "order": "select", "submit": "Start",
    }, follow_redirects=True)
    assert r.status_code == 200
    sess = app.StudySession.query.first()
    assert sess is None
