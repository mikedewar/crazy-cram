"""Regression: the card form must submit a single ``answer`` field for MC.

Prior to the fix, ``card_form.html`` rendered ``form.answer`` inside both the
``.type-written`` and ``.type-mc`` blocks. The non-chosen block was marked
``hidden``, but ``hidden`` only hides visually — the browser still submitted
every textarea in the form. The POST therefore contained two ``answer`` keys
(one empty from the hidden written block, one with the correct answer from
the visible MC block). WTForms' ``StringField`` takes the first value, so
MC saves rejected the form with "The correct answer is required." even
though the user filled it in.

The existing suite's tests always posted a single ``answer`` key, so the
duplicate-field bug slipped past them. This test drives the real HTML:

1. Render the new-card page as an authenticated user.
2. Parse the rendered form and collect every ``name`` attribute on every
   ``<input>`` and ``<textarea>``.
3. Fill in the submission by name, exactly as a browser would, including
   the CSRF token and any duplicate field names.
4. POST that payload and assert the card is created.

A duplicate ``name="answer"`` in the rendered HTML makes this fail — the
hidden written block would overwrite the MC answer with an empty string.
"""
import re
from html.parser import HTMLParser

from werkzeug.datastructures import MultiDict


def _register(client, invite, username="alice", password="correct-horse-1"):
    code = invite()
    return client.post(
        "/register",
        data={
            "invite_code": code,
            "username": username,
            "password": password,
            "confirm": password,
            "submit": "Create account",
        },
    )


def _mk_deck(app, user_id, name="French"):
    d = app.Deck(user_id=user_id, name=name)
    app.db.session.add(d)
    app.db.session.commit()
    return d


class _FormFieldScanner(HTMLParser):
    """Collect (tag, attrs) for every input/textarea with a name."""

    def __init__(self):
        super().__init__()
        self.fields = []  # list of (tag, {attr: value})

    def handle_starttag(self, tag, attrs):
        if tag not in ("input", "textarea"):
            return
        a = dict(attrs)
        if a.get("name"):
            self.fields.append((tag, a))


def _collect_form_fields(html: str) -> list[tuple[str, dict]]:
    s = _FormFieldScanner()
    s.feed(html)
    return s.fields


def test_mc_create_submits_browser_payload_and_saves(client, invite, app):
    """Reproduce the browser's POST shape from the actual rendered HTML."""
    _register(client, invite, "alice")
    alice = app.User.query.filter_by(username="alice").one()
    d = _mk_deck(app, alice.id)

    get = client.get(f"/decks/{d.id}/cards")
    assert get.status_code == 200, "GET new-card page should be 200"
    html = get.data.decode("utf-8")

    fields = _collect_form_fields(html)
    assert fields, "No form fields parsed out of the rendered page"

    # Values the user would supply for an MC random-mode card.
    chosen = {
        "card_type": "mc",
        "question": "Capital of France?",
        "answer": "Paris",
        "mc_mode": "random",
        "distractor_1": "",
        "distractor_2": "",
        "distractor_3": "",
        "tf_correct": "true",
        "submit": "Save card",
    }

    payload = MultiDict()
    for tag, attrs in fields:
        name = attrs["name"]
        itype = attrs.get("type", "")
        # Hidden inputs (CSRF token etc.) submit their current value.
        if tag == "input" and itype == "hidden":
            payload.add(name, attrs.get("value", ""))
            continue
        # Radios submit only the checked option's value.
        if tag == "input" and itype == "radio":
            chosen_val = chosen.get(name)
            if chosen_val is not None and attrs.get("value") == chosen_val:
                payload.add(name, chosen_val)
            continue
        # Submit button only if we're "clicking" it.
        if tag == "input" and itype == "submit":
            payload.add(name, attrs.get("value", ""))
            continue
        # Everything else (textarea, text input) submits the chosen value if
        # we have one, otherwise the empty string — which is exactly what a
        # browser does for an unfilled textarea.
        payload.add(name, chosen.get(name, ""))

    # Sanity: with a correctly rendered form there is exactly one `answer`
    # field in the submission. If this fails, the template is still
    # rendering `form.answer` more than once.
    answer_count = len(payload.getlist("answer"))
    assert answer_count == 1, (
        f"Expected exactly 1 `answer` field in the browser payload, "
        f"got {answer_count}. The template is rendering form.answer in "
        f"more than one place."
    )

    r = client.post(f"/decks/{d.id}/cards", data=payload, follow_redirects=False)

    assert r.status_code in (301, 302), (
        f"Expected redirect after save, got {r.status_code}. "
        "The MC answer field was likely masked by a duplicate hidden "
        "`name=\"answer\"` elsewhere in the form."
    )
    c = app.Card.query.filter_by(deck_id=d.id).one()
    assert c.card_type == "mc"
    assert c.answer == "Paris"
