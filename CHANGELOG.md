# Changelog

## v1.9.12 — 2026-10-24

**Globe-with-strike icon finally renders.** v1.9.11's `color: #222` on
`.icon-btn` fixed the hover (no more blue square) but the SVG strokes
were still invisible — Firefox's UA button rendering swallows `color`
before SVG `currentColor` can see it. Target the SVG directly:

```
.icon-btn svg { stroke: #222; }
.icon-btn-danger:hover svg { stroke: #c3413a; }
```

The hardcoded `stroke="#000000"` on the delete-card SVG was a prior
workaround for exactly this bug; the new rule generalises the fix so
it applies to every `.icon-btn` SVG without template changes.

## v1.9.11 — 2026-10-24

**Fix: `.icon-btn` SVGs now actually render when the button is a
`<button>`.** On the globe-with-strike Unpublish button, Mike saw
"blue square on hover, no icon at rest" — because `.icon-btn`
set `color: inherit`, but a `<button>` loses `inherit` to its UA
style and SVG `currentColor` resolved to white (invisible on pale
tiles). Set `.icon-btn { color: #222 }` explicitly instead; works
across `<a>`/`<summary>`/`<button>` uniformly. Also added explicit
`background: transparent; border-color: #8886` to `.icon-btn:hover`
so it stops picking up the global blue-button hover.

Visible result: Unpublish globe shows up as a dark icon on all
tiles. Delete-card button on `/decks/<id>/cards` still works (its
SVG hard-coded `stroke="#000000"` as a prior workaround for this
same cause; left alone, black ≈ #222).

## v1.9.10 — 2026-10-24

**Version string under the GitHub icon in the sidebar.** `v<X.Y.Z>`
sits at the very bottom of every page, small and dimmed so it stays
out of the way. Also makes "which version am I actually looking
at?" visible at a glance — relevant after yesterday's HTML-cache
rodeo. `app_version` plumbed through the base context; sidebar
`:nth-last-child(2)` selector updated so GitHub still anchors to
the bottom cluster above the version string.

## v1.9.9 — 2026-10-24

**Dynamic HTML pages are no longer browser-cached.** v1.9.8 shipped
the globe-with-strike Unpublish icon, but Mike's Firefox kept
serving a cached pre-v1.9.4 copy of `/universal` for ten-plus
minutes after deploy — only the "Save to folder" icon rendered on
each tile, no Unpublish. The static CSS cache-buster
(`?v=<VERSION>-<mtime>`) does nothing if the HTML itself is stale.
Added an `after_request` that stamps `Cache-Control: no-store` on
every non-static HTML response. CSRF-stamped per-user pages
shouldn't be cached anyway; static assets are untouched (they
still cache aggressively via the existing cache-buster).

## v1.9.8 — 2026-10-24

**Unpublish icon is now a globe with a line through it, not a trash
can.** The trash-can read as "destroy this deck" but Unpublish only
flips the deck private — the owner still has it. The new icon
(circle + equator + meridian, matching the universal glyph used
elsewhere, with a diagonal strike) says "remove from Universal",
which is what the action actually does. `.icon-btn-danger` dropped
too, since the hover state was reinforcing the destruction framing.
`aria-label`/`title` unchanged ("Unpublish" / "Unpublish (admin)")
so existing tests and screen readers see the same text.

## v1.9.7 — 2026-10-24

**`/universal`: trash-can Unpublish, no more "Already Added".**
Unpublish is now the same `.icon-btn-danger` trash-can SVG used
elsewhere (owners get it; admins viewing someone else's deck get
"Unpublish (admin)" as the aria-label). The "Already Added"
button is gone — Save-to-folder is always available on non-owner
tiles. The one-copy-per-source cap was lifted at the same time, so
re-saving a deck now creates an independent second copy (e.g. into
a different folder). The `already_added_ids` plumbing (view +
template) was dropped since nothing reads it anymore. Two existing
tests flipped to the new intent + docstring rule 5 updated.

