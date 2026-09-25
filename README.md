# Crazy-Cram

Small Flask web app with invite-code self-registration and a hard cap on users. Boring-tech stack, single SQLite file, ~200 lines of application code.

## Stack

- **Flask 3** + Jinja templates
- **Flask-Login** — session management
- **Flask-WTF** — forms, CSRF
- **Flask-SQLAlchemy** — ORM
- **Flask-Bcrypt** — password hashing
- **gunicorn** — WSGI server behind a reverse proxy
- SQLite — user + invite storage

## Run locally

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
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

The Flask secret key is generated on first run and written to `instance/secret_key` (`0600`). Delete it to force a rotation (invalidates all sessions).

## Invite codes

Only holders of an unused invite code can register. Mint codes with:

```bash
bin/crazy-cram-initdb          # first run only
bin/crazy-cram-invite [count]  # default 1
```

Each printed code is single-use. When a user registers, the code is marked used and linked to that user.

## Deployment (systemd user unit)

`bin/crazy-cram-initdb` is safe to re-run (`create_all` is idempotent). Wire it into an `ExecStartPre=` so the schema exists before workers start. Example unit:

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

- Passwords: bcrypt hashes only, never stored plaintext.
- CSRF: enabled on every POST.
- Session cookies: `HttpOnly`, `Secure`, `SameSite=Lax`.
- Referrer check: Flask-WTF's default strict referrer validation is on — needs a proxy that forwards the right host or `ProxyFix` (already wired in).
- Passwords must be 8–128 chars. Usernames: `[A-Za-z0-9_.-]{3,32}`, case-insensitive uniqueness.

## Layout

```
app.py                    # ~150 lines: models, forms, routes
templates/                # base + login + register + home
static/style.css          # ~30 lines
bin/crazy-cram-initdb     # idempotent schema init
bin/crazy-cram-invite     # mint invite codes
tests/                    # pytest suite (22 tests)
```

## Licence

[MIT](LICENSE)
