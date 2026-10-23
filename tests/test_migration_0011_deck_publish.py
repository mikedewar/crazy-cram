"""Regression test for migration 0011_deck_publish on real file-backed SQLite.

batch_alter_table on `deck` is the dangerous shape: `card`, `study_session`,
and (transitively) `study_attempt` all FK into deck. With PRAGMA foreign_keys=ON
the implicit drop during the rebuild fires those cascades and wipes rows.
The migration disables FKs via _fks_off() to prevent that; these tests prove
it.
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _flask_env(db_path: Path) -> dict:
    env = os.environ.copy()
    env["CRAZY_CRAM_DATABASE_URI"] = f"sqlite:///{db_path}"
    env["FLASK_APP"] = "app.py"
    return env


def _run_migrate(db_path: Path, target: str) -> subprocess.CompletedProcess:
    env = _flask_env(db_path)
    if target == "head":
        cmd = ["db", "upgrade"]
    else:
        current = sqlite3.connect(db_path).execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
        order = [
            "0001_baseline_v0", "0002_flashcards",
            "0003_invite_used_by_set_null", "0004_folders",
            "0005_deck_color", "0006_study_mode", "0007_learn_section",
            "0008_folder_color", "0009_user_is_admin",
            "0010_user_last_login_at", "0011_deck_publish",
        ]
        direction = "upgrade" if order.index(target) > order.index(current) else "downgrade"
        cmd = ["db", direction, target]
    return subprocess.run(
        [sys.executable, "-m", "flask", *cmd],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True,
    )


def _seed_0010_db(db_path: Path):
    """Build a 0010-shaped DB with users, decks, cards, sessions, attempts."""
    env = _flask_env(db_path)
    subprocess.run(
        [sys.executable, "-m", "flask", "db", "upgrade", "0010_user_last_login_at"],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True,
    )
    c = sqlite3.connect(db_path)
    c.execute("PRAGMA foreign_keys=ON")
    # Two users.
    c.execute(
        "INSERT INTO user (id, username, password_hash, created_at, is_admin, last_login_at) "
        "VALUES (1, 'alice', 'x', '2026-01-01', 0, NULL)"
    )
    c.execute(
        "INSERT INTO user (id, username, password_hash, created_at, is_admin, last_login_at) "
        "VALUES (2, 'bob', 'x', '2026-01-01', 0, NULL)"
    )
    # Two decks for alice, one for bob.
    for did, uid, name in [(1, 1, 'French'), (2, 1, 'German'), (3, 2, 'Spanish')]:
        c.execute(
            "INSERT INTO deck (id, user_id, name, created_at, folder_id, "
            "last_opened_at, color) "
            "VALUES (?, ?, ?, '2026-01-01', NULL, NULL, '#fff')",
            (did, uid, name),
        )
    # Four cards per deck.
    cid = 1
    for did in (1, 2, 3):
        for i in range(4):
            c.execute(
                "INSERT INTO card (id, deck_id, question, answer, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, '2026-01-01', '2026-01-01')",
                (cid, did, f"q{cid}", f"a{cid}"),
            )
            cid += 1
    # One study session for alice on deck 1, four attempts.
    c.execute(
        "INSERT INTO study_session (id, user_id, deck_id, n_cards, shuffled, mode, "
        "learn_section, started_at, finished_at, score) "
        "VALUES (1, 1, 1, 4, 1, 'written', NULL, '2026-01-01', '2026-01-01', 2)"
    )
    for i in range(4):
        c.execute(
            "INSERT INTO study_attempt (session_id, card_id, card_snapshot_q, "
            "card_snapshot_a, student_answer, is_correct, position, attempted_at, section) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, '2026-01-01', NULL)",
            (i + 1, f"q{i+1}", f"a{i+1}", f"a{i+1}", i < 2, i),
        )
    c.commit()
    c.close()


def _row_fingerprint(db_path: Path, table: str) -> tuple:
    """Return (count, sorted-rows) for a table. Robust across schema evolution:
    we only compare values of columns that exist on both sides."""
    c = sqlite3.connect(db_path)
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
    rows = c.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY rowid").fetchall()
    c.close()
    return (len(rows), tuple(cols), rows)


def test_upgrade_preserves_all_rows(tmp_path):
    """0010 → 0011 must not drop or null any row in any related table."""
    db = tmp_path / "cc.db"
    _seed_0010_db(db)

    pre_users = _row_fingerprint(db, "user")
    pre_decks_count = _row_fingerprint(db, "deck")[0]
    pre_cards = _row_fingerprint(db, "card")
    pre_sessions = _row_fingerprint(db, "study_session")
    pre_attempts = _row_fingerprint(db, "study_attempt")

    assert pre_users[0] == 2
    assert pre_decks_count == 3
    assert pre_cards[0] == 12
    assert pre_sessions[0] == 1
    assert pre_attempts[0] == 4

    _run_migrate(db, "0011_deck_publish")

    # All counts preserved.
    assert _row_fingerprint(db, "user") == pre_users
    assert _row_fingerprint(db, "deck")[0] == pre_decks_count
    assert _row_fingerprint(db, "card") == pre_cards
    assert _row_fingerprint(db, "study_session") == pre_sessions
    assert _row_fingerprint(db, "study_attempt") == pre_attempts


def test_new_columns_present_and_null(tmp_path):
    db = tmp_path / "cc.db"
    _seed_0010_db(db)
    _run_migrate(db, "0011_deck_publish")

    c = sqlite3.connect(db)
    cols = {r[1] for r in c.execute("PRAGMA table_info(deck)").fetchall()}
    assert "published_at" in cols
    assert "source_deck_id" in cols

    # Every existing deck row has NULL for both.
    nulls = c.execute(
        "SELECT COUNT(*) FROM deck WHERE published_at IS NULL AND source_deck_id IS NULL"
    ).fetchone()[0]
    total = c.execute("SELECT COUNT(*) FROM deck").fetchone()[0]
    assert nulls == total == 3

    # FK is wired: deleting a parent deck SETs NULL on children's source_deck_id.
    c.execute("PRAGMA foreign_keys=ON")
    # Publish deck 1, then make deck 2 a 'copy' of deck 1 by hand.
    c.execute("UPDATE deck SET published_at='2026-10-23' WHERE id=1")
    c.execute("UPDATE deck SET source_deck_id=1 WHERE id=2")
    c.commit()
    c.execute("DELETE FROM deck WHERE id=1")
    c.commit()
    survivor_source = c.execute("SELECT source_deck_id FROM deck WHERE id=2").fetchone()[0]
    assert survivor_source is None
    # Cards on deck 2 untouched (deck 2 wasn't deleted).
    cards_on_deck_2 = c.execute("SELECT COUNT(*) FROM card WHERE deck_id=2").fetchone()[0]
    assert cards_on_deck_2 == 4
    c.close()


def test_round_trip_upgrade_downgrade_upgrade(tmp_path):
    """0010 → 0011 → 0010 → 0011 round-trip preserves all data."""
    db = tmp_path / "cc.db"
    _seed_0010_db(db)
    _run_migrate(db, "0011_deck_publish")
    _run_migrate(db, "0010_user_last_login_at")

    c = sqlite3.connect(db)
    assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0010_user_last_login_at"
    assert c.execute("SELECT COUNT(*) FROM deck").fetchone()[0] == 3
    assert c.execute("SELECT COUNT(*) FROM card").fetchone()[0] == 12
    assert c.execute("SELECT COUNT(*) FROM study_session").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM study_attempt").fetchone()[0] == 4
    cols = [r[1] for r in c.execute("PRAGMA table_info(deck)").fetchall()]
    assert "published_at" not in cols
    assert "source_deck_id" not in cols
    c.close()

    _run_migrate(db, "0011_deck_publish")
    c = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM deck").fetchone()[0] == 3
    assert c.execute("SELECT COUNT(*) FROM card").fetchone()[0] == 12
    assert c.execute("SELECT COUNT(*) FROM study_session").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM study_attempt").fetchone()[0] == 4
    c.close()


def test_cascade_on_delete_still_fires_after_upgrade(tmp_path):
    """Deleting a session should still cascade to its attempts post-migration."""
    db = tmp_path / "cc.db"
    _seed_0010_db(db)
    _run_migrate(db, "0011_deck_publish")

    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("DELETE FROM study_session WHERE id = 1")
    c.commit()
    assert c.execute("SELECT COUNT(*) FROM study_attempt").fetchone()[0] == 0
    c.close()


def test_deck_delete_cascades_to_cards_after_upgrade(tmp_path):
    """Deleting a deck should still cascade to its cards post-migration."""
    db = tmp_path / "cc.db"
    _seed_0010_db(db)
    _run_migrate(db, "0011_deck_publish")

    c = sqlite3.connect(db)
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("DELETE FROM deck WHERE id = 3")  # bob's deck
    c.commit()
    # Cards on deck 3 wiped; others survive.
    assert c.execute("SELECT COUNT(*) FROM card WHERE deck_id=3").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM card").fetchone()[0] == 8
    c.close()
