import difflib
import json
import logging
import os
import random
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, redirect, url_for, flash, request, abort, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_bcrypt import Bcrypt
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, login_required, current_user
)
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event, func, text
from sqlalchemy.engine import Engine
from wtforms import (
    StringField, PasswordField, SubmitField, TextAreaField,
    IntegerField, RadioField, SelectField, BooleanField, HiddenField,
)
from wtforms.validators import (
    DataRequired, Length, Regexp, EqualTo, NumberRange, ValidationError, Optional,
)

MAX_USERS = int(os.environ.get("CRAZY_CRAM_MAX_USERS", "30"))
INSTANCE_DIR = Path(__file__).parent / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

_VERSION_FILE = Path(__file__).parent / "VERSION"
VERSION = (
    os.environ.get("CRAZY_CRAM_VERSION")
    or (_VERSION_FILE.read_text().strip() if _VERSION_FILE.exists() else "0.0.0")
)

app = Flask(__name__, instance_path=str(INSTANCE_DIR))
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

_STYLE_FILE = Path(__file__).parent / "static" / "style.css"
_ASSET_VERSION = f"{VERSION}-{int(_STYLE_FILE.stat().st_mtime)}" if _STYLE_FILE.exists() else VERSION


@app.context_processor
def _inject_asset_version():
    return {
        "asset_version": _ASSET_VERSION,
        "folder_palette": FOLDER_PALETTE,
        "unfiled_swatch": UNFILED_SWATCH,
    }


@app.context_processor
def _inject_sidebar_folders():
    """Top-3 most recently opened folders for the sidebar.

    'Recently opened' is defined as the max(deck.last_opened_at) of
    decks in that folder. Folders with no opened decks are excluded.
    Unfiled is intentionally omitted. Only runs for authenticated
    requests."""
    if not current_user.is_authenticated:
        return {}
    rows = (
        db.session.query(Folder, func.max(Deck.last_opened_at).label("last_opened"))
        .join(Deck, Deck.folder_id == Folder.id)
        .filter(Folder.user_id == current_user.id)
        .filter(Deck.last_opened_at.isnot(None))
        .group_by(Folder.id)
        .order_by(func.max(Deck.last_opened_at).desc())
        .limit(3)
        .all()
    )
    return {"sidebar_folders": [f for (f, _) in rows]}

_secret_file = INSTANCE_DIR / "secret_key"
if not _secret_file.exists():
    _secret_file.write_bytes(secrets.token_bytes(32))
    _secret_file.chmod(0o600)
app.config["SECRET_KEY"] = _secret_file.read_bytes()

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "CRAZY_CRAM_DATABASE_URI",
    f"sqlite:///{INSTANCE_DIR / 'crazy-cram.db'}",
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

db = SQLAlchemy(app)
migrate = Migrate(app, db, directory=str(Path(__file__).parent / "migrations"))


@event.listens_for(Engine, "connect")
def _sqlite_enable_fk(dbapi_connection, connection_record):
    # SQLite ships with FKs off by default; cascade/on-delete only work with them on.
    import sqlite3
    if isinstance(dbapi_connection, sqlite3.Connection):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
bcrypt = Bcrypt(app)
csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# --- Rate limiting ---------------------------------------------------
# In-memory backend is fine at 30 users on one gunicorn instance — no
# cross-worker sharing needed since traffic is negligible. If we ever
# horizontally scale, swap storage_uri for redis://.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri=os.environ.get("CRAZY_CRAM_LIMITER_STORAGE", "memory://"),
    default_limits=[],
    headers_enabled=True,
)


@app.errorhandler(429)
def _rate_limited(e):
    if request.accept_mimetypes.best == "application/json":
        return jsonify(error="rate_limited", detail=str(e.description)), 429
    return render_template("rate_limited.html", detail=str(e.description)), 429


# --- Structured event logging ---------------------------------------
# One JSON line per event on stderr. Gunicorn/systemd captures it into
# the journal; from there, `journalctl -u crazy-cram` gives grep-able
# audit trail without pulling in a logging framework.
_log_handler = logging.StreamHandler(sys.stderr)
_log_handler.setFormatter(logging.Formatter("%(message)s"))
app.logger.handlers = [_log_handler]
app.logger.setLevel(logging.INFO)
app.logger.propagate = False


def _log_event(name, **fields):
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": name,
        "ip": request.remote_addr if request else None,
        **fields,
    }
    app.logger.info(json.dumps(payload, separators=(",", ":"), default=str))


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    last_login_at = db.Column(db.DateTime, nullable=True)


class InviteCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    used_at = db.Column(db.DateTime, nullable=True)
    used_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    @property
    def is_used(self):
        return self.used_at is not None


CARD_SIDE_MAX = 500

# MC study mode: 1 correct + 3 distractors drawn from other cards in the deck.
MC_OPTIONS_PER_QUESTION = 4
MC_MIN_DECK_SIZE = MC_OPTIONS_PER_QUESTION  # need at least this many cards to run MC
STUDY_MODES = ("written", "mc", "flashcard", "learn")
LEARN_TOTAL_SECTIONS = 5
LEARN_MIN_DECK_SIZE = MC_MIN_DECK_SIZE  # Learn uses MC in 3 of 5 sections
DECK_NAME_MAX = 120
FOLDER_NAME_MAX = 64

DECK_PALETTE = [
    "#ffd6d6",  # peach
    "#ffe8c2",  # apricot
    "#fff4b8",  # butter
    "#dff5c5",  # sage
    "#c8ecd6",  # mint
    "#c8e6f2",  # sky
    "#d6dcf5",  # lavender
    "#e8d1f2",  # lilac
    "#f5cfe1",  # rose
    "#e8dfd0",  # sand
]

FOLDER_PALETTE = [
    "#e63946",  # crimson
    "#f3722c",  # orange
    "#f9c74f",  # amber
    "#43aa8b",  # teal
    "#2a9d8f",  # emerald
    "#277da1",  # ocean
    "#4361ee",  # cobalt
    "#7b2cbf",  # violet
    "#c71585",  # magenta
    "#6a994e",  # moss
]

UNFILED_SWATCH = "#8a8a8a"


def random_deck_color():
    import secrets
    return secrets.choice(DECK_PALETTE)


def random_folder_color(user_id=None):
    import secrets
    if user_id is None:
        return secrets.choice(FOLDER_PALETTE)
    used = {
        c for (c,) in db.session.query(Folder.color)
        .filter(Folder.user_id == user_id, Folder.color.isnot(None))
        .all()
    }
    unused = [c for c in FOLDER_PALETTE if c not in used]
    pool = unused if unused else FOLDER_PALETTE
    return secrets.choice(pool)


class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name = db.Column(db.String(FOLDER_NAME_MAX), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    color = db.Column(db.String(9), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "name", name="uq_folder_user_id_name"),
    )

    user = db.relationship("User", backref=db.backref("folders", cascade="all, delete-orphan", passive_deletes=True))


