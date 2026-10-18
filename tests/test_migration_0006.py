"""Regression test for migration 0006_card_types.

The pytest fixtures use in-memory DBs that stamp the schema directly
and skip the migration chain entirely. 0006 shipped with a bug where
``batch_alter_table("study_attempt")`` ran with ``PRAGMA foreign_keys=ON``
and nulled every ``study_attempt.card_id`` via the ON DELETE SET NULL
cascade firing against the temp-table rebuild.

This test exercises the real ``flask db upgrade`` CLI against a
file-backed SQLite copy, with the app's own connect-time FK pragma
in effect, and asserts no card_id gets nulled.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


APP_DIR = Path(__file__).resolve().parent.parent


def _migrate_from_scratch(db_path: Path, target: str) -> None:
    """Run `flask db upgrade <target>` against db_path."""
    env = dict(os.environ)
    env["CRAZY_CRAM_DATABASE_URI"] = f"sqlite:///{db_path}"
    env["FLASK_APP"] = "app.py"
    cmd = [str(APP_DIR / "venv" / "bin" / "flask"), "db", "upgrade", target]
    if not Path(cmd[0]).exists():
        cmd = [sys.executable, "-m", "flask", "db", "upgrade", target]
    subprocess.run(cmd, cwd=APP_DIR, env=env, check=True, capture_output=True)


def test_0006_upgrade_preserves_study_attempt_card_id(tmp_path):
    """Pre-seed a 0005 DB with cards+attempts, upgrade to 0006, prove no nulls."""
    db = tmp_path / "regression.db"
    # Stand up schema up to and including 0005.
    _migrate_from_scratch(db, "0005_deck_color")

    # Seed one user, one deck, one card, one session, one attempt.
    with sqlite3.connect(str(db)) as con:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute(
            "INSERT INTO user (id, username, password_hash, created_at) "
            "VALUES (1, 'u', 'x', CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO deck (id, user_id, name, created_at, color) "
            "VALUES (1, 1, 'd', CURRENT_TIMESTAMP, '#fff')"
        )
        con.execute(
            "INSERT INTO card (id, deck_id, question, answer, created_at, updated_at) "
            "VALUES (1, 1, 'q', 'a', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO study_session (id, user_id, deck_id, n_cards, shuffled, started_at, score) "
            "VALUES (1, 1, 1, 1, 0, CURRENT_TIMESTAMP, 0)"
        )
        con.execute(
            "INSERT INTO study_attempt "
            "(id, session_id, card_id, card_snapshot_q, card_snapshot_a, "
            " student_answer, is_correct, position, attempted_at) "
            "VALUES (1, 1, 1, 'q', 'a', 'a', 1, 0, CURRENT_TIMESTAMP)"
        )
        con.commit()

    # Upgrade to 0006.
    _migrate_from_scratch(db, "0006_card_types")

    # Verify.
    with sqlite3.connect(str(db)) as con:
        con.execute("PRAGMA foreign_keys=ON")
        attempts = con.execute("SELECT id, card_id, card_type FROM study_attempt").fetchall()
        cards = con.execute("SELECT id, card_type, mc_random FROM card").fetchall()
    assert attempts == [(1, 1, "written")], f"card_id was nulled or card_type wrong: {attempts}"
    assert cards == [(1, "written", None)], f"card backfill wrong: {cards}"


def test_0006_round_trip(tmp_path):
    """Upgrade -> downgrade -> upgrade must preserve every attempt row."""
    db = tmp_path / "roundtrip.db"
    _migrate_from_scratch(db, "0005_deck_color")

    with sqlite3.connect(str(db)) as con:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute(
            "INSERT INTO user (id, username, password_hash, created_at) "
            "VALUES (1, 'u', 'x', CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO deck (id, user_id, name, created_at, color) "
            "VALUES (1, 1, 'd', CURRENT_TIMESTAMP, '#fff')"
        )
        for cid in (1, 2, 3):
            con.execute(
                "INSERT INTO card (id, deck_id, question, answer, created_at, updated_at) "
                "VALUES (?, 1, 'q', 'a', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (cid,),
            )
        con.execute(
            "INSERT INTO study_session (id, user_id, deck_id, n_cards, shuffled, started_at, score) "
            "VALUES (1, 1, 1, 3, 0, CURRENT_TIMESTAMP, 0)"
        )
        for aid, cid in enumerate((1, 2, 3), start=1):
            con.execute(
                "INSERT INTO study_attempt "
                "(id, session_id, card_id, card_snapshot_q, card_snapshot_a, "
                " student_answer, is_correct, position, attempted_at) "
                "VALUES (?, 1, ?, 'q', 'a', 'a', 1, ?, CURRENT_TIMESTAMP)",
                (aid, cid, aid - 1),
            )
        con.commit()

    _migrate_from_scratch(db, "0006_card_types")
    _migrate_from_scratch(db, "0005_deck_color")

    with sqlite3.connect(str(db)) as con:
        pairs = con.execute("SELECT id, card_id FROM study_attempt ORDER BY id").fetchall()
    assert pairs == [(1, 1), (2, 2), (3, 3)], f"downgrade lost card_id links: {pairs}"

    _migrate_from_scratch(db, "0006_card_types")

    with sqlite3.connect(str(db)) as con:
        pairs = con.execute("SELECT id, card_id, card_type FROM study_attempt ORDER BY id").fetchall()
    assert pairs == [(1, 1, "written"), (2, 2, "written"), (3, 3, "written")], \
        f"re-upgrade lost card_id or type: {pairs}"


def test_0006_fk_cascade_still_fires_after_upgrade(tmp_path):
    """Deleting a card should SET NULL on linked attempts, not fail silently."""
    db = tmp_path / "cascade.db"
    _migrate_from_scratch(db, "0005_deck_color")

    with sqlite3.connect(str(db)) as con:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute(
            "INSERT INTO user (id, username, password_hash, created_at) "
            "VALUES (1, 'u', 'x', CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO deck (id, user_id, name, created_at, color) "
            "VALUES (1, 1, 'd', CURRENT_TIMESTAMP, '#fff')"
        )
        con.execute(
            "INSERT INTO card (id, deck_id, question, answer, created_at, updated_at) "
            "VALUES (1, 1, 'q', 'a', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO study_session (id, user_id, deck_id, n_cards, shuffled, started_at, score) "
            "VALUES (1, 1, 1, 1, 0, CURRENT_TIMESTAMP, 0)"
        )
        con.execute(
            "INSERT INTO study_attempt "
            "(id, session_id, card_id, card_snapshot_q, card_snapshot_a, "
            " student_answer, is_correct, position, attempted_at) "
            "VALUES (1, 1, 1, 'q', 'a', 'a', 1, 0, CURRENT_TIMESTAMP)"
        )
        con.commit()

    _migrate_from_scratch(db, "0006_card_types")

    with sqlite3.connect(str(db)) as con:
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("DELETE FROM card WHERE id = 1")
        con.commit()
        rows = con.execute("SELECT id, card_id FROM study_attempt").fetchall()
    assert rows == [(1, None)], f"ON DELETE SET NULL did not fire: {rows}"
