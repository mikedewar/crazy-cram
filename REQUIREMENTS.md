# Crazy-Cram — Requirements (v1)

Flashcard web app for students (12–15) to learn languages or other flashcard-friendly material. Two modes: **create cards** and **study cards**. Runs on the existing Crazy-Cram Flask app (invite-code auth, 30-user cap).

---

## 1. Users & access

- Auth stack unchanged from v0: username + password, invite-code self-registration, cap 30 users.
- All content is **per-student and private**. No sharing, no teacher/parent role, no admin dashboard.
- Self-service `/account` page:
  - Change password.
  - Delete account (types username to confirm; cascades to decks, cards, sessions).
- No password-reset flow (no email). Manual reset by the operator if needed.

## 2. Content model

### Decks
- Named. Owned by exactly one student.
- Full CRUD: create, rename, delete.
- Deleting a deck deletes its cards and study history.
- No cap on number of decks per student.

### Cards
- Two text sides: **question** and **answer**.
- Text only in v1 (no images, no audio).
- Each card belongs to **exactly one deck**. No move-between-decks in v1.
- Full CRUD, always editable (including mid-session-history).
- No bulk import in v1 (no paste-box, no CSV).
- No cap on number of cards per deck.
- **DB column limit**: 500 chars per side (hygiene — prevents paste-bomb, not a product-visible cap). UI shows a friendly error on overflow.

## 3. Landing page (`/home`)

- Deck list. Each row: deck name, card count, **Study** button, edit link.
- Empty state: prompt to create the first deck.
- Header shows logged-in username + Logout + link to `/account`.

## 4. Study session

### Session config page (after clicking Study on a deck)
- Student picks:
  1. **Number of cards** — default = all in the deck.
  2. **Order** — shuffle (default) or creation order.
- Sensible defaults pre-filled; student can change them.
- If the chosen deck has **0 cards**: no Start button; page prompts "add cards to this deck first" with a link to add-card.

### Study loop
- One card at a time: question shown, text input for the answer.
- **Progress bar** at top ("3 of 12" style).
- **Enter submits** the answer (also a visible Submit button).
- **Enter with an empty input** = skip = counts wrong (blank recorded as the student's answer).
- **On submit, auto-advance immediately to the next card.** No inline feedback between cards — all feedback lives on the results page.
- No timer. No retry-wrong-within-session. No skip button beyond blank-submit.

### Answer checking
- Whitespace tolerant: trim leading/trailing, collapse internal runs to a single space.
- **Case-sensitive.**
- Exactly one accepted answer per card. No fuzzy / regex / alternatives in v1.

## 5. Results page (after final card)

- Score: `n / total`.
- Per-card list, in study order: question, student's answer, correct answer, verdict (right/wrong).
- **Character-level diff** on wrong ones, highlighting the exact positions that differ.
- **Restart** button (starts a new session with the same config).
- **Edit-card link** on each wrong row.

## 6. Persistence

- Every study session and every per-card attempt is saved to the database.
- Fields per attempt (minimum): deck_id, card_id, student's answer, correct/wrong, timestamp.
- Fields per session (minimum): student_id, deck_id, config (n cards, order), started_at, finished_at, score.
- **v1 UI does not surface history** — capture only. Downstream: history tab, improvement/decay charts.

## 7. UI target

- Students aged 12–15. Standard density, generous tap targets.
- Responsive web (works on phone). No native app.
- Same visual language as existing Crazy-Cram (system font, light/dark auto).

## 8. Non-goals for v1 (explicitly out of scope)

- Sharing decks between students.
- Teacher / parent role or oversight dashboard.
- Public deck library.
- Spaced-repetition scheduling.
- Native mobile app.
- Import / export beyond in-app CRUD.
- Password-reset self-service flow.
- Images, audio, video on cards.
- Fuzzy / multi-answer matching.
- History-based session filters ("cards I got wrong last time" etc.).

## 9. Data model sketch

New tables:

```
Deck
  id (pk)
  user_id (fk User)
  name (varchar 120)
  created_at

Card
  id (pk)
  deck_id (fk Deck, cascade delete)
  question (varchar 500)
  answer   (varchar 500)
  created_at
  updated_at

StudySession
  id (pk)
  user_id (fk User)
  deck_id (fk Deck, cascade delete)
  n_cards (int)
  shuffled (bool)
  started_at
  finished_at (nullable)
  score (int, nullable until finished)

StudyAttempt
  id (pk)
  session_id (fk StudySession, cascade delete)
  card_id (fk Card, nullable — card may be deleted later)
  card_snapshot_q (varchar 500)   # capture at attempt time so history survives edits
  card_snapshot_a (varchar 500)
  student_answer (varchar 500)
  is_correct (bool)
  position (int)                  # order within the session
  attempted_at
```

Notes on snapshotting: because cards are editable at any time, storing the Q/A **as seen during the attempt** keeps historical results honest even after the card is later edited or deleted.

## 10. Routes (indicative)

```
/                            existing — redirects to /login or /home
/login, /register, /logout   existing
/home                        deck list (new content)
/account                     change-password, delete-account
/decks/new                   create deck
/decks/<id>/edit             rename
/decks/<id>/delete           delete (POST, confirm)
/decks/<id>/cards            list + add card
/cards/<id>/edit             edit card
/cards/<id>/delete           delete card (POST)
/decks/<id>/study            session config page
/sessions/<id>               active study loop (one card at a time)
/sessions/<id>/submit        POST an attempt, advance
/sessions/<id>/results       results page
```

## 11. Acceptance criteria

- A logged-in student can create a deck, add cards, run a study session, and see character-level diffs of their mistakes on the results page.
- Restart on the results page starts a fresh session with the same config.
- Deleting an account removes every trace: decks, cards, sessions, attempts.
- Editing a card mid-life does not corrupt past results (snapshot preserved).
- A deck with 0 cards cannot be studied; the page tells the student what to do.
- All existing v0 behaviour (invite codes, 30-user cap, session security) still passes its tests.