## v1.9.6 — 2026-10-24

**"Save to folder" is now a floppy-disk icon button**, using the
same `.icon-btn` chrome as the existing pencil/trash controls so it
sits visually in the row rather than crowding it with text. Full
"Save to folder" string lives in `aria-label` + `title` for
accessibility and tooltip. No behavioural change; same picker opens
on click.

## v1.9.5 — 2026-10-23

**Fix: admins now see "Save to folder" on `/universal`.** v1.9.4's
template branch rendered "Unpublish (admin)" in place of the Save
picker whenever the viewer was an admin, so for the only two admins
on the system (mikedewar + AliMonkeyBrains) the Save button never
appeared on any deck. Branches reshaped: owner-only sees Unpublish;
everyone else sees Save to folder (or Already Added if copied);
admins who don't own the deck additionally get Unpublish (admin)
alongside Save/Already Added. New test covers the admin + Save-to-
folder combo.

## v1.9.4 — 2026-10-23

**Save to folder picker on `/universal`.** Each universal deck tile
now carries a "Save to folder" button in place of the old "Add To
Decks" button. Clicking opens a `<details>` popover listing the
user's folders (plus "Unfiled" as the first entry); picking one
copies the deck straight into that folder, instead of always landing
in Unfiled. `POST /universal/<id>/add` accepts an optional
`folder_id` form field — blank/missing → Unfiled; owned folder id →
that folder; non-integer → 400; another user's id → 404 per the
cross-user isolation rule. The deck tile is promoted above later
sibling tiles while the picker is open (`:has()` + `z-index: 9999`)
so the popover can escape downward without being painted over by the
next row. 5 new tests.

## v1.9.3 — 2026-10-23

**Fix: `/universal` deck tiles render exactly like folder-page tiles.**
The universal page had its own `.universal-tile` layout — a short,
rectangular tile without the stack-of-three stacked backing cards. It
also set `background-color: {{ deck.color }}` on the tile directly
instead of the `--deck-color` custom property that the stacking
pseudo-elements read, so even when a tile was coloured it showed the
default `#e8e8e8` grey backing. Rewrote the template to reuse the
same `.deck-tile` structure (jitter custom props, `--deck-color`
plumbing, `.deck-tile-name` / `.deck-tile-actions`) as
`folders/detail.html`, and added `card_count` to the view so each tile
can show the N cards line. Published-date meta sits under the card
count. Dropped the `.universal-tile*` CSS block.

## v1.9.2 — 2026-10-23

**Fix: can type into the deck name field on `/decks/new` again.** The
v1.9.0 slider rewrite added `disabled=published` to the WTForms field
renders in `deck_form.html`, but the `/new` view never passed
`published` into the template context. Jinja silently resolved that
to `Undefined`, which WTForms rendered as `disabled=""` — making the
name input and folder dropdown non-interactive. Pass `published=False`
on `/new` so the fields render editable; regression test asserts no
`disabled` attribute on either tag.

## v1.9.1 — 2026-10-23

**Fix: Personal/Universal slider on deck edit no longer navigates away
or silently fails.** The previous shipped slider nested a secondary
`<form>` inside the deck edit form (invalid HTML). Browsers quietly
dropped the inner form, so flipping the slider submitted the OUTER
deck form instead — redirecting to `/home` without ever hitting the
publish/unpublish endpoint, which is why the deck never appeared under
Universal.

Rewritten as a plain checkbox + `fetch()` handler that POSTs to the
publish/unpublish endpoint (with CSRF header), then reloads so the
edit-lock banner reflects the new state. No page navigation on flip;
state change is now what the slider does.

## v1.9.0 — 2026-10-23

**Deck sharing — the Universal folder.** Any deck can be flipped to
Universal via a new Personal/Universal slider on the deck edit (and
new) page. Published decks appear in a global **Universal** folder
on `/home` (grey globe swatch, sits above Unfiled). Inside
`/universal`, everyone's published decks are grouped by creator:
AliMonkeyBrains's group pinned to the top, then publishers in
most-recent-publish order. Each tile has one button:

