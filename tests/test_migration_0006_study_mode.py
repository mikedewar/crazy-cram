"""Regression test for migration 0006_study_mode on real file-backed SQLite.

The in-memory pytest fixture doesn't exercise `flask db upgrade` from an
0005 state against a populated DB — but that's the dangerous path. SQLite's
batch_alter_table rebuilds the table in-place; with PRAGMA foreign_keys=ON
(as the app sets per-connection) dropping study_session cascades to
study_attempt via ON DELETE CASCADE and wipes every row. The migration
disables FKs around the batch rebuild to prevent that.

These tests fail against a buggy migration (no _fks_off wrapper) and pass
against the fixed one.
"""
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


def _run_migrate(db_path: Path, target: str) -> subprocess.CompletedProcess:
    """Migrate db to `target`. 'head' goes up to head; otherwise we ask
    alembic for the current rev and up/down accordingly."""
    env = os.environ.copy()
    env["CRAZY_CRAM_DATABASE_URI"] = f"sqlite:///{db_path}"
    env["FLASK_APP"] = "app.py"
    if target == "head":
        cmd = ["db", "upgrade"]
    else:
        # Figure out direction. If target is at or below the current rev,
        # downgrade; otherwise upgrade. Simpler proxy: just try upgrade,
        # fall back to downgrade.
        current = sqlite3.connect(db_path).execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
        # Order of migrations we know about:
        order = ["0001_baseline_v0", "0002_flashcards",
                 "0003_invite_used_by_set_null", "0004_folders",
                 "0005_deck_color", "0006_study_mode", "0007_learn_section"]
        direction = "upgrade" if order.index(target) > order.index(current) else "downgrade"
        cmd = ["db", direction, target]
    return subprocess.run(
        [sys.executable, "-m", "flask", *cmd],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True,
    )


def _seed_0005_db(db_path: Path):
    """Build an 0005-shaped DB with a user, deck, cards, session, attempts."""
    env = os.environ.copy()
    env["CRAZY_CRAM_DATABASE_URI"] = f"sqlite:///{db_path}"
    env["FLASK_APP"] = "app.py"
    # Upgrade to just 0005.
    subprocess.run(
        [sys.executable, "-m", "flask", "db", "upgrade", "0005_deck_color"],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True,
    )
    # Pump some seed data in.
    c = sqlite3.connect(db_path)
    c.execute("PRAGMA foreign_keys=ON")
    c.execute(
        "INSERT INTO user (id, username, password_hash, created_at) "
        "VALUES (1, 'alice', 'x', '2026-01-01')"
    )
    c.execute(
        "INSERT INTO deck (id, user_id, name, created_at, folder_id, last_opened_at, color) "
        "VALUES (1, 1, 'French', '2026-01-01', NULL, NULL, '#fff')"
    )
    for i in range(4):
        c.execute(
            "INSERT INTO card (id, deck_id, question, answer, created_at, updated_at) "
            "VALUES (?, 1, ?, ?, '2026-01-01', '2026-01-01')",
            (i + 1, f"q{i}", f"a{i}"),
        )
    c.execute(
        "INSERT INTO study_session (id, user_id, deck_id, n_cards, shuffled, "
        "started_at, finished_at, score) "
        "VALUES (1, 1, 1, 4, 1, '2026-01-01', '2026-01-01', 2)"
    )
    for i in range(4):
        c.execute(
            "INSERT INTO study_attempt (session_id, card_id, card_snapshot_q, "
            "card_snapshot_a, student_answer, is_correct, position, attempted_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, '2026-01-01')",
            (i + 1, f"q{i}", f"a{i}", f"a{i}", i < 2, i),
        )
    c.commit()
    c.close()


def test_upgrade_preserves_study_attempts(tmp_path):
    """0005 → 0006 must not drop study_attempt rows."""
    db = tmp_path / "cc.db"
    _seed_0005_db(db)

    c = sqlite3.connect(db)
    pre_attempts = c.execute("SELECT COUNT(*) FROM study_attempt").fetchone()[0]
    pre_sessions = c.execute("SELECT COUNT(*) FROM study_session").fetchone()[0]
    c.close()
    assert pre_attempts == 4
    assert pre_sessions == 1

    _run_migrate(db, "0006_study_mode")

    c = sqlite3.connect(db)
    assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0006_study_mode"
    assert c.execute("SELECT COUNT(*) FROM study_attempt").fetchone()[0] == pre_attempts
    assert c.execute("SELECT COUNT(*) FROM study_session").fetchone()[0] == pre_sessions
    # All existing sessions get mode='written'.
    modes = dict(c.execute("SELECT mode, COUNT(*) FROM study_session GROUP BY mode").fetchall())
    assert modes == {"written": 1}
    c.close()


def test_round_trip_upgrade_downgrade_upgrade(tmp_path):
    """0005 → 0006 → 0005 → 0006 round-trip preserves all data."""
    db = tmp_path / "cc.db"
    _seed_0005_db(db)
    _run_migrate(db, "0006_study_mode")
    _run_migrate(db, "0005_deck_color")

    c = sqlite3.connect(db)
    assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0005_deck_color"
    assert c.execute("SELECT COUNT(*) FROM study_attempt").fetchone()[0] == 4
    assert c.execute("SELECT COUNT(*) FROM study_session").fetchone()[0] == 1
    cols = [r[1] for r in c.execute("PRAGMA table_info(study_session)").fetchall()]
    assert "mode" not in cols
    c.close()

    _run_migrate(db, "0006_study_mode")
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM study_attempt").fetchone()[0] == 4
    assert c.execute("SELECT COUNT(*) FROM study_session").fetchone()[0] == 1
    c.close()


def test_cascade_on_delete_still_fires_after_upgrade(tmp_path):
    """Deleting a session should still cascade to its attempts post-migration."""
    db = tmp_path / "cc.db"
    _seed_0005_db(db)
    _run_migrate(db, "0006_study_mode")

    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("DELETE FROM study_session WHERE id = 1")
    c.commit()
    assert c.execute("SELECT COUNT(*) FROM study_attempt").fetchone()[0] == 0
    c.close()
