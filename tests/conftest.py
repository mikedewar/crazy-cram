import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAZY_CRAM_MAX_USERS", "3")
    monkeypatch.setenv("CRAZY_CRAM_DATABASE_URI", f"sqlite:///{tmp_path / 'test.db'}")

    if "app" in sys.modules:
        del sys.modules["app"]
    import app as app_module

    app_module.app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SESSION_COOKIE_SECURE=False,
    )
    with app_module.app.app_context():
        app_module.db.create_all()
        yield app_module


@pytest.fixture()
def client(app):
    return app.app.test_client()


@pytest.fixture()
def invite(app):
    def _mint():
        import secrets
        code = secrets.token_urlsafe(9)
        app.db.session.add(app.InviteCode(code=code))
        app.db.session.commit()
        return code
    return _mint
