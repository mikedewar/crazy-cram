import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, render_template, redirect, url_for, flash, request
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_bcrypt import Bcrypt
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, login_required, current_user
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import func
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, Regexp, EqualTo

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
    return render_template("home.html", user=current_user)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="127.0.0.1", port=8776)