- **Add To Decks** — snapshot-copies the deck and its cards into your
  Unfiled, drops you straight on `/edit` to rename/recolour/refile.
- **Already Added** — once you've copied a given source deck, you
  can't copy it a second time.
- **Unpublish** — owner's own tiles show this; admins see it on every
  tile. Unpublishing hides the deck from `/universal` but existing
  copies survive.

**Edit-locked while published.** You can't rename, recolour, move, or
add/edit/delete cards on a deck while it's published — flip it back
to Personal first. Deleting the deck still works; downstream copies
survive via `source_deck_id ON DELETE SET NULL` at the schema level.

**Schema change:** migration `0011_deck_publish` adds `published_at`
and `source_deck_id` to `deck`, wrapped in the `_fks_off()` guard that
every `batch_alter_table` on a parent table needs. 22 new tests cover
the full behaviour contract; test total 305 → 327.

## v1.8.3 — 2026-10-21

**More breathing room between rows on `/stats`.** Table cells go from
`0 .35rem` to `.35rem .35rem` so each row of donuts gets its own
vertical gutter.

## v1.8.2 — 2026-10-21

**Donuts switch to green/red.** Correct slice is now `#4a9d5f` (the
same green the end-of-session results page uses on `.result-row.right`)
and incorrect is `#c3413a` (same red as `.result-row.wrong`). "Right =
green, wrong = red" is now one visual language across the app.

Deck colour still identifies the row — it stays on the swatch next to
the deck name.

## v1.8.1 — 2026-10-21

**Stats page polish.** Deck-name row headers were laid out as `display:
flex`, which stopped `vertical-align: middle` on the `<th>` from
working — the text floated above the donuts' centrelines. Flex moves
to an inner `<span>` so the `<th>` itself stays `table-cell` and the
baseline aligns with the donut geometric centres.

Donut colours now have real contrast. Previous: bright = raw deck
colour, dull = 35% colour + 65% white (pastel decks lost their dull
slice entirely). Now: bright = 75% of each channel (deepens the hue),
dull = 15% deck colour + 85% light grey (`#e8e8e8`). Correct vs
incorrect is readable at 40px.

## v1.8.0 — 2026-10-21

**Stats page: small-multiples of every finished study session.** New
`/stats` route, one table per folder, one row per deck, one column per
completed session (oldest → newest, ragged right — a deck's row is
only as long as its session history). Each cell is a tiny donut:
correct answers in a bright shade of the deck colour, incorrect +
skipped in a dulled shade. Partial (unfinished) sessions are ignored.
Learn-mode sessions use the final run-through (§5) only, so a Learn
donut summarises how well you ended up, not how many times you
scrambled on the way there. A donut icon in the sidebar links to it —
above the GitHub button for everyone, above the admin shield for
admins. Admins see only their own stats; `/stats` is per-user.

No schema change — reuses the existing `StudySession` and
`StudyAttempt` tables already created by migrations 0006/0007.

## v1.7.4 — 2026-10-21

**Admin table gains last-login, folder-count and deck-count columns.**
`/admin` now shows three more columns per user: last login time, number
of folders, number of decks. A new nullable `user.last_login_at`
column (migration 0010) is stamped on every successful password check.
Pre-existing users show `—` for last login until they next sign in.

## v1.7.3 — 2026-10-21

**Sidebar no longer overlaps `main` on narrow viewports.** The sidebar
is `position: fixed`, so `main` previously centered itself ignoring the
sidebar and slid under it as the viewport shrank. Below 52rem, `main`
now reserves the sidebar's column (sidebar width + gutters = 5.25rem)
and shrinks against it instead.

## v1.7.2 — 2026-10-21

**Admin sidebar icon.** For admin users only, a shield icon appears in
the sidebar directly above the GitHub button and links to `/admin`.
Rendered in `base.html` so it's present on every page. Non-admin users
and anonymous visitors never see it.

