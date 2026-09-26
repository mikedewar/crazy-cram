# Changelog

## v1.1.0 — 2026-09-26

**Folders.** A one-level organisation layer above decks, plus a "Recently opened" section on the landing page.

- `Folder(id, user_id, name, created_at)` with `UNIQUE(user_id, name)`. One flat level per user, uncapped, private.
- `Deck.folder_id` — nullable FK, `ON DELETE SET NULL`. Existing decks migrate to `folder_id = NULL` (Unfiled).
- `Deck.last_opened_at` — DateTime nullable, indexed. Bumped on `GET /decks/<id>/cards` only.
- Folder CRUD: `/folders`, `/folders/<id>`, `/folders/unfiled`, rename, and delete-with-optional-cascade. Deleting a folder keeps its decks (SET NULL) by default; a checkbox on the confirm page deletes the decks too.
- Deck create/edit gains a folder dropdown. `/decks/new?folder=<id>` preselects. `POST /decks/<id>/move` for standalone move.
- Home page reworked: shows folders (with an Unfiled pseudo-folder) plus a "Recently opened" section listing the top 5 decks by `last_opened_at` with folder chips. Never-opened decks are reached via a folder view.
- All folder routes ownership-gated to `current_user.id` — foreign folders / decks 404 uniformly, including in `/move` and `?folder=` preselect.
- Alembic migration `0004_folders_and_last_opened_at`.
- 207 tests green (was 161; +46 covering folders, deck-folder wiring, and `last_opened_at`).

## v1.0.0 — 2026-09-25

**Milestone 7 — Housekeeping.** Production-ready polish.

- Per-IP rate limits on `POST /login` (10/min) and `POST /register` (5/hour) via Flask-Limiter, in-memory backend by default; storage URI overridable via `CRAZY_CRAM_LIMITER_STORAGE`.
- Structured JSON event log on all auth events (`login_success`, `login_fail`, `logout`, `register_success`, `register_fail`, `account_password_change`, `account_delete`) and session events (`study_session_start`, `study_session_finish`). One line per event on stderr → systemd journal.
- `login_fail` uses the same log-line shape for bad-user and bad-password — no user-enumeration leak.
- `/health` endpoint: no auth, exempt from rate limit; returns `200 {"status":"ok","version":…,"db":"ok"}` or `503` if the DB is unreachable.
- `VERSION` file added; `/health` reports it (override with `CRAZY_CRAM_VERSION`).
- Fixed a Flask-Migrate env.py bug that silently disabled the app's own loggers whenever `flask db upgrade` ran in-process. Pass `disable_existing_loggers=False` to `fileConfig` so the audit log survives startup.
- 161 tests green (was 146; +15 M7 tests).

## v0.7.0 — 2026-09-25

**Milestone 6 — Account self-service.** No manual DB surgery required for account changes.

- `/account` page: change password (current + new + confirm, forces re-login) and delete account (typed-username + password confirm, cascades everything).
- Delete-account cascades to owned decks, cards, sessions, attempts.
- Alembic `0003_invite_used_by_set_null`: rebuilds `invite_code` with `used_by ON DELETE SET NULL` so deleting a user with a linked invite preserves the audit row (code + used_at, used_by → NULL).
- Username-confirm is case-insensitive to match registration/login behaviour.
- 146 tests green.

## v0.6.0 — 2026-09-25

**Milestone 5 — Restart + always-editable cards from results.** Iteration loop polish.

- Restart button on the results page creates a fresh session with the same n_cards + shuffle config, using the deck's **current** cards (the point of restart: the student may have edited a card between sessions).
- Edit-card links on wrong rows carry `?return_to=<session_id>` and jump back to the results page after save. Historical attempt snapshots are preserved — editing a card does not rewrite past `card_snapshot_a` values.
- 130 tests green.

## v0.5.0 — 2026-09-25

**Milestone 4 — Study session (MVP).** A student can pick a deck, answer questions, and see a scored results page with diffs.

- `/decks/<id>/study` — session config (n_cards + shuffle/creation order); empty deck blocks Start with an add-cards prompt.
- `/sessions/<id>` — one card per page, progress bar, Enter submits, blank = wrong, no inline feedback (auto-advance).
- Answer check: trim + collapse whitespace, case-sensitive equality.
- `/sessions/<id>/results` — score, per-card list, character-level diff on wrongs (difflib `SequenceMatcher.get_opcodes`).
- Every attempt is stored with a snapshot of the card's question + answer, so history survives later edits/deletes.
- 118 tests green.

## v0.4.0 — 2026-09-25

**Milestone 3 — Cards CRUD.** A student can build a full deck of cards.

- `/decks/<id>/cards`, `/cards/<id>/edit`, `/cards/<id>/delete`.
- Textareas with 500-char cap per side.
- Cross-user isolation: 404 on foreign card IDs.
- Cascade delete when the parent deck is removed.

## v0.3.0 — 2026-09-25

**Milestone 2 — Decks CRUD.** A student can end-to-end manage decks in the browser.

- `/home` becomes the deck list with card counts and empty-state prompt.
- `/decks/new`, `/decks/<id>/edit`, `/decks/<id>/delete` (POST + confirmation on delete).
- WTForms + CSRF; name required, ≤ 120 chars.

## v0.2.0 — 2026-09-25

**Milestone 1 — Data model & migrations.** Schema in place; nothing user-visible changes.

- SQLAlchemy models: `Deck`, `Card`, `StudySession`, `StudyAttempt` with snapshot columns so attempt history survives edits and deletes.
- Alembic migrations: `0001_baseline_v0` (existing schema) → `0002_flashcards` (four new tables).
- `bin/crazy-cram-initdb` becomes `flask db upgrade`.
- SQLite `PRAGMA foreign_keys=ON` enforced on every connection so cascade rules actually fire.
- Backup: `~/bin/diane-backup` picks up the new instance DB.

## v0.1.0 — pre-plan

**Milestone 0 — Baseline.** Auth, invite codes, user cap, deploy pipeline.

- Flask app + Jinja + Flask-Login + Flask-WTF + Flask-Bcrypt.
- Invite-only self-registration, `MAX_USERS` hard cap.
- `bin/crazy-cram-invite` mints single-use codes.
- systemd user unit + Cloudflare Tunnel deployment.
- 22 tests green.