class Deck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name = db.Column(db.String(DECK_NAME_MAX), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    folder_id = db.Column(
        db.Integer, db.ForeignKey("folder.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    last_opened_at = db.Column(db.DateTime, nullable=True, index=True)
    color = db.Column(db.String(9), nullable=True)
    # NULL = personal; UTC timestamp = published to the Universal folder.
    # See migration 0011_deck_publish.
    published_at = db.Column(db.DateTime, nullable=True, index=True)
    # Points at the original deck for copies made via /universal/<id>/add.
    # ON DELETE SET NULL at the DB level, so deleting the original leaves
    # downstream copies intact (per the published-deck sharing contract).
    source_deck_id = db.Column(
        db.Integer, db.ForeignKey("deck.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    user = db.relationship("User", backref=db.backref("decks", cascade="all, delete-orphan", passive_deletes=True))
    folder = db.relationship("Folder", backref=db.backref("decks", passive_deletes=True))
    source = db.relationship(
        "Deck", remote_side=[id], foreign_keys=[source_deck_id],
    )
    cards = db.relationship(
        "Card",
        backref="deck",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sessions = db.relationship(
        "StudySession",
        backref="deck",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    deck_id = db.Column(
        db.Integer, db.ForeignKey("deck.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    question = db.Column(db.String(CARD_SIDE_MAX), nullable=False)
    answer = db.Column(db.String(CARD_SIDE_MAX), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class StudySession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    deck_id = db.Column(
        db.Integer, db.ForeignKey("deck.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    n_cards = db.Column(db.Integer, nullable=False)
    shuffled = db.Column(db.Boolean, nullable=False, default=True)
    mode = db.Column(db.String(16), nullable=False, default="written")
    # Which section the Learn run is currently on (1..5). NULL for non-Learn.
    learn_section = db.Column(db.Integer, nullable=True)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = db.Column(db.DateTime, nullable=True)
    score = db.Column(db.Integer, nullable=True)

    user = db.relationship("User", backref=db.backref("study_sessions", cascade="all, delete-orphan", passive_deletes=True))
    attempts = db.relationship(
        "StudyAttempt",
        backref="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StudyAttempt.position",
    )


class StudyAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("study_session.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # nullable — a card may be deleted after the attempt was recorded;
    # snapshot columns keep the historical record honest.
    card_id = db.Column(
        db.Integer, db.ForeignKey("card.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    card_snapshot_q = db.Column(db.String(CARD_SIDE_MAX), nullable=False)
    card_snapshot_a = db.Column(db.String(CARD_SIDE_MAX), nullable=False)
    student_answer = db.Column(db.String(CARD_SIDE_MAX), nullable=True)
    is_correct = db.Column(db.Boolean, nullable=True)
    position = db.Column(db.Integer, nullable=False)
    attempted_at = db.Column(db.DateTime, nullable=True)
    # NULL for non-Learn modes; 1..LEARN_TOTAL_SECTIONS for Learn.
    section = db.Column(db.Integer, nullable=True)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


USERNAME_RE = r"^[A-Za-z0-9_.-]{3,32}$"


class RegisterForm(FlaskForm):
    invite_code = StringField(
        "Invite code",
        validators=[DataRequired(), Length(min=4, max=64)],
    )
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(min=3, max=32),
            Regexp(USERNAME_RE, message="Letters, digits, . _ - only (3-32 chars)."),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=8, max=128)],
    )
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(max=32)])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])
    submit = SubmitField("Log in")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(
        "Current password",
        validators=[DataRequired(), Length(max=128)],
    )
    new_password = PasswordField(
        "New password",
        validators=[DataRequired(), Length(min=8, max=128)],
    )
    confirm = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("new_password", message="Passwords must match.")],
    )
    submit = SubmitField("Change password")


class DeleteAccountForm(FlaskForm):
    confirm_username = StringField(
        "Type your username to confirm",
        validators=[DataRequired(), Length(max=32)],
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(max=128)],
    )
    submit = SubmitField("Delete my account")


def _folder_choices():
    """SelectField choices for the current user's folders, alpha, with a
    leading Unfiled option ('' → NULL). Callers must be inside a request
    with current_user available."""
    choices = [("", "— Unfiled —")]
    for f in Folder.query.filter_by(user_id=current_user.id).order_by(Folder.name.asc()):
        choices.append((str(f.id), f.name))
    return choices


def _resolve_folder_id(raw):
    """Turn a SelectField value ('' or '<id>') into a validated folder_id
    for current_user, or None. 404 on any id the user doesn't own."""
    if raw in (None, ""):
        return None
    try:
        fid = int(raw)
    except (TypeError, ValueError):
        abort(400)
    _owned_folder_or_404(fid)
    return fid


class DeckForm(FlaskForm):
    name = StringField(
        "Deck name",
        validators=[DataRequired(), Length(min=1, max=DECK_NAME_MAX)],
        filters=[lambda v: v.strip() if isinstance(v, str) else v],
    )
    folder_id = SelectField("Folder", choices=[], validate_choice=False, default="")
    color = StringField("Colour", default="")
    submit = SubmitField("Save deck")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.folder_id.choices = _folder_choices()


class DeckMoveForm(FlaskForm):
    folder_id = SelectField("Move to folder", choices=[], validate_choice=False, default="")
    submit = SubmitField("Move")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.folder_id.choices = _folder_choices()


class FolderForm(FlaskForm):
    name = StringField(
        "Folder name",
        validators=[DataRequired(), Length(min=1, max=FOLDER_NAME_MAX)],
        filters=[lambda v: v.strip() if isinstance(v, str) else v],
    )
    submit = SubmitField("Save folder")

    def __init__(self, *args, folder_id=None, **kwargs):
        """folder_id — the id of the folder being renamed, so the
        per-user uniqueness check below can exclude it from the clash
        check (a no-op rename mustn't collide with itself)."""
        super().__init__(*args, **kwargs)
        self._folder_id = folder_id

    def validate_name(self, field):
        existing = Folder.query.filter_by(
            user_id=current_user.id, name=field.data,
        ).first()
        if existing is not None and existing.id != self._folder_id:
            raise ValidationError("You already have a folder with that name.")


class FolderDeleteForm(FlaskForm):
    id = HiddenField()
    also_delete_decks = BooleanField("Also delete the decks inside", default=False)
    submit = SubmitField("Delete folder")


def _owned_deck_or_404(deck_id):
    deck = db.session.get(Deck, deck_id)
    if deck is None or deck.user_id != current_user.id:
        abort(404)
    return deck


def _owned_folder_or_404(folder_id):
    folder = db.session.get(Folder, folder_id)
    if folder is None or folder.user_id != current_user.id:
        abort(404)
    return folder


def _delete_deck(deck):
    """Delete a deck. Cascades to its cards/sessions/attempts via the
    ORM relationship cascades on Deck — the single source of truth for
    deck-delete semantics, shared by the single-deck route and the
    folder 'also delete decks' path so they can't drift apart."""
    db.session.delete(deck)


def _abort_if_published(deck):
    """403 when a deck is published and read-only edits are attempted.

    Published decks are frozen at the moment of the flip: cards, name,
    colour, folder are all immutable until the owner un-publishes. The
    Personal/Universal slider and the delete flow stay available.
    """
    if deck.published_at is not None:
        abort(403)


def _owned_card_or_404(card_id):
    card = db.session.get(Card, card_id)
    if card is None or card.deck.user_id != current_user.id:
        abort(404)
    return card


class CardForm(FlaskForm):
    question = TextAreaField(
        "Question",
        validators=[DataRequired(), Length(min=1, max=CARD_SIDE_MAX)],
        filters=[lambda v: v.strip() if isinstance(v, str) else v],
    )
    answer = TextAreaField(
        "Answer",
        validators=[DataRequired(), Length(min=1, max=CARD_SIDE_MAX)],
        filters=[lambda v: v.strip() if isinstance(v, str) else v],
    )
    submit = SubmitField("Save card")


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter(func.lower(User.username) == form.username.data.lower()).first()
        if user and bcrypt.check_password_hash(user.password_hash, form.password.data):
            user.last_login_at = datetime.now(timezone.utc)
            db.session.commit()
            login_user(user)
            _log_event("login_success", user_id=user.id, username=user.username)
            return redirect(url_for("home"))
        # Same log shape for bad-user and bad-password: don't leak which.
        _log_event("login_fail", username=form.username.data)
        flash("Invalid username or password.", "error")
    return render_template("login.html", form=form)


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    form = RegisterForm()
    if form.validate_on_submit():
        if db.session.query(func.count(User.id)).scalar() >= MAX_USERS:
            _log_event("register_fail", reason="user_cap")
            flash(f"Registration closed — user cap ({MAX_USERS}) reached.", "error")
            return render_template("register.html", form=form)

        invite = InviteCode.query.filter_by(code=form.invite_code.data.strip()).first()
        if invite is None or invite.is_used:
            _log_event("register_fail", reason="bad_invite")
            flash("Invalid or already-used invite code.", "error")
            return render_template("register.html", form=form)

        if User.query.filter(func.lower(User.username) == form.username.data.lower()).first():
            _log_event("register_fail", reason="dupe_username", username=form.username.data)
            flash("That username is taken.", "error")
            return render_template("register.html", form=form)

        pw_hash = bcrypt.generate_password_hash(form.password.data).decode("utf-8")
        user = User(username=form.username.data, password_hash=pw_hash)
        db.session.add(user)
        db.session.flush()
        invite.used_at = datetime.now(timezone.utc)
        invite.used_by = user.id
        db.session.commit()
        login_user(user)
        _log_event("register_success", user_id=user.id, username=user.username)
        return redirect(url_for("home"))
    return render_template("register.html", form=form)


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    _log_event("logout", user_id=current_user.id, username=current_user.username)
    logout_user()
    return redirect(url_for("login"))


@app.route("/home")
@login_required
def home():
    folder_rows = (
        db.session.query(Folder, func.count(Deck.id))
        .outerjoin(Deck, Deck.folder_id == Folder.id)
        .filter(Folder.user_id == current_user.id)
        .group_by(Folder.id)
        .order_by(Folder.name.asc())
        .all()
    )
    folders = [{"folder": f, "deck_count": n} for (f, n) in folder_rows]
    unfiled_count = Deck.query.filter_by(user_id=current_user.id, folder_id=None).count()
    total_decks = Deck.query.filter_by(user_id=current_user.id).count()
    universal_count = Deck.query.filter(Deck.published_at.isnot(None)).count()

    return render_template(
        "home.html",
        user=current_user,
        folders=folders,
        unfiled_count=unfiled_count,
        universal_count=universal_count,
        total_decks=total_decks,
    )


@app.route("/decks/new", methods=["GET", "POST"])
@login_required
def deck_new():
    form = DeckForm()
    if request.method == "GET":
        # ?folder=<id> pre-selects the dropdown when arriving from a folder view.
        pre = request.args.get("folder", "")
        if pre and any(pre == v for v, _ in form.folder_id.choices):
            form.folder_id.data = pre
    if form.validate_on_submit():
        folder_id = _resolve_folder_id(form.folder_id.data)
        color = form.color.data if form.color.data in DECK_PALETTE else random_deck_color()
        deck = Deck(
            user_id=current_user.id, name=form.name.data,
            folder_id=folder_id, color=color,
        )
        # Slider on /new: publish=1 means create-and-publish atomically.
        if request.form.get("publish") == "1":
            deck.published_at = datetime.now(timezone.utc)
        db.session.add(deck)
        db.session.commit()
        flash(f"Deck “{deck.name}” created.", "info")
        return redirect(url_for("deck_cards", deck_id=deck.id))
    return render_template("deck_form.html", form=form, mode="new", palette=DECK_PALETTE, published=False)


@app.route("/decks/<int:deck_id>/edit", methods=["GET", "POST"])
@login_required
def deck_edit(deck_id):
    deck = _owned_deck_or_404(deck_id)
    # Published decks are frozen; the form is still rendered read-only.
    if request.method == "POST":
        _abort_if_published(deck)
    form = DeckForm(obj=deck)
    if request.method == "GET":
        form.folder_id.data = "" if deck.folder_id is None else str(deck.folder_id)
    if form.validate_on_submit():
        deck.name = form.name.data
        deck.folder_id = _resolve_folder_id(form.folder_id.data)
        if form.color.data in DECK_PALETTE:
            deck.color = form.color.data
        db.session.commit()
        flash("Deck saved.", "info")
        return redirect(url_for("home"))
    return render_template(
        "deck_form.html", form=form, mode="edit", deck=deck,
        palette=DECK_PALETTE, published=deck.published_at is not None,
    )


@app.route("/decks/<int:deck_id>/move", methods=["POST"])
@login_required
def deck_move(deck_id):
    deck = _owned_deck_or_404(deck_id)
    _abort_if_published(deck)
    form = DeckMoveForm()
    if form.validate_on_submit():
        deck.folder_id = _resolve_folder_id(form.folder_id.data)
        db.session.commit()
        flash("Deck moved.", "info")
    return redirect(request.referrer or url_for("home"))


@app.route("/decks/<int:deck_id>/delete", methods=["GET", "POST"])
@login_required
def deck_delete(deck_id):
    # Delete stays available even when a deck is published — unpublishing
    # survives on downstream copies via source_deck_id ON DELETE SET NULL.
    deck = _owned_deck_or_404(deck_id)
    if request.method == "POST":
        name = deck.name
        _delete_deck(deck)
        db.session.commit()
        flash(f"Deck “{name}” deleted.", "info")
        return redirect(url_for("home"))
    return render_template("deck_delete.html", deck=deck)


@app.route("/decks/<int:deck_id>/publish", methods=["POST"])
@login_required
def deck_publish(deck_id):
    """Flip a personal deck to Universal. Owner-only, idempotent."""
    deck = _owned_deck_or_404(deck_id)
    if deck.published_at is None:
        deck.published_at = datetime.now(timezone.utc)
        db.session.commit()
        flash(f"“{deck.name}” published to Universal.", "info")
    return redirect(request.referrer or url_for("deck_edit", deck_id=deck_id))


@app.route("/decks/<int:deck_id>/unpublish", methods=["POST"])
@login_required
def deck_unpublish(deck_id):
    """Remove a deck from Universal. Owner or admin.

    Existing copies survive — source_deck_id stays pointing at this deck
    (or SETs NULL if the original is later deleted). Idempotent.
    """
    deck = db.session.get(Deck, deck_id)
    if deck is None:
        abort(404)
    if deck.user_id != current_user.id and not current_user.is_admin:
        # 404 (not 403) when a non-owner non-admin probes an id they don't own.
        abort(404)
    if deck.published_at is not None:
        deck.published_at = None
        db.session.commit()
        flash(f"“{deck.name}” removed from Universal.", "info")
    return redirect(request.referrer or url_for("home"))


# --- Universal (published decks shared across all users) --------------

# AliMonkeyBrains's group is pinned to the top of /universal, then the
# rest of the publishers in most-recent-publish order.
_UNIVERSAL_PINNED_USERNAME = "AliMonkeyBrains"


@app.route("/universal")
@login_required
def universal_index():
    """Published decks, grouped by creator.

    Group order: AliMonkeyBrains first (if present), then other creators
    ordered by their most-recent publish time (newest group first).
    Within each group: decks by published_at desc (youngest first).
    """
    rows = (
        db.session.query(Deck, func.count(Card.id))
        .outerjoin(Card, Card.deck_id == Deck.id)
        .filter(Deck.published_at.isnot(None))
        .group_by(Deck.id)
        .order_by(Deck.published_at.desc(), Deck.id.desc())
        .all()
    )
    published = [d for (d, _n) in rows]
    card_counts = {d.id: n for (d, n) in rows}

    # Group by publisher.
    groups_by_user = {}
    for deck in published:
        groups_by_user.setdefault(deck.user_id, []).append(deck)

    # Order the groups.
    user_ids = list(groups_by_user.keys())
    users = {u.id: u for u in User.query.filter(User.id.in_(user_ids)).all()}
    # Latest publish time per group (first entry's published_at — already
    # sorted desc).
    def _latest(uid):
        return groups_by_user[uid][0].published_at

    pinned_uid = None
    for uid, u in users.items():
        if u.username == _UNIVERSAL_PINNED_USERNAME:
            pinned_uid = uid
            break
    sorted_uids = sorted(
        [uid for uid in user_ids if uid != pinned_uid],
        key=_latest, reverse=True,
    )
    if pinned_uid is not None:
        sorted_uids.insert(0, pinned_uid)

    groups = [
        {
            "user": users[uid],
            "decks": groups_by_user[uid],
        }
        for uid in sorted_uids
    ]
    user_folders = (
        Folder.query.filter_by(user_id=current_user.id)
        .order_by(Folder.name.asc())
        .all()
    )
    return render_template(
        "universal.html",
        groups=groups,
        card_counts=card_counts,
        current_user_id=current_user.id,
        user_folders=user_folders,
    )


@app.route("/universal/<int:deck_id>/add", methods=["POST"])
@login_required
def universal_add(deck_id):
    """Snapshot-copy a published deck into Unfiled; redirect to /edit.

    - Only works on currently-published decks.
    - Users may add the same source more than once; each add creates
      a fresh independent copy.
    """
    source = db.session.get(Deck, deck_id)
    if source is None or source.published_at is None:
        abort(404)
    # Destination folder: blank/missing form field → Unfiled.
    raw_folder_id = (request.form.get("folder_id") or "").strip()
    dest_folder_id = None
    if raw_folder_id:
        try:
            fid = int(raw_folder_id)
        except ValueError:
            abort(400)
        folder = db.session.get(Folder, fid)
        if folder is None or folder.user_id != current_user.id:
            abort(404)  # cross-user → 404, per isolation rule
        dest_folder_id = folder.id
    copy = Deck(
        user_id=current_user.id,
        name=source.name,
        folder_id=dest_folder_id,
        color=source.color,
        source_deck_id=source.id,
    )
    db.session.add(copy)
    db.session.flush()  # populate copy.id
    source_cards = (
        Card.query.filter_by(deck_id=source.id)
        .order_by(Card.created_at.asc(), Card.id.asc())
        .all()
    )
    for c in source_cards:
        db.session.add(Card(
            deck_id=copy.id, question=c.question, answer=c.answer,
        ))
    db.session.commit()
    flash(f"Copied “{source.name}” into your decks.", "info")
    return redirect(url_for("deck_edit", deck_id=copy.id))


# --- Folders ------------------------------------------------------------

@app.route("/folders/new", methods=["GET", "POST"])
@login_required
def folder_new():
    form = FolderForm()
    if form.validate_on_submit():
        folder = Folder(user_id=current_user.id, name=form.name.data, color=random_folder_color(current_user.id))
        db.session.add(folder)
        db.session.commit()
        flash(f"Folder “{folder.name}” created.", "info")
        return redirect(url_for("home"))
    return render_template("folders/new.html", form=form)


@app.route("/folders", methods=["GET", "POST"])
@login_required
def folder_list():
    form = FolderForm()
    if form.validate_on_submit():
        folder = Folder(user_id=current_user.id, name=form.name.data, color=random_folder_color(current_user.id))
        db.session.add(folder)
        db.session.commit()
        flash(f"Folder “{folder.name}” created.", "info")
        return redirect(url_for("folder_list"))

    rows = (
        db.session.query(Folder, func.count(Deck.id))
        .outerjoin(Deck, Deck.folder_id == Folder.id)
        .filter(Folder.user_id == current_user.id)
        .group_by(Folder.id)
        .order_by(Folder.name.asc())
        .all()
    )
    folders = [{"folder": f, "deck_count": n} for (f, n) in rows]
    unfiled_count = Deck.query.filter_by(user_id=current_user.id, folder_id=None).count()
    rename_forms = {f["folder"].id: FolderForm(obj=f["folder"], folder_id=f["folder"].id) for f in folders}
    return render_template(
        "folders/list.html", form=form, folders=folders,
        unfiled_count=unfiled_count, rename_forms=rename_forms,
    )


@app.route("/folders/unfiled")
@login_required
def folder_unfiled():
    rows = (
        db.session.query(Deck, func.count(Card.id))
        .outerjoin(Card, Card.deck_id == Deck.id)
        .filter(Deck.user_id == current_user.id, Deck.folder_id.is_(None))
        .group_by(Deck.id)
        .order_by(Deck.created_at.asc())
        .all()
    )
    decks = [{"deck": d, "card_count": n} for (d, n) in rows]
    return render_template("folders/detail.html", folder=None, decks=decks)


@app.route("/folders/<int:folder_id>")
@login_required
def folder_detail(folder_id):
    folder = _owned_folder_or_404(folder_id)
    rows = (
        db.session.query(Deck, func.count(Card.id))
        .outerjoin(Card, Card.deck_id == Deck.id)
        .filter(Deck.folder_id == folder.id)
        .group_by(Deck.id)
        .order_by(Deck.created_at.asc())
        .all()
    )
    decks = [{"deck": d, "card_count": n} for (d, n) in rows]
    return render_template("folders/detail.html", folder=folder, decks=decks)


@app.route("/folders/<int:folder_id>/rename", methods=["POST"])
@login_required
def folder_rename(folder_id):
    folder = _owned_folder_or_404(folder_id)
    form = FolderForm(folder_id=folder.id)
    if form.validate_on_submit():
        folder.name = form.name.data
        db.session.commit()
        flash("Folder renamed.", "info")
    else:
        for e in form.name.errors:
            flash(e, "error")
    return redirect(url_for("folder_list"))


@app.route("/folders/<int:folder_id>/color", methods=["POST"])
@login_required
def folder_set_color(folder_id):
    folder = _owned_folder_or_404(folder_id)
    chosen = (request.form.get("color") or "").strip()
    if chosen not in FOLDER_PALETTE:
        abort(400)
    folder.color = chosen
    db.session.commit()
    next_url = request.form.get("next")
    if next_url == "home":
        return redirect(url_for("home"))
    return redirect(url_for("folder_list"))


@app.route("/folders/<int:folder_id>/delete", methods=["GET", "POST"])
@login_required
def folder_delete(folder_id):
    folder = _owned_folder_or_404(folder_id)
    deck_count = Deck.query.filter_by(folder_id=folder.id).count()
    form = FolderDeleteForm(id=folder.id)
    if request.method == "POST":
        form = FolderDeleteForm()
        if form.validate_on_submit():
            name = folder.name
            if form.also_delete_decks.data:
                decks = Deck.query.filter_by(folder_id=folder.id).all()
                for d in decks:
                    _delete_deck(d)
            # Unchecked: leave decks in place — the FK's ON DELETE SET NULL
            # nulls their folder_id automatically when the folder row goes.
            db.session.delete(folder)
            db.session.commit()
            flash(f"Folder “{name}” deleted.", "info")
            return redirect(url_for("folder_list"))
    return render_template(
        "folders/delete.html", folder=folder, deck_count=deck_count, form=form,
    )


@app.route("/decks/<int:deck_id>/cards", methods=["GET", "POST"])
@login_required
def deck_cards(deck_id):
    deck = _owned_deck_or_404(deck_id)
    # Adding cards to a published deck is blocked; GET renders read-only.
    if request.method == "POST":
        _abort_if_published(deck)
    form = CardForm()
    if form.validate_on_submit():
        card = Card(deck_id=deck.id, question=form.question.data, answer=form.answer.data)
        db.session.add(card)
        db.session.commit()
        flash("Card added.", "info")
        return redirect(url_for("deck_cards", deck_id=deck.id))
    cards = (
        Card.query.filter_by(deck_id=deck.id)
        .order_by(Card.created_at.asc(), Card.id.asc())
        .all()
    )
    # Bump last_opened_at on GET only — POST is card-creation, not a
    # deck-viewing event. Isolated UPDATE via db.session.execute so the
    # ORM doesn't touch Deck.updated_at (that column belongs to Card).
    if request.method == "GET":
        db.session.execute(
            db.update(Deck)
            .where(Deck.id == deck.id)
            .values(last_opened_at=datetime.now(timezone.utc))
        )
        db.session.commit()
    return render_template("deck_cards.html", deck=deck, cards=cards, form=form)


@app.route("/cards/<int:card_id>/edit", methods=["GET", "POST"])
@login_required
def card_edit(card_id):
    card = _owned_card_or_404(card_id)
    if request.method == "POST":
        _abort_if_published(card.deck)
    form = CardForm(obj=card)

    # Optional round-trip: if the caller passed ?return_to=<session_id> and
    # that session belongs to the current user, save-and-return to its results
    # page instead of the deck's card list.
    return_to = request.values.get("return_to", type=int)
    return_session = None
    if return_to is not None:
        s = db.session.get(StudySession, return_to)
        if s is not None and s.user_id == current_user.id:
            return_session = s

    if form.validate_on_submit():
        card.question = form.question.data
        card.answer = form.answer.data
        db.session.commit()
        flash("Card updated.", "info")
        if return_session is not None:
            return redirect(url_for("study_results", session_id=return_session.id))
        return redirect(url_for("deck_cards", deck_id=card.deck_id))
    return render_template(
        "card_form.html", form=form, card=card,
        return_session=return_session,
    )


@app.route("/cards/<int:card_id>/delete", methods=["POST"])
@login_required
def card_delete(card_id):
    card = _owned_card_or_404(card_id)
    _abort_if_published(card.deck)
    deck_id = card.deck_id
    db.session.delete(card)
    db.session.commit()
    flash("Card deleted.", "info")
    return redirect(url_for("deck_cards", deck_id=deck_id))


# --- Study session ----------------------------------------------------

_WS_RUN = re.compile(r"\s+")


def normalize_answer(text):
    """Trim + collapse internal whitespace runs to a single space.

    Case is preserved (comparison is case-sensitive per REQUIREMENTS §4).
    None → "" so a blank submit compares against the normalized correct
    answer and (unless the answer really is empty, which it can't be)
    always loses.
    """
    if text is None:
        return ""
    return _WS_RUN.sub(" ", text).strip()


def answers_match(student_answer, correct_answer):
    return normalize_answer(student_answer) == normalize_answer(correct_answer)


def char_diff_ops(student_answer, correct_answer):
    """Return per-side lists of (kind, char) tuples for HTML rendering.

    kind is "eq", "ins" (present in correct only), or "del" (present in
    student only). Comparison is on the raw text, not the normalized
    text — the student sees exactly what they typed.
    """
    a = student_answer or ""
    b = correct_answer or ""
    student_side = []
    correct_side = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for ch in a[i1:i2]:
                student_side.append(("eq", ch))
            for ch in b[j1:j2]:
                correct_side.append(("eq", ch))
        elif tag == "replace":
            for ch in a[i1:i2]:
                student_side.append(("del", ch))
            for ch in b[j1:j2]:
                correct_side.append(("ins", ch))
        elif tag == "delete":
            for ch in a[i1:i2]:
                student_side.append(("del", ch))
        elif tag == "insert":
            for ch in b[j1:j2]:
                correct_side.append(("ins", ch))
    return student_side, correct_side


def mc_options_for(attempt):
    """Pick MC options for an attempt: correct answer + 3 distractors.

    Distractors are drawn from *other* cards in the same deck, by looking at
    the current cards (not snapshots) via the attempt's session.deck_id.
    Dedupes on normalized text so two cards with the same answer don't both
    appear. If fewer than 3 unique distractors exist the deck has shrunk
    since start — fall back to whatever we have, options list < 4.

    Returns a shuffled list of plain strings.
    """
    correct = attempt.card_snapshot_a
    correct_norm = normalize_answer(correct)
    sibling_answers = (
        db.session.query(Card.answer)
        .filter(Card.deck_id == attempt.session.deck_id)
        .filter(Card.id != attempt.card_id)
        .all()
    )
    seen = {correct_norm}
    pool = []
    for (ans,) in sibling_answers:
        norm = normalize_answer(ans)
        if norm in seen:
            continue
        seen.add(norm)
        pool.append(ans)
    distractors = random.sample(pool, min(MC_OPTIONS_PER_QUESTION - 1, len(pool)))
    options = [correct, *distractors]
    random.shuffle(options)
    return options


class StudyConfigForm(FlaskForm):
    mode = RadioField(
        "Study mode",
        choices=[("written", "Written"), ("mc", "Multiple choice"), ("flashcard", "Flashcards"), ("learn", "Learn")],
        default="written",
        validators=[DataRequired()],
    )
    n_cards = IntegerField(
        "How many cards?",
        validators=[DataRequired(), NumberRange(min=1)],
    )
    order = RadioField(
        "Order",
        choices=[("shuffle", "Shuffle"), ("created", "Creation order")],
        default="shuffle",
        validators=[DataRequired()],
    )
    submit = SubmitField("Start")


def _owned_session_or_404(session_id):
    s = db.session.get(StudySession, session_id)
    if s is None or s.user_id != current_user.id:
        abort(404)
    return s


@app.route("/decks/<int:deck_id>/study", methods=["GET", "POST"])
@login_required
def study_config(deck_id):
    deck = _owned_deck_or_404(deck_id)
    cards = (
        Card.query.filter_by(deck_id=deck.id)
        .order_by(Card.created_at.asc(), Card.id.asc())
        .all()
    )
    total = len(cards)
    mc_available = total >= MC_MIN_DECK_SIZE
    learn_available = total >= LEARN_MIN_DECK_SIZE

    if total == 0:
        # No form / no Start button — the template shows a link to add cards.
        return render_template(
            "study_config.html", deck=deck, total=0, form=None,
            mc_available=False, learn_available=False,
            mc_min_deck_size=MC_MIN_DECK_SIZE,
            learn_min_deck_size=LEARN_MIN_DECK_SIZE,
        )

    form = StudyConfigForm()
    if request.method == "GET":
        form.n_cards.data = total

    if form.validate_on_submit():
        mode = form.mode.data if form.mode.data in STUDY_MODES else "written"
        # Reject MC/Learn if deck has shrunk below the minimum between form
        # render and submit (or if someone POSTs them directly on a tiny deck).
        if mode == "mc" and not mc_available:
            flash(
                f"Multiple choice needs at least {MC_MIN_DECK_SIZE} cards in the deck.",
                "error",
            )
            return redirect(url_for("study_config", deck_id=deck.id))
        if mode == "learn" and not learn_available:
            flash(
                f"Learn mode needs at least {LEARN_MIN_DECK_SIZE} cards in the deck.",
                "error",
            )
            return redirect(url_for("study_config", deck_id=deck.id))

        shuffled = form.order.data == "shuffle"

        if mode == "learn":
            # Learn always uses the whole deck in section 1; n_cards on the
            # session row is the running total across all 5 sections and gets
            # patched up as sections are composed. Start with section 1's size.
            chosen = list(cards)
            if shuffled:
                random.shuffle(chosen)
            s = StudySession(
                user_id=current_user.id,
                deck_id=deck.id,
                n_cards=len(chosen),
                shuffled=shuffled,
                mode="learn",
                learn_section=1,
            )
            db.session.add(s)
            db.session.flush()
            for i, c in enumerate(chosen):
                db.session.add(StudyAttempt(
                    session_id=s.id,
                    card_id=c.id,
                    card_snapshot_q=c.question,
                    card_snapshot_a=c.answer,
                    position=i,
                    section=1,
                ))
            db.session.commit()
            _log_event(
                "study_session_start",
                user_id=current_user.id, session_id=s.id,
                deck_id=deck.id, n_cards=len(chosen), shuffled=shuffled, mode="learn",
            )
            return redirect(url_for("learn_section", session_id=s.id))

        # Clamp requested count silently to what's actually available.
        n = min(max(1, form.n_cards.data), total)

        chosen = list(cards)
        if shuffled:
            random.shuffle(chosen)
        chosen = chosen[:n]

        s = StudySession(
            user_id=current_user.id,
            deck_id=deck.id,
            n_cards=n,
            shuffled=shuffled,
            mode=mode,
        )
        db.session.add(s)
        db.session.flush()
        for i, c in enumerate(chosen):
            db.session.add(StudyAttempt(
                session_id=s.id,
                card_id=c.id,
                card_snapshot_q=c.question,
                card_snapshot_a=c.answer,
                position=i,
            ))
        db.session.commit()
        _log_event(
            "study_session_start",
            user_id=current_user.id, session_id=s.id,
            deck_id=deck.id, n_cards=n, shuffled=shuffled, mode=mode,
        )
        return redirect(url_for("study_session", session_id=s.id))

    return render_template(
        "study_config.html", deck=deck, total=total, form=form,
        mc_available=mc_available, learn_available=learn_available,
        mc_min_deck_size=MC_MIN_DECK_SIZE,
        learn_min_deck_size=LEARN_MIN_DECK_SIZE,
    )


def _next_unanswered(session):
    return (
        StudyAttempt.query
        .filter_by(session_id=session.id, is_correct=None)
        .order_by(StudyAttempt.position.asc())
        .first()
    )


@app.route("/sessions/<int:session_id>")
@login_required
def study_session(session_id):
    s = _owned_session_or_404(session_id)
    if s.mode == "learn":
        if s.finished_at is not None:
            return redirect(url_for("learn_results", session_id=s.id))
        return redirect(url_for("learn_section", session_id=s.id))
    if s.finished_at is not None:
        return redirect(url_for("study_results", session_id=s.id))
    attempt = _next_unanswered(s)
    if attempt is None:
        # Shouldn't happen — finalize defensively and redirect to results.
        _finalize_session(s)
        return redirect(url_for("study_results", session_id=s.id))
    if s.mode == "flashcard":
        return render_template(
            "study_flashcard.html",
            session=s, attempt=attempt,
            position=attempt.position + 1, total=s.n_cards,
        )
    options = mc_options_for(attempt) if s.mode == "mc" else None
    return render_template(
        "study_session.html",
        session=s, attempt=attempt,
        position=attempt.position + 1, total=s.n_cards,
        options=options,
    )


@app.route("/sessions/<int:session_id>/submit", methods=["POST"])
@login_required
def study_submit(session_id):
    s = _owned_session_or_404(session_id)
    if s.finished_at is not None:
        return redirect(url_for("study_results", session_id=s.id))

    attempt_id = request.form.get("attempt_id", type=int)
    if attempt_id is None:
        abort(400)
    attempt = db.session.get(StudyAttempt, attempt_id)
    if attempt is None or attempt.session_id != s.id:
        abort(404)
    if attempt.is_correct is not None:
        # Double-submit — ignore silently, go to whatever's next.
        return redirect(url_for("study_session", session_id=s.id))

    if s.mode == "flashcard":
        verdict = request.form.get("self_grade")
        if verdict not in ("right", "wrong"):
            abort(400)
        attempt.student_answer = None
        attempt.is_correct = (verdict == "right")
    else:
        raw = request.form.get("answer", "") or ""
        # Trim to schema cap so a paste-bomb can't blow up the insert.
        if len(raw) > CARD_SIDE_MAX:
            raw = raw[:CARD_SIDE_MAX]
        attempt.student_answer = raw
        attempt.is_correct = answers_match(raw, attempt.card_snapshot_a)
    attempt.attempted_at = datetime.now(timezone.utc)
    db.session.commit()

    if _next_unanswered(s) is None:
        _finalize_session(s)
        return redirect(url_for("study_results", session_id=s.id))
    return redirect(url_for("study_session", session_id=s.id))


def _finalize_session(s):
    if s.finished_at is not None:
        return
    score = (
        db.session.query(func.count(StudyAttempt.id))
        .filter(StudyAttempt.session_id == s.id, StudyAttempt.is_correct.is_(True))
        .scalar()
    )
    s.score = int(score or 0)
    s.finished_at = datetime.now(timezone.utc)
    db.session.commit()
    _log_event(
        "study_session_finish",
        user_id=s.user_id, session_id=s.id, deck_id=s.deck_id,
        score=s.score, n_cards=s.n_cards,
    )


@app.route("/sessions/<int:session_id>/results")
@login_required
def study_results(session_id):
    s = _owned_session_or_404(session_id)
    if s.mode == "learn":
        return redirect(url_for("learn_results", session_id=s.id))
    if s.finished_at is None:
        # Not finished yet — send them back to the loop.
        return redirect(url_for("study_session", session_id=s.id))

    attempts = (
        StudyAttempt.query.filter_by(session_id=s.id)
        .order_by(StudyAttempt.position.asc())
        .all()
    )
    rows = []
    for a in attempts:
        student_side, correct_side = ([], [])
        # Only produce a char-diff for written mode — MC picks are whole-string
        # choices, there's nothing to diff char-by-char.
        if not a.is_correct and s.mode == "written":
            student_side, correct_side = char_diff_ops(
                a.student_answer or "", a.card_snapshot_a
            )
        rows.append({
            "attempt": a,
            "student_side": student_side,
            "correct_side": correct_side,
        })
    return render_template(
        "study_results.html",
        session=s, deck=s.deck, rows=rows, total=s.n_cards,
    )


@app.route("/sessions/<int:session_id>/restart", methods=["POST"])
@login_required
def study_restart(session_id):
    """Start a fresh session against the same deck with the same config.

    Uses the deck's *current* cards, not the old snapshot — that's the whole
    point of restart: the student may have edited a card between sessions.
    """
    old = _owned_session_or_404(session_id)
    deck = _owned_deck_or_404(old.deck_id)

    cards = (
        Card.query.filter_by(deck_id=deck.id)
        .order_by(Card.created_at.asc(), Card.id.asc())
        .all()
    )
    if not cards:
        flash("This deck has no cards to study.", "error")
        return redirect(url_for("deck_cards", deck_id=deck.id))

    n = min(old.n_cards, len(cards))
    chosen = list(cards)
    if old.shuffled:
        random.shuffle(chosen)
    chosen = chosen[:n]

    # Carry over mode. If the deck shrank below MC's floor, fall back to written
    # rather than exploding — the student still gets a session.
    new_mode = old.mode
    if new_mode == "mc" and len(cards) < MC_MIN_DECK_SIZE:
        new_mode = "written"
        flash(
            f"Multiple choice needs at least {MC_MIN_DECK_SIZE} cards — restarted in written mode.",
            "info",
        )
    if new_mode == "learn" and len(cards) < LEARN_MIN_DECK_SIZE:
        new_mode = "written"
        flash(
            f"Learn mode needs at least {LEARN_MIN_DECK_SIZE} cards — restarted in written mode.",
            "info",
        )

    # Learn restart: forward to study_config with mode preselected rather
    # than reusing this entry point, so the state machine seeds section 1
    # cleanly. (Carrying n_cards/shuffle through a Learn restart isn't
    # meaningful — Learn always uses the whole deck in §1.)
    if new_mode == "learn":
        # Re-seed a fresh Learn session: whole deck in §1.
        chosen = list(cards)
        if old.shuffled:
            random.shuffle(chosen)
        s = StudySession(
            user_id=current_user.id,
            deck_id=deck.id,
            n_cards=len(chosen),
            shuffled=old.shuffled,
            mode="learn",
            learn_section=1,
        )
        db.session.add(s)
        db.session.flush()
        for i, c in enumerate(chosen):
            db.session.add(StudyAttempt(
                session_id=s.id,
                card_id=c.id,
                card_snapshot_q=c.question,
                card_snapshot_a=c.answer,
                position=i,
                section=1,
            ))
        db.session.commit()
        _log_event(
            "study_session_start",
            user_id=current_user.id, session_id=s.id,
            deck_id=deck.id, n_cards=len(chosen), shuffled=old.shuffled,
            mode="learn", restart_of=old.id,
        )
        return redirect(url_for("learn_section", session_id=s.id))

    s = StudySession(
        user_id=current_user.id,
        deck_id=deck.id,
        n_cards=n,
        shuffled=old.shuffled,
        mode=new_mode,
    )
    db.session.add(s)
    db.session.flush()
    for i, c in enumerate(chosen):
        db.session.add(StudyAttempt(
            session_id=s.id,
            card_id=c.id,
            card_snapshot_q=c.question,
            card_snapshot_a=c.answer,
            position=i,
        ))
    db.session.commit()
    _log_event(
        "study_session_start",
        user_id=current_user.id, session_id=s.id,
        deck_id=deck.id, n_cards=n, shuffled=old.shuffled,
        mode=new_mode, restart_of=old.id,
    )
    return redirect(url_for("study_session", session_id=s.id))


# --- Learn mode -------------------------------------------------------
# Five-section guided study run. Section composition depends on prior
# results, so we build each section when the previous one ends.
#   §1 MC — every card in the deck
#   §2 MC — cards wrong in §1
#   §3 Written — cards right in §1 AND §2 (right in whichever they were in)
#   §4 MC — cards wrong in §2 AND §3
#   §5 Written — every card in the deck
# Empty sections still get an interstitial ("nothing to review") so the
# six-page promise stays visible, then the next one is composed.


def _owned_learn_session_or_404(session_id):
    s = _owned_session_or_404(session_id)
    if s.mode != "learn":
        abort(404)
    return s


def _learn_attempts(session, section):
    return (
        StudyAttempt.query
        .filter_by(session_id=session.id, section=section)
        .order_by(StudyAttempt.position.asc())
        .all()
    )


def _learn_section_complete(session, section):
    """True if the section's attempts (if any) are all answered.
    An empty section is trivially complete (nothing to answer).
    """
    attempts = _learn_attempts(session, section)
    if not attempts:
        return True
    return all(a.is_correct is not None for a in attempts)


def _learn_current_section(session):
    """The section the student is currently playing (1..5)."""
    return int(session.learn_section or 1)


def _learn_section_mode(section):
    # §3 and §5 are written; §1, §2, §4 are MC.
    return "written" if section in (3, 5) else "mc"


def _learn_attempts_for_cards(session, cards_in_order, section):
    """Create StudyAttempt rows for `cards_in_order` in `section`.

    Positions continue from the current max position so attempts across
    sections are totally ordered — section 1 fills 0..k-1, section 2
    fills k..k+m-1, etc. That keeps `_next_unanswered`-style ordering
    sensible even though Learn has its own routes.
    """
    base = (
        db.session.query(func.coalesce(func.max(StudyAttempt.position), -1))
        .filter(StudyAttempt.session_id == session.id)
        .scalar()
    )
    base = int(base) + 1
    cards_in_order = list(cards_in_order)
    if session.shuffled:
        random.shuffle(cards_in_order)
    for i, c in enumerate(cards_in_order):
        db.session.add(StudyAttempt(
            session_id=session.id,
            card_id=c.id,
            card_snapshot_q=c.question,
            card_snapshot_a=c.answer,
            position=base + i,
            section=section,
        ))


def _learn_card_ids_right_in(session, sections):
    """Card IDs the student got right in ANY of `sections`.

    Uses card_id (not snapshot) so cards deleted mid-run drop out
    naturally — nothing to study for a card that no longer exists.
    """
    rows = (
        db.session.query(StudyAttempt.card_id)
        .filter(StudyAttempt.session_id == session.id)
        .filter(StudyAttempt.section.in_(sections))
        .filter(StudyAttempt.is_correct.is_(True))
        .filter(StudyAttempt.card_id.isnot(None))
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


def _learn_card_ids_wrong_in(session, sections):
    rows = (
        db.session.query(StudyAttempt.card_id)
        .filter(StudyAttempt.session_id == session.id)
        .filter(StudyAttempt.section.in_(sections))
        .filter(StudyAttempt.is_correct.is_(False))
        .filter(StudyAttempt.card_id.isnot(None))
        .distinct()
        .all()
    )
    return [r[0] for r in rows]


def _learn_cards_by_ids(deck_id, card_ids):
    """Fetch current Card rows matching ids, ordered by created_at."""
    if not card_ids:
        return []
    return (
        Card.query
        .filter(Card.deck_id == deck_id)
        .filter(Card.id.in_(card_ids))
        .order_by(Card.created_at.asc(), Card.id.asc())
        .all()
    )


def _learn_compose_section(session, section):
    """Build attempts for `section` based on prior-section results.

    Does nothing if the section already has attempts (idempotent on
    double-POST of advance).
    """
    if _learn_attempts(session, section):
        return
    deck_id = session.deck_id
    if section == 2:
        ids = _learn_card_ids_wrong_in(session, [1])
    elif section == 3:
        ids = sorted(set(_learn_card_ids_right_in(session, [1, 2])))
    elif section == 4:
        ids = sorted(set(_learn_card_ids_wrong_in(session, [2, 3])))
    elif section == 5:
        ids = [c.id for c in Card.query.filter_by(deck_id=deck_id)
               .order_by(Card.created_at.asc(), Card.id.asc()).all()]
    else:
        return
    cards = _learn_cards_by_ids(deck_id, ids) if section != 5 else (
        Card.query.filter_by(deck_id=deck_id)
        .order_by(Card.created_at.asc(), Card.id.asc()).all()
    )
    _learn_attempts_for_cards(session, cards, section)
    # Keep n_cards in sync so results-page totals stay honest.
    total = (
        db.session.query(func.count(StudyAttempt.id))
        .filter(StudyAttempt.session_id == session.id)
        .scalar()
    )
    session.n_cards = int(total or 0)


def _learn_next_unanswered(session, section):
    return (
        StudyAttempt.query
        .filter_by(session_id=session.id, section=section, is_correct=None)
        .order_by(StudyAttempt.position.asc())
        .first()
    )


@app.route("/sessions/<int:session_id>/learn")
@login_required
def learn_section(session_id):
    s = _owned_learn_session_or_404(session_id)
    if s.finished_at is not None:
        return redirect(url_for("learn_results", session_id=s.id))
    section = _learn_current_section(s)
    # If the current section is complete, send to interstitial (or results
    # if §5). The advance route is what seeds the next one.
    if _learn_section_complete(s, section):
        if section >= LEARN_TOTAL_SECTIONS:
            _finalize_session(s)
            return redirect(url_for("learn_results", session_id=s.id))
        return redirect(url_for("learn_interstitial",
                                session_id=s.id, section=section))
    attempt = _learn_next_unanswered(s, section)
    if attempt is None:
        # Shouldn't happen (complete check above), but defend defensively.
        return redirect(url_for("learn_interstitial",
                                session_id=s.id, section=section))
    section_total = len(_learn_attempts(s, section))
    position_in_section = sum(
        1 for a in _learn_attempts(s, section) if a.position < attempt.position
    ) + 1
    mode = _learn_section_mode(section)
    options = mc_options_for(attempt) if mode == "mc" else None
    return render_template(
        "learn_session.html",
        session=s, attempt=attempt, options=options,
        section=section, section_mode=mode,
        total_sections=LEARN_TOTAL_SECTIONS,
        position=position_in_section, section_total=section_total,
    )


@app.route("/sessions/<int:session_id>/learn/submit", methods=["POST"])
@login_required
def learn_submit(session_id):
    s = _owned_learn_session_or_404(session_id)
    if s.finished_at is not None:
        return redirect(url_for("learn_results", session_id=s.id))

    attempt_id = request.form.get("attempt_id", type=int)
    if attempt_id is None:
        abort(400)
    attempt = db.session.get(StudyAttempt, attempt_id)
    if attempt is None or attempt.session_id != s.id or attempt.section is None:
        abort(404)
    if attempt.is_correct is not None:
        return redirect(url_for("learn_section", session_id=s.id))

    raw = request.form.get("answer", "") or ""
    if len(raw) > CARD_SIDE_MAX:
        raw = raw[:CARD_SIDE_MAX]
    attempt.student_answer = raw
    attempt.is_correct = answers_match(raw, attempt.card_snapshot_a)
    attempt.attempted_at = datetime.now(timezone.utc)
    db.session.commit()
    return redirect(url_for("learn_section", session_id=s.id))


@app.route("/sessions/<int:session_id>/learn/interstitial/<int:section>")
@login_required
def learn_interstitial(session_id, section):
    s = _owned_learn_session_or_404(session_id)
    if s.finished_at is not None:
        return redirect(url_for("learn_results", session_id=s.id))
    if not (1 <= section < LEARN_TOTAL_SECTIONS):
        abort(404)
    # Only valid once the named section has been fully answered.
    if not _learn_section_complete(s, section):
        return redirect(url_for("learn_section", session_id=s.id))

    attempts = _learn_attempts(s, section)
    right = [a for a in attempts if a.is_correct]
    wrong = [a for a in attempts if a.is_correct is False]
    section_total = len(attempts)
    score = len(right)
    return render_template(
        "learn_interstitial.html",
        session=s, deck=s.deck,
        section=section, next_section=section + 1,
        total_sections=LEARN_TOTAL_SECTIONS,
        attempts=attempts, right=right, wrong=wrong,
        score=score, section_total=section_total,
        section_mode=_learn_section_mode(section),
        next_section_mode=_learn_section_mode(section + 1),
    )


@app.route("/sessions/<int:session_id>/learn/advance", methods=["POST"])
@login_required
def learn_advance(session_id):
    s = _owned_learn_session_or_404(session_id)
    if s.finished_at is not None:
        return redirect(url_for("learn_results", session_id=s.id))
    from_section = request.form.get("from_section", type=int)
    if from_section is None or not (1 <= from_section < LEARN_TOTAL_SECTIONS):
        abort(400)
    # Only advance if from_section is actually complete, defensively.
    if not _learn_section_complete(s, from_section):
        return redirect(url_for("learn_section", session_id=s.id))
    next_section = from_section + 1
    _learn_compose_section(s, next_section)
    s.learn_section = next_section
    db.session.commit()
    # If §5 came out empty (deck was emptied mid-run), finalize now so
    # the student lands on results instead of a stuck section screen.
    if next_section >= LEARN_TOTAL_SECTIONS and not _learn_attempts(s, next_section):
        _finalize_session(s)
        return redirect(url_for("learn_results", session_id=s.id))
    return redirect(url_for("learn_section", session_id=s.id))


@app.route("/sessions/<int:session_id>/learn/results")
@login_required
def learn_results(session_id):
    s = _owned_learn_session_or_404(session_id)
    if s.finished_at is None:
        return redirect(url_for("learn_section", session_id=s.id))

    # §5 attempts for score + current-run marking.
    section5 = _learn_attempts(s, 5)
    s5_right = sum(1 for a in section5 if a.is_correct)
    s5_total = len(section5)

    # Aggregate across all sections: per-card right/wrong counts.
    all_attempts = (
        StudyAttempt.query
        .filter(StudyAttempt.session_id == s.id)
        .filter(StudyAttempt.section.isnot(None))
        .all()
    )
    # Key by snapshot question so a deleted card still groups correctly.
    counts = {}
    for a in all_attempts:
        key = (a.card_id, a.card_snapshot_q)
        c = counts.setdefault(key, {
            "card_id": a.card_id,
            "question": a.card_snapshot_q,
            "answer": a.card_snapshot_a,
            "right": 0,
            "wrong": 0,
        })
        if a.is_correct:
            c["right"] += 1
        elif a.is_correct is False:
            c["wrong"] += 1

    # Build the §5 marking rows (in order).
    s5_rows = []
    for a in section5:
        key = (a.card_id, a.card_snapshot_q)
        agg = counts.get(key, {"right": 0, "wrong": 0})
        student_side, correct_side = ([], [])
        if a.is_correct is False:
            student_side, correct_side = char_diff_ops(
                a.student_answer or "", a.card_snapshot_a
            )
        s5_rows.append({
            "attempt": a,
            "right_total": agg["right"],
            "wrong_total": agg["wrong"],
            "student_side": student_side,
            "correct_side": correct_side,
        })

    # Most-missed = highest total wrong count across all 5 sections.
    # Ties broken by lower right count, then by question text.
    most_missed = sorted(
        [c for c in counts.values() if c["wrong"] > 0],
        key=lambda c: (-c["wrong"], c["right"], c["question"]),
    )

    return render_template(
        "learn_results.html",
        session=s, deck=s.deck,
        s5_rows=s5_rows, s5_right=s5_right, s5_total=s5_total,
        most_missed=most_missed,
        total_sections=LEARN_TOTAL_SECTIONS,
    )


# --- Health check -----------------------------------------------------

@app.route("/health")
@limiter.exempt
def health():
    """Liveness + readiness probe: returns 200 iff the DB is reachable."""
    try:
        db.session.execute(text("SELECT 1")).scalar()
    except Exception as e:  # pragma: no cover — verified via mocked engine failure
        return jsonify(status="error", version=VERSION, db="unreachable", detail=str(e)), 503
    return jsonify(status="ok", version=VERSION, db="ok"), 200


# --- Stats -----------------------------------------------------------
# Per-user small-multiples: one table per folder, one row per deck,
# one column per completed study session, oldest -> newest. Each cell
# is a tiny donut: correct in a bright shade of the deck colour,
# incorrect+skipped in a dulled shade. Partial (unfinished) sessions
# are ignored. Admins see only their own stats, same as any user.

# Donut colours — intentionally the same hues used on the end-of-session
# results page (.result-row.right / .result-row.wrong border-left-color
# in style.css), so "right = green, wrong = red" is one consistent
# visual language across the app.
STATS_RIGHT_COLOR = "#4a9d5f"
STATS_WRONG_COLOR = "#c3413a"


def _session_right_wrong(s):
    """Count correct vs incorrect for a finished session.

    - Non-learn modes: every attempt in the session. is_correct=False or
      is_correct=None (skipped) both count as wrong.
    - Learn mode: the final run-through only (section == LEARN_TOTAL_SECTIONS).
    """
    q = StudyAttempt.query.filter(StudyAttempt.session_id == s.id)
    if s.mode == "learn":
        q = q.filter(StudyAttempt.section == LEARN_TOTAL_SECTIONS)
    attempts = q.all()
    right = sum(1 for a in attempts if a.is_correct is True)
    wrong = sum(1 for a in attempts if a.is_correct is not True)
    return right, wrong


@app.route("/stats")
@login_required
def stats():
    # All of this user's folders, in alphabetical order. Unfiled gets
    # its own pseudo-group at the end.
    folders = (
        Folder.query.filter_by(user_id=current_user.id)
        .order_by(func.lower(Folder.name).asc(), Folder.id.asc())
        .all()
    )
    # All of this user's finished sessions, oldest -> newest.
    sessions = (
        StudySession.query
        .filter(StudySession.user_id == current_user.id)
        .filter(StudySession.finished_at.isnot(None))
        .order_by(StudySession.finished_at.asc(), StudySession.id.asc())
        .all()
    )
    sessions_by_deck = {}
    for s in sessions:
        sessions_by_deck.setdefault(s.deck_id, []).append(s)

    def _deck_row(deck):
        cells = []
        for s in sessions_by_deck.get(deck.id, []):
            right, wrong = _session_right_wrong(s)
            cells.append({
                "right": right,
                "wrong": wrong,
                "total": right + wrong,
                "finished_at": s.finished_at,
                "mode": s.mode,
            })
        return {
            "deck": deck,
            "right_color": STATS_RIGHT_COLOR,
            "wrong_color": STATS_WRONG_COLOR,
            "cells": cells,
        }

    def _folder_group(folder, decks):
        rows = [_deck_row(d) for d in decks if sessions_by_deck.get(d.id)]
        max_cols = max((len(r["cells"]) for r in rows), default=0)
        return {
            "folder": folder,
            "rows": rows,
            "max_cols": max_cols,
        }

    groups = []
    for f in folders:
        decks = (
            Deck.query.filter_by(user_id=current_user.id, folder_id=f.id)
            .order_by(func.lower(Deck.name).asc(), Deck.id.asc())
            .all()
        )
        g = _folder_group(f, decks)
        if g["rows"]:
            groups.append(g)

    unfiled_decks = (
        Deck.query.filter_by(user_id=current_user.id, folder_id=None)
        .order_by(func.lower(Deck.name).asc(), Deck.id.asc())
        .all()
    )
    unfiled_group = _folder_group(None, unfiled_decks)
    if unfiled_group["rows"]:
        groups.append(unfiled_group)

    return render_template("stats.html", groups=groups)


# --- Admin -----------------------------------------------------------
# Gated by User.is_admin. Bootstrap admin is set in migration 0009.

def _require_admin():
    if not current_user.is_authenticated or not current_user.is_admin:
        abort(404)


@app.route("/admin")
@login_required
def admin():
    _require_admin()

    users = User.query.order_by(User.created_at.asc()).all()
    invite_by_user = {
        iv.used_by: iv.code
        for iv in InviteCode.query.filter(InviteCode.used_by.isnot(None)).all()
    }
    folder_counts = dict(
        db.session.query(Folder.user_id, func.count(Folder.id))
        .group_by(Folder.user_id).all()
    )
    deck_counts = dict(
        db.session.query(Deck.user_id, func.count(Deck.id))
        .group_by(Deck.user_id).all()
    )
    user_rows = [
        {
            "username": u.username,
            "invite_code": invite_by_user.get(u.id),
            "last_login_at": u.last_login_at,
            "folders": folder_counts.get(u.id, 0),
            "decks": deck_counts.get(u.id, 0),
        }
        for u in users
    ]
    return render_template("admin.html", user_rows=user_rows)


@app.route("/admin/overview")
@login_required
def admin_overview():
    _require_admin()

    users = User.query.order_by(User.created_at.asc()).all()

    deck_counts = dict(
        db.session.query(Deck.user_id, func.count(Deck.id)).group_by(Deck.user_id).all()
    )
    card_counts = dict(
        db.session.query(Deck.user_id, func.count(Card.id))
        .join(Card, Card.deck_id == Deck.id)
        .group_by(Deck.user_id)
        .all()
    )
    session_counts = dict(
        db.session.query(StudySession.user_id, func.count(StudySession.id))
        .group_by(StudySession.user_id)
        .all()
    )
    last_session_at = dict(
        db.session.query(StudySession.user_id, func.max(StudySession.started_at))
        .group_by(StudySession.user_id)
        .all()
    )

    user_rows = [
        {
            "id": u.id,
            "username": u.username,
            "created_at": u.created_at,
            "decks": deck_counts.get(u.id, 0),
            "cards": card_counts.get(u.id, 0),
            "sessions": session_counts.get(u.id, 0),
            "last_session_at": last_session_at.get(u.id),
        }
        for u in users
    ]

    invites = InviteCode.query.order_by(InviteCode.created_at.asc()).all()
    username_by_id = {u.id: u.username for u in users}
    invite_rows = [
        {
            "code": iv.code,
            "created_at": iv.created_at,
            "used_at": iv.used_at,
            "used_by": username_by_id.get(iv.used_by) if iv.used_by else None,
        }
        for iv in invites
    ]

    stats = {
        "users_total": len(users),
        "users_cap": MAX_USERS,
        "invites_total": len(invites),
        "invites_used": sum(1 for iv in invites if iv.used_at),
        "invites_free": sum(1 for iv in invites if not iv.used_at),
    }

    return render_template(
        "admin_overview.html",
        user_rows=user_rows,
        invite_rows=invite_rows,
        stats=stats,
    )


# --- Account self-service --------------------------------------------

@app.route("/account", methods=["GET"])
@login_required
def account():
    return render_template(
        "account.html",
        pw_form=ChangePasswordForm(),
        del_form=DeleteAccountForm(),
    )


@app.route("/account/password", methods=["POST"])
@login_required
def account_change_password():
    pw_form = ChangePasswordForm()
    del_form = DeleteAccountForm()
    if pw_form.validate_on_submit():
        if not bcrypt.check_password_hash(
            current_user.password_hash, pw_form.current_password.data
        ):
            flash("Current password is incorrect.", "error")
            return render_template("account.html", pw_form=pw_form, del_form=del_form)
        current_user.password_hash = bcrypt.generate_password_hash(
            pw_form.new_password.data
        ).decode("utf-8")
        db.session.commit()
        _log_event("account_password_change", user_id=current_user.id, username=current_user.username)
        logout_user()
        flash("Password changed — please log in again.", "success")
        return redirect(url_for("login"))
    return render_template("account.html", pw_form=pw_form, del_form=del_form)


@app.route("/account/delete", methods=["POST"])
@login_required
def account_delete():
    pw_form = ChangePasswordForm()
    del_form = DeleteAccountForm()
    if del_form.validate_on_submit():
        typed = del_form.confirm_username.data.strip()
        if typed.lower() != current_user.username.lower():
            flash("Typed username doesn't match — account not deleted.", "error")
            return render_template("account.html", pw_form=pw_form, del_form=del_form)
        if not bcrypt.check_password_hash(
            current_user.password_hash, del_form.password.data
        ):
            flash("Password is incorrect — account not deleted.", "error")
            return render_template("account.html", pw_form=pw_form, del_form=del_form)

        user = db.session.get(User, current_user.id)
        deleted_id, deleted_name = user.id, user.username
        logout_user()
        db.session.delete(user)
        db.session.commit()
        _log_event("account_delete", user_id=deleted_id, username=deleted_name)
        flash("Your account has been deleted.", "success")
        return redirect(url_for("login"))
    return render_template("account.html", pw_form=pw_form, del_form=del_form)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="127.0.0.1", port=8776)
