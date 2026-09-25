# Crazy-Cram

A small Flask flashcard app for a small number of students. Invite-only, hard user cap, single SQLite file, boring stack.

## What it does

- **Decks**: create, rename, delete a set of flashcards.
- **Cards**: question + answer, ≤ 500 chars each side.
- **Study session**: pick how many cards and shuffle vs creation order; answer one at a time with progress bar; blank = wrong; case-sensitive, whitespace-tolerant equality against the answer.
- **Results**: score, per-card list, character-level diff on wrong answers, restart button, edit-from-results round-trip that preserves the historical attempt snapshot.
- **Account self-service**: change password (forces re-login), delete account (cascades to all owned decks / cards / sessions / attempts; preserves invite-code audit trail via `SET NULL`).
- **Ops**: per-IP rate limits on `/login` and `/register`, structured JSON audit log on auth + session events, `/health` readiness probe.

## Stack

- **Flask 3** + Jinja templates
- **Flask-Login** — session management
- **Flask-WTF** — forms, CSRF
- **Flask-SQLAlchemy** + **Flask-Migrate** (Alembic) — ORM + forward-only migrations
- **Flask-Bcrypt** — password hashing
- **Flask-Limiter** — in-memory per-IP rate limiting
- **gunicorn** — WSGI server behind a reverse proxy
- SQLite — everything, one file

## Run locally

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./bin/crazy-cram-initdb        # runs `flask db upgrade`
./venv/bin/python app.py
# open http://127.0.0.1:8776
```

## Tests

```bash
./venv/bin/pip install pytest
./venv/bin/pytest tests/ -q
```

## Configuration

Environment variables:

| Name | Default | Purpose |
| --- | --- | --- |
| `CRAZY_CRAM_MAX_USERS` | `30` | Hard cap on total registered users |
| `CRAZY_CRAM_DATABASE_URI` | `sqlite:///instance/crazy-cram.db` | SQLAlchemy database URL |
| `CRAZY_CRAM_LIMITER_STORAGE` | `memory://` | Flask-Limiter storage URI; use `redis://…` if you scale past one worker box |
| `CRAZY_CRAM_VERSION` | `VERSION` file contents | Version string reported by `/health` |

The Flask secret key is generated on first run and written to `instance/secret_key` (`0600`). Delete it to force a rotation (invalidates all sessions).

## Invite codes

Only holders of an unused invite code can register. Mint codes with:

```bash
bin/crazy-cram-initdb          # first run or after a schema change
bin/crazy-cram-invite [count]  # default 1
```

Each printed code is single-use. When a user registers, the code is marked used and linked to that user. Deleting the user later preserves the invite row (used_by → NULL, used_at preserved) so the audit trail stays honest.

## Rate limits

Applied per client IP (`get_remote_address` reads `X-Forwarded-For` via `ProxyFix`):

- `POST /login`: 10 per minute
- `POST /register`: 5 per hour

Storage defaults to in-memory (fine at 30 users on a single gunicorn instance). Point `CRAZY_CRAM_LIMITER_STORAGE` at a Redis URI if you ever scale horizontally.

## `/health`

Cheap liveness + readiness probe — no auth, exempt from rate limit. Returns JSON:

```json
{"status":"ok","version":"1.0.0","db":"ok"}
```

`200` when the DB responds to `SELECT 1`; `503` with `{"status":"error","db":"unreachable"}` otherwise.

## Structured event log

One JSON line per event on stderr (captured into the systemd journal). Events:

- `login_success`, `login_fail` (same shape for bad-user and bad-password — no user-enumeration leak)
- `logout`
- `register_success`, `register_fail` (with `reason ∈ {user_cap, bad_invite, dupe_username}`)
- `account_password_change`, `account_delete`
- `study_session_start` (includes `restart_of` on restarts), `study_session_finish`

Every line includes `ts` (ISO-8601 UTC), `event`, `ip`, and event-specific fields. Grep in production with `journalctl -u crazy-cram | grep 'login_fail'`.

## Deployment (systemd user unit)

```ini
[Unit]
Description=Crazy-Cram Flask app (gunicorn)
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/apps/crazy-cram
Environment=PYTHONUNBUFFERED=1
ExecStartPre=%h/apps/crazy-cram/bin/crazy-cram-initdb
ExecStart=%h/apps/crazy-cram/venv/bin/gunicorn \
  --bind 127.0.0.1:8776 \
  --workers 2 \
  --forwarded-allow-ips=127.0.0.1 \
  app:app
Restart=on-failure
KillSignal=SIGTERM
TimeoutStopSec=15

[Install]
WantedBy=default.target
```

Front with any reverse proxy that terminates TLS and forwards `X-Forwarded-*` (Cloudflare Tunnel, nginx, Caddy). The app uses Werkzeug's `ProxyFix` for one hop of proxy headers.

## Security notes

- Passwords: bcrypt hashes only, never stored plaintext. Change-password re-hashes and force-logs-out.
- CSRF: enabled on every POST.
- Session cookies: `HttpOnly`, `Secure`, `SameSite=Lax`.
- Cross-user isolation: every route touching user-owned data returns `404` on foreign IDs (no `403` — no existence leak).
- Passwords must be 8–128 chars. Usernames: `[A-Za-z0-9_.-]{3,32}`, case-insensitive uniqueness.

## Layout

```
app.py                    # ~880 lines: models, forms, routes, logging, rate-limits
VERSION                   # semver string reported by /health
templates/                # base, auth, account, decks, cards, study, results, rate_limited
static/style.css          # ~180 lines
migrations/               # Alembic — forward-only chain (0001 → 0003)
bin/crazy-cram-initdb     # runs `flask db upgrade`
bin/crazy-cram-invite     # mint invite codes
tests/                    # pytest suite (161 tests)
```

## Licence

[MIT](LICENSE)
