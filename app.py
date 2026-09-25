import difflib
import os
import random
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, redirect, url_for, flash, request, abort
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_bcrypt import Bcrypt
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, login_required, current_user
)
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event, func
from sqlalchemy.engine import Engine
from wtforms import (
    StringField, PasswordField, SubmitField, TextAreaField,
    IntegerField, RadioField,
)
from wtforms.validators import DataRequired, Length, Regexp, EqualTo, NumberRange

MAX_USERS = int(os.environ.get("CRAZY_CRAM_MAX_USERS", "30"))
INSTANCE_DIR = Path(__file__).parent / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

app = Flask(__name__, instance_path=str(INSTANCE_DIR))
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

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


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(32), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


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
DECK_NAME_MAX = 120


class Deck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name = db.Column(db.String(DECK_NAME_MAX), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("decks", cascade="all, delete-orphan", passive_deletes=True))
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


class DeckForm(FlaskForm):
    name = StringField(
        "Deck name",
        validators=[DataRequired(), Length(min=1, max=DECK_NAME_MAX)],
        filters=[lambda v: v.strip() if isinstance(v, str) else v],
    )
    submit = SubmitField("Save deck")


def _owned_deck_or_404(deck_id):
    deck = db.session.get(Deck, deck_id)
    if deck is None or deck.user_id != current_user.id:
        abort(404)
    return deck


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
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter(func.lower(User.username) == form.username.data.lower()).first()
        if user and bcrypt.check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            return redirect(url_for("home"))
        flash("Invalid username or password.", "error")
    return render_template("login.html", form=form)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    form = RegisterForm()
    if form.validate_on_submit():
        if db.session.query(func.count(User.id)).scalar() >= MAX_USERS:
            flash(f"Registration closed — user cap ({MAX_USERS}) reached.", "error")
            return render_template("register.html", form=form)

        invite = InviteCode.query.filter_by(code=form.invite_code.data.strip()).first()
        if invite is None or invite.is_used:
            flash("Invalid or already-used invite code.", "error")
            return render_template("register.html", form=form)

        if User.query.filter(func.lower(User.username) == form.username.data.lower()).first():
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
        return redirect(url_for("home"))
    return render_template("register.html", form=form)


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/home")
@login_required
def home():
    rows = (
        db.session.query(Deck, func.count(Card.id))
        .outerjoin(Card, Card.deck_id == Deck.id)
        .filter(Deck.user_id == current_user.id)
        .group_by(Deck.id)
        .order_by(Deck.created_at.asc())
        .all()
    )
    decks = [{"deck": d, "card_count": n} for (d, n) in rows]
    return render_template("home.html", user=current_user, decks=decks)


@app.route("/decks/new", methods=["GET", "POST"])
@login_required
def deck_new():
    form = DeckForm()
    if form.validate_on_submit():
        deck = Deck(user_id=current_user.id, name=form.name.data)
        db.session.add(deck)
        db.session.commit()
        flash(f"Deck “{deck.name}” created.", "info")
        return redirect(url_for("home"))
    return render_template("deck_form.html", form=form, mode="new")


@app.route("/decks/<int:deck_id>/edit", methods=["GET", "POST"])
@login_required
def deck_edit(deck_id):
    deck = _owned_deck_or_404(deck_id)
    form = DeckForm(obj=deck)
    if form.validate_on_submit():
        deck.name = form.name.data
        db.session.commit()
        flash("Deck renamed.", "info")
        return redirect(url_for("home"))
    return render_template("deck_form.html", form=form, mode="edit", deck=deck)


@app.route("/decks/<int:deck_id>/delete", methods=["GET", "POST"])
@login_required
def deck_delete(deck_id):
    deck = _owned_deck_or_404(deck_id)
    if request.method == "POST":
        db.session.delete(deck)
        db.session.commit()
        flash(f"Deck “{deck.name}” deleted.", "info")
        return redirect(url_for("home"))
    return render_template("deck_delete.html", deck=deck)


@app.route("/decks/<int:deck_id>/cards", methods=["GET", "POST"])
@login_required
def deck_cards(deck_id):
    deck = _owned_deck_or_404(deck_id)
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
    return render_template("deck_cards.html", deck=deck, cards=cards, form=form)


@app.route("/cards/<int:card_id>/edit", methods=["GET", "POST"])
@login_required
def card_edit(card_id):
    card = _owned_card_or_404(card_id)
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


class StudyConfigForm(FlaskForm):
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

    if total == 0:
        # No form / no Start button — the template shows a link to add cards.
        return render_template(
            "study_config.html", deck=deck, total=0, form=None,
        )

    form = StudyConfigForm()
    if request.method == "GET":
        form.n_cards.data = total

    if form.validate_on_submit():
        # Clamp requested count silently to what's actually available.
        n = min(max(1, form.n_cards.data), total)
        shuffled = form.order.data == "shuffle"

        chosen = list(cards)
        if shuffled:
            random.shuffle(chosen)
        chosen = chosen[:n]

        s = StudySession(
            user_id=current_user.id,
            deck_id=deck.id,
            n_cards=n,
            shuffled=shuffled,
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
        return redirect(url_for("study_session", session_id=s.id))

    return render_template(
        "study_config.html", deck=deck, total=total, form=form,
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
    if s.finished_at is not None:
        return redirect(url_for("study_results", session_id=s.id))
    attempt = _next_unanswered(s)
    if attempt is None:
        # Shouldn't happen — finalize defensively and redirect to results.
        _finalize_session(s)
        return redirect(url_for("study_results", session_id=s.id))
    return render_template(
        "study_session.html",
        session=s, attempt=attempt,
        position=attempt.position + 1, total=s.n_cards,
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


@app.route("/sessions/<int:session_id>/results")
@login_required
def study_results(session_id):
    s = _owned_session_or_404(session_id)
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
        if not a.is_correct:
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

    s = StudySession(
        user_id=current_user.id,
        deck_id=deck.id,
        n_cards=n,
        shuffled=old.shuffled,
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
    return redirect(url_for("study_session", session_id=s.id))


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
        logout_user()
        db.session.delete(user)
        db.session.commit()
        flash("Your account has been deleted.", "success")
        return redirect(url_for("login"))
    return render_template("account.html", pw_form=pw_form, del_form=del_form)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="127.0.0.1", port=8776)
