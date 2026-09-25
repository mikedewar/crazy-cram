# Crazy-Cram — Build Plan

Milestones for the v1 flashcard rebuild. Each milestone ends in something shippable to production with tests green. Cut a git tag at the end of each one so we can roll back cleanly. Numbers are not time estimates — they're ordering.

---

## Milestone 0 — Baseline (already done ✅)

- Flask app, auth, invite codes, 30-user cap, systemd unit, Cloudflare Tunnel, 22 tests green.
- Tagged as `v0.1.0` for the record.

---

## Milestone 1 — Data model & migrations

**Goal**: schema in place; nothing user-visible changes.

- Add SQLAlchemy models: `Deck`, `Card`, `StudySession`, `StudyAttempt` (per REQUIREMENTS §9).
- Add `student_answer`/`card_snapshot_*` fields so history survives edits/deletes.
- Introduce Alembic (or Flask-Migrate) so future schema changes don't need drop-and-recreate.
- Baseline migration = current schema; second migration adds the four new tables.
- `bin/crazy-cram-initdb` becomes `alembic upgrade head`.
- Tests: model round-trip, cascade-delete rules, DB constraint on 500-char cap.

**Ship criterion**: `pytest -q` green; deployed app still behaves identically for existing users; new tables exist and are empty.

**Tag**: `v0.2.0`

---

## Milestone 2 — Decks CRUD

**Goal**: student can create, rename, and delete decks; `/home` shows their deck list.

- Routes: `/home` (deck list), `/decks/new`, `/decks/<id>/edit`, `/decks/<id>/delete`.
- Templates + minimal styling reusing existing look.
- Empty-state on `/home` ("Make your first deck").
- Forms: WTForms with CSRF; deck name required, ≤ 120 chars.
- Delete requires POST + confirmation (typed-name unnecessary at deck level; single-click confirm is enough).
- Tests: create/rename/delete happy path, name required, cross-user isolation (student A can't see/edit student B's deck).

**Ship criterion**: student can end-to-end manage decks in the browser.

**Tag**: `v0.3.0`

---

## Milestone 3 — Cards CRUD

**Goal**: student can add/edit/delete cards inside a deck.

- Routes: `/decks/<id>/cards` (list + add), `/cards/<id>/edit`, `/cards/<id>/delete`.
- Card form: question + answer, each ≤ 500 chars (`textarea`, char counter).
- Deck-detail view shows card list with edit/delete links.
- Tests: CRUD happy path, cross-user isolation, char limit rejected, cascade delete when deck removed.

**Ship criterion**: student can build a full deck of cards.

**Tag**: `v0.4.0`

---

## Milestone 4 — Study session (the core feature)

**Goal**: student can run a session end-to-end and see results.

- Route: `/decks/<id>/study` — session config page.
  - Number of cards (default = all in deck).
  - Order (shuffle / creation order).
  - If deck empty → no Start button, "add cards first" link (per Q14).
- On Start: create `StudySession`, snapshot the chosen card order into `StudyAttempt` rows with `position` set but `student_answer`/`is_correct` null.
- Route: `/sessions/<id>` — active study loop.
  - One card per page. Progress bar ("3 of 12").
  - Enter submits; empty submit = blank counts wrong.
  - On submit: server records the attempt, redirect (or fetch) to the next card.
  - No inline feedback (auto-advance — per Q13).
- Answer check: trim + collapse whitespace, case-sensitive equality against `card.answer`.
- Route: `/sessions/<id>/results` — score, per-card list, char-level diff on wrong ones, Restart button, edit-card link on wrongs.
- Char diff: use Python's `difflib.ndiff` or `SequenceMatcher.get_opcodes` server-side, render with `<span class="diff-ins">`/`<span class="diff-del">`.
- Tests: full session flow via test client; whitespace tolerance; case sensitivity; blank = wrong; results page renders diff; session config with empty deck blocks Start.

**Ship criterion**: a student can pick a deck, answer questions, and see a scored results page with diffs. **This is the MVP.**

**Tag**: `v0.5.0` — announce internally, invite the actual student to try it.

---

## Milestone 5 — Restart + always-editable cards from results

**Goal**: polish the study loop.

- Restart button on `/sessions/<id>/results` = create a new session with the same config.
- Edit-card links on wrong rows jump to `/cards/<id>/edit` and return to results after save.
- Tests: restart creates a distinct session with same params; edit-from-results preserves the historical attempt snapshot (edit does not rewrite past results).

**Ship criterion**: iteration loop for a struggling student feels smooth.

**Tag**: `v0.6.0`

---

## Milestone 6 — Account self-service

**Goal**: student can change password and delete their account.

- Route: `/account` with two sections: change password, delete account.
- Change password: current + new + confirm; bcrypt re-hash; force re-login.
- Delete account: type username to confirm; cascades to decks, cards, sessions, attempts, invite-code link.
- Tests: change-password wrong-current rejected; delete removes all owned rows; deleted user can't log back in.

**Ship criterion**: no manual DB surgery required for account changes.

**Tag**: `v0.7.0`

---

## Milestone 7 — Housekeeping

**Goal**: production-ready polish.

- Rate-limit `/login` and `/register` (Flask-Limiter, in-memory backend fine at 30 users).
- Structured logging on auth events (login/logout/register/delete-account) and session events (start/finish).
- Small `/health` endpoint (returns 200 + version + db-reachable) — makes it easier to wire monitoring later.
- README updated for the new feature set; screenshots optional.
- `CHANGELOG.md` covering the whole v1 arc.

**Ship criterion**: comfortable letting a small group of real students use it.

**Tag**: `v1.0.0`

---

## Cross-cutting rules (apply through every milestone)

- **Tests first or alongside.** No merge to `main` with red tests. Every milestone adds tests for its new surface.
- **Cross-user isolation** tested on every new route that touches user-owned data. This is the biggest single risk in a shared-hostname app.
- **All destructive actions are POST + confirmation.**
- **Migrations are forward-only** in production; rollbacks happen by deploying a new migration, not by downgrading.
- **CSS/JS budget**: keep it vanilla and small. No SPA framework. Progressive enhancement — the app must work with JS disabled for the auth flows; JS is only for niceties in the study loop (focus management, Enter handling).
- **Backups**: `~/bin/diane-backup` already covers `~/apps/crazy-cram/instance/*.db` if we add the path — do that in Milestone 1 so we're not sorry later.

---

## What's deliberately not in the plan

- Sessions/history UI (deferred — data is captured, screens come post-v1).
- Import/export beyond the CRUD forms.
- Password reset flow.
- Anything from REQUIREMENTS §8 (non-goals).

If any of those become urgent, they slot in as v1.1+.
