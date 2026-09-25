"""M1 model + migration tests.

Covers the four new tables (Deck, Card, StudySession, StudyAttempt):
round-trip, cascade delete, snapshot survives card deletion, char-limit boundary,
and that the migration chain actually installed the tables.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import DataError


def _mk_user(app, username="alice"):
    user = app.User(
        username=username,
        password_hash=app.bcrypt.generate_password_hash("correct-horse-1").decode(),
    )
    app.db.session.add(user)
    app.db.session.commit()
    return user


def _mk_deck(app, user, name="French"):
    deck = app.Deck(user_id=user.id, name=name)
    app.db.session.add(deck)
    app.db.session.commit()
    return deck


def _mk_card(app, deck, q="chat", a="cat"):
    card = app.Card(deck_id=deck.id, question=q, answer=a)
    app.db.session.add(card)
    app.db.session.commit()
    return card


# -- Migration chain ---------------------------------------------------

def test_migration_chain_created_all_expected_tables(app):
    tables = set(inspect(app.db.engine).get_table_names())
    assert {"user", "invite_code", "deck", "card",
            "study_session", "study_attempt", "alembic_version"}.issubset(tables)


def test_alembic_version_stamped_at_head(app):
    row = app.db.session.execute(
        app.db.text("SELECT version_num FROM alembic_version")
    ).fetchone()
    assert row is not None
    assert row[0] == "0002_flashcards"


# -- Model round-trip --------------------------------------------------

def test_deck_round_trip(app):
    user = _mk_user(app)
    deck = _mk_deck(app, user, "French")

    fetched = app.Deck.query.filter_by(id=deck.id).one()
    assert fetched.name == "French"
    assert fetched.user_id == user.id
    assert fetched.created_at is not None


def test_card_round_trip(app):
    user = _mk_user(app)
    deck = _mk_deck(app, user)
    card = _mk_card(app, deck, "chien", "dog")

    fetched = app.Card.query.filter_by(id=card.id).one()
    assert fetched.question == "chien"
    assert fetched.answer == "dog"
    assert fetched.deck_id == deck.id
    assert fetched.created_at is not None
    assert fetched.updated_at is not None


def test_study_session_and_attempt_round_trip(app):
    user = _mk_user(app)
    deck = _mk_deck(app, user)
    card = _mk_card(app, deck, "bonjour", "hello")

    sess = app.StudySession(
        user_id=user.id, deck_id=deck.id,
        n_cards=1, shuffled=False,
    )
    app.db.session.add(sess)
    app.db.session.commit()

    attempt = app.StudyAttempt(
        session_id=sess.id, card_id=card.id,
        card_snapshot_q="bonjour", card_snapshot_a="hello",
        student_answer="hello", is_correct=True,
        position=0, attempted_at=datetime.now(timezone.utc),
    )
    app.db.session.add(attempt)
    app.db.session.commit()

    fetched = app.StudyAttempt.query.filter_by(id=attempt.id).one()
    assert fetched.card_snapshot_q == "bonjour"
    assert fetched.is_correct is True
    assert fetched.session.deck_id == deck.id
    assert fetched.session.user_id == user.id


# -- Cascade behaviour -------------------------------------------------

def test_deleting_deck_cascades_to_cards(app):
    user = _mk_user(app)
    deck = _mk_deck(app, user)
    _mk_card(app, deck)
    _mk_card(app, deck, "chien", "dog")
    assert app.Card.query.filter_by(deck_id=deck.id).count() == 2

    app.db.session.delete(deck)
    app.db.session.commit()

    assert app.Card.query.filter_by(deck_id=deck.id).count() == 0


def test_deleting_deck_cascades_to_sessions_and_attempts(app):
    user = _mk_user(app)
    deck = _mk_deck(app, user)
    card = _mk_card(app, deck)

    sess = app.StudySession(user_id=user.id, deck_id=deck.id, n_cards=1, shuffled=False)
    app.db.session.add(sess)
    app.db.session.commit()

    app.db.session.add(app.StudyAttempt(
        session_id=sess.id, card_id=card.id,
        card_snapshot_q="q", card_snapshot_a="a",
        position=0,
    ))
    app.db.session.commit()

    assert app.StudySession.query.count() == 1
    assert app.StudyAttempt.query.count() == 1

    app.db.session.delete(deck)
    app.db.session.commit()

    assert app.StudySession.query.count() == 0
    assert app.StudyAttempt.query.count() == 0


def test_deleting_user_cascades_to_decks(app):
    user = _mk_user(app)
    _mk_deck(app, user, "French")
    _mk_deck(app, user, "Capitals")
    assert app.Deck.query.filter_by(user_id=user.id).count() == 2

    app.db.session.delete(user)
    app.db.session.commit()

    assert app.Deck.query.filter_by(user_id=user.id).count() == 0


def test_deleting_card_sets_attempt_card_id_null_but_snapshot_survives(app):
    user = _mk_user(app)
    deck = _mk_deck(app, user)
    card = _mk_card(app, deck, "bonjour", "hello")

    sess = app.StudySession(user_id=user.id, deck_id=deck.id, n_cards=1, shuffled=False)
    app.db.session.add(sess)
    app.db.session.commit()

    attempt = app.StudyAttempt(
        session_id=sess.id, card_id=card.id,
        card_snapshot_q="bonjour", card_snapshot_a="hello",
        student_answer="hello", is_correct=True, position=0,
    )
    app.db.session.add(attempt)
    app.db.session.commit()
    attempt_id = attempt.id

    app.db.session.delete(card)
    app.db.session.commit()

    survived = app.StudyAttempt.query.get(attempt_id)
    assert survived is not None
    assert survived.card_id is None                # FK cleared by ON DELETE SET NULL
    assert survived.card_snapshot_q == "bonjour"   # historical record intact
    assert survived.card_snapshot_a == "hello"
    assert survived.student_answer == "hello"
    assert survived.is_correct is True


# -- Column-cap sanity -------------------------------------------------

def test_card_side_at_500_chars_is_accepted(app):
    user = _mk_user(app)
    deck = _mk_deck(app, user)
    long_side = "x" * 500
    card = app.Card(deck_id=deck.id, question=long_side, answer=long_side)
    app.db.session.add(card)
    app.db.session.commit()

    fetched = app.Card.query.get(card.id)
    assert len(fetched.question) == 500
    assert len(fetched.answer) == 500


def test_card_side_cap_matches_model_constant(app):
    assert app.CARD_SIDE_MAX == 500
    # And the schema column matches.
    q_col = inspect(app.db.engine).get_columns("card")
    q_col_map = {c["name"]: c for c in q_col}
    # SQLAlchemy String types expose length; SQLite reflects VARCHAR(500).
    assert q_col_map["question"]["type"].length == 500
    assert q_col_map["answer"]["type"].length == 500


# -- Cross-user isolation basics (data-model level) ---------------------

def test_two_users_can_have_decks_with_the_same_name(app):
    a = _mk_user(app, "alice")
    b = _mk_user(app, "bob")
    _mk_deck(app, a, "French")
    _mk_deck(app, b, "French")

    assert app.Deck.query.count() == 2
    assert {d.user_id for d in app.Deck.query.all()} == {a.id, b.id}