## v1.7.1 — 2026-10-21

**Admin page shows users and their invite tokens.** `/admin` now has
a two-column table (username, invite token) — the token column is the
`invite_code.code` that was redeemed to create the account. Users with
no redeemed invite (shouldn't happen, but handle it) show an em dash.

## v1.7.0 — 2026-10-21

**Admin role.** The admin gate is now a `User.is_admin` boolean rather
than a hard-coded username env var.

- New column `user.is_admin` (bool, default false). Migration
  `0009_user_is_admin` adds it, wrapped in `_fks_off()`, and promotes
  the bootstrap admin (`CRAZY_CRAM_BOOTSTRAP_ADMIN`, default
  `mikedewar`) to admin on upgrade.
- `/admin` is now a blank page (just a page header and a back link);
  the previous dashboard moved to `/admin/overview`.
- `_require_admin()` checks `current_user.is_admin`; non-admins still
  get 404 (unchanged UX).
- Removed `ADMIN_USERNAME` module global.

## v1.6.0 — 2026-10-21

**Folder colours.** Each folder now has its own colour, shown as a small
coloured square to the left of the folder name on the home page and the
folders list page.

- New `FOLDER_PALETTE` of 10 vibrant hues (crimson, orange, amber, teal,
  emerald, ocean, cobalt, violet, magenta, moss) — distinct from the
  pastel deck palette.
- Random colour assigned when a folder is created.
- Click the swatch to open a palette picker and recolour the folder;
  posts to `/folders/<id>/color`. Non-palette values are rejected (400).
- The Unfiled pseudo-folder gets a neutral grey swatch (not pickable).
- Migration `0008_folder_color` adds a nullable `folder.color` string(9)
  column and backfills existing rows with random palette picks. Wrapped
  in `_fks_off()` per the SQLite batch FK trap.
- CSS: a `.folder-swatch` square (1.4rem) in a `<details>` popover, with
  dark-mode canvas colour for the popover.

## v1.5.0 — 2026-10-19

**Learn study mode.** A new guided 5-section study progression,
selected on `/decks/<id>/study` as the third option alongside Written
and Flashcards. Needs 4+ cards (same gate as MC).

- §1: multiple choice over every card in the deck.
- §2: multiple choice over the cards you got wrong in §1.
- §3: written over the cards you got right in §1 OR §2.
- §4: multiple choice over the cards you got wrong in §2 OR §3.
- §5: written over every card in the deck.
- Between every section: an interstitial page showing that section's
  score and a right/wrong breakdown, with "Next section →" at the top.
  Empty sections still get an interstitial saying "nothing to review"
  so the five-step progression is always visible.
- Final results header is §5 score (`§5 right / §5 total`); a
  "most-missed" panel ranks cards by total wrongs across all 5
  sections; §5 marking shows each card's cumulative right/wrong record
  across the whole run.
- One `StudySession` per Learn run (not five); mid-run abandonment
  leaves `finished_at IS NULL`. Added `study_session.learn_section`
  and `study_attempt.section` as explicit section state (migration
  `0007_learn_section`, wrapped in `_fks_off()` per the SQLite batch
  FK trap).

## v1.4.2 — 2026-10-19

**Flashcard focus ring fix.** On hover/click the flashcard was showing
a thick blue border on only two sides. Cause: the `.flashcard` button
retains focus after a click, and its `outline` was being projected
through the surrounding `perspective: 1200px` / `preserve-3d`
transform, so the outline rendered asymmetrically depending on which
face was front.

- Replace `.flashcard` outline with a `box-shadow` on the inner
  `.flashcard-face` (which lives inside the 3D context in the right
  place), gated on `:focus-visible` so a mouse click no longer leaves
  a sticky ring.
- Explicitly remove the browser default `:focus` outline on the
  button so a plain click never shows a ring.

## v1.4.1 — 2026-10-19

**Study cards now use the deck's own colour.** All three study modes
render the card as a square tile in the deck's palette, matching the
deck tile on the folder page. Flashcard back face is rendered in a
slightly darker shade (brightness 0.9) so you can tell front from back
during the flip.

- New shared `.study-card` class (square aspect ratio, deck-coloured
  background via `--deck-color` inline var, no stack-of-three jitter,
  no icons). Used by `study_session.html` for the written/MC question
  panel and by both faces of the flashcard.
- `study_flashcard.html`: both faces wrapped in `.study-card`; `.flashcard`
  button loses its own sizing (handled by the shared class) and keeps
  just the 3D flip bits (`transform-style`, `rotateY`, `backface-visibility`).
- `.flashcard .flashcard-back` gets `filter: brightness(0.9)` so the
  back of the card is visibly a darker shade of the same colour.
- Dark mode: deck pastels stay as-is (same as deck tiles); only cards
  without a colour fall back to the dark panel colour.
- 2 new tests confirming the deck colour reaches both the flashcard
  and the written-mode question panel.

## v1.4.0 — 2026-10-19

**Flashcards mode.** A third study mode alongside Written and Multiple
choice. One card foregrounded at a time, tap or Space to flip (both
directions, any number of times), then self-grade Right / Wrong. No
schema change — reuses `StudySession.mode` with a new value `flashcard`.

- `STUDY_MODES` gains `"flashcard"`; `StudyConfigForm.mode` gains a third
  radio ("Flashcards"); enabled at any card count ≥ 1.
- `templates/study_flashcard.html`: progress bar, a `<button>` card with
  3D CSS flip (`transform: rotateY(180deg)` + `backface-visibility`),
  hint text showing the Space shortcut, Wrong/Right submit buttons.
- `study_session` branches on `s.mode == "flashcard"` and renders the new
  template; `study_submit` reads `self_grade` from the form (`right` →
  `is_correct=True`, `wrong` → `False`), leaves `student_answer` NULL.
  Rejects missing/bogus `self_grade` with 400.
- `templates/study_results.html` adds a flashcard branch: shows the
  card's answer and whether the student self-graded it right or wrong.
- Restart carries flashcard mode forward (same path as MC/written).
- 11 new tests cover: config radio renders & enabled at 1 card; session
  renders flip card + grade buttons; DB shape; right/wrong record;
  missing/bogus grade rejected; full end-to-end session scoring; restart
  preserves mode; cross-user 404 isolation.
- 236 tests green on the suite.

## v1.3.2 — 2026-10-19

**Home page slimmed down to folder-first navigation.** The home page is now
purely a folder index: one "+ New folder" button, the Unfiled tile stays as
a first-class entry so orphaned decks remain reachable, and the folders list
is it. Everything deck-level — opening, creating, studying — lives inside a
folder page.

- `templates/home.html`: single "+ New folder" button in both empty and
  populated states; icon-btn next to the "Folders" heading removed; the
  "Recently opened" grid removed entirely (including the WIP stack-of-three
  jitter in that section). Unfiled tile preserved.
- `app.py` `home()` view: dropped the `recent_rows` query and template kwarg;
  `unfiled_count` kept. `last_opened_at` column itself unchanged — the bump
  behaviour still runs on `GET /decks/<id>/cards` for any future surface
  that wants it.
- Deck-tile WIP from v1.3.0-era now folded in: `folders/detail.html` +
  `deck_cards.html` + `study_session.html` + `static/style.css` — stable
  per-deck stack-of-three jitter (CSS vars seeded from `deck.id`), MC
  study-mode radio-dot visually hidden with auto-advance on `change`,
  dedicated Skip button posts blank, `prefers-color-scheme` dark mode,
  keyboard-only `:focus-visible` ring.
- Schema unchanged — no migration.
- 225 tests green (home-page tests retargeted at folder-detail where deck
  tiles still render; new guards cover the "no recent", "no new deck", and
  "Unfiled tile present" invariants).

## v1.3.1 — 2026-10-18

**Mode picker moved onto the study-config page.** Deck tiles go back to one
"Study" button; the written / multiple-choice choice lives inside
`/decks/<id>/study` as a radio in the config form.

- `StudyConfigForm` gains a `mode` RadioField (`written` default, `mc`
  disabled when the deck has fewer than 4 cards).
- `study_config` route reads `form.mode.data` instead of `?mode=mc`; a POST
  with `mode=mc` on a sub-4-card deck is rejected with a flash and redirect
  (no session created).
- `templates/home.html` and `templates/folders/detail.html` collapse their
  two-button block to one "Study" button.
- `templates/study_config.html` loses its header-fork and `<input
  type="hidden" name="mode">` — mode is just another form field now.
- Schema unchanged from v1.3.0 — no migration needed on deploy.
- 231 tests green (same count: deck-tile tests rewritten, config-redirect
  test replaced with radio-visibility + POST-rejection coverage).

## v1.3.0 — 2026-10-18

**Multiple-choice as a study mode, not a card type.** Decks with ≥4 cards get a
"Multiple choice" button next to "Written study". Picks 1 correct + 3 random
distractors from other cards' answers in the same deck; options are generated
per-attempt at render time (not persisted). Keeps the single schema path we had
in v1.1.1 — no `card_type`, no per-card distractor table.

- `StudySession.mode` ('written' | 'mc'), default 'written'. Existing sessions
  backfill as 'written'.
- `/decks/<id>/study?mode=mc` starts an MC session when the deck has ≥4 cards;
  below that, redirects to written-mode config with a flash. Bogus modes fall
  back to written.
- Study page renders a radio group when `session.mode == 'mc'`; same submit
  path, same `answers_match()` scoring (exact string match).
- Results page drops the char-diff view for MC rows — picks aren't typed, so
  "You picked X / Correct was Y" is clearer than a per-char diff.
- Restart carries the mode forward; if the deck shrank below MC's floor between
  sessions, restart falls back to written mode with a flash.
- Deck tiles on `/home` and `/folders/<id>` now label the first study button
  "Written study"; "Multiple choice" appears only when `card_count >= 4`.
- Migration `0006_study_mode` wraps `batch_alter_table` in `_fks_off()` to
  stop the SQLite rebuild from cascading `study_attempt` wipeouts — same
  pattern as the (now-reverted) card-types fix. Rehearsed on a byte-identical
  copy of the live DB: 11 users / 19 decks / 244 cards / 70 sessions / 1146
  attempts preserved on upgrade; 0 null card_ids before or after.
- 231 tests green (+18: 15 MC behaviour + 3 migration regression against a
  file-backed SQLite DB).

## v1.1.2 — 2026-10-18

**Roll back card types.** v1.2.0 (card types: written / MC / TF) and the
subsequent v1.2.1 duplicate-answer-field fix are reverted. Multiple-choice
and true/false didn't earn their complexity. The one MC card that was created
on live (deck 6, "how much poop?" / "so much poop!") is preserved as a plain
written card. Historical attempts (1146) retain their `card_id` and
snapshot columns; the `card_type` and `options_json` columns are dropped
with migration `0006` on downgrade. No user-visible data was lost — only
the type classification on one card and the empty `card_distractor` table
go away.

- Reverted commits: `1fee38e` (card types), `bdc0409` (0006 FK fix),
  `bcfc191` (MC duplicate-answer form fix).
- Alembic downgrade `0006_card_types → 0005_deck_color` rehearsed against
  a byte-identical copy of the live DB: 11 users / 19 decks / 244 cards /
  70 sessions / 1146 attempts / 0 null card_ids preserved; `card_distractor`
  and the new columns dropped cleanly.
- Also re-applied the pre-existing `test_home_has_new_folder_link` test
  (previously renamed in v1.2.0) so the suite stays green at this commit.
- 213 tests green.

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
