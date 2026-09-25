"""M4 unit tests — answer normalizer, matcher, and char-diff builder."""
import pytest


# --- normalize_answer -------------------------------------------------

def test_normalize_none_is_empty(app):
    assert app.normalize_answer(None) == ""


def test_normalize_empty_is_empty(app):
    assert app.normalize_answer("") == ""


def test_normalize_trims(app):
    assert app.normalize_answer("  chat  ") == "chat"


def test_normalize_collapses_runs(app):
    assert app.normalize_answer("a  b   c\t\nd") == "a b c d"


def test_normalize_preserves_case(app):
    assert app.normalize_answer("Chat") == "Chat"
    assert app.normalize_answer("cHaT") == "cHaT"


# --- answers_match ----------------------------------------------------

def test_match_identical(app):
    assert app.answers_match("chat", "chat") is True


def test_match_whitespace_tolerant(app):
    assert app.answers_match("  chat ", "chat") is True
    assert app.answers_match("hello  world", "hello world") is True
    assert app.answers_match("hello\tworld", "hello world") is True


def test_match_case_sensitive(app):
    assert app.answers_match("Chat", "chat") is False
    assert app.answers_match("CHAT", "chat") is False


def test_match_wrong(app):
    assert app.answers_match("chien", "chat") is False


def test_match_blank_is_wrong(app):
    # A card's answer is never empty (schema/UI enforce it).
    assert app.answers_match("", "chat") is False
    assert app.answers_match(None, "chat") is False
    assert app.answers_match("   ", "chat") is False


# --- char_diff_ops ---------------------------------------------------

def test_diff_identical_all_equal(app):
    s, c = app.char_diff_ops("chat", "chat")
    assert all(k == "eq" for k, _ in s)
    assert all(k == "eq" for k, _ in c)
    assert "".join(ch for _, ch in s) == "chat"
    assert "".join(ch for _, ch in c) == "chat"


def test_diff_insertion(app):
    # Student typed "cat", correct is "chat" — needs an 'h' inserted.
    s, c = app.char_diff_ops("cat", "chat")
    assert "".join(ch for _, ch in s) == "cat"
    assert "".join(ch for _, ch in c) == "chat"
    # The 'h' in the correct side must be marked "ins".
    correct_marked = [(k, ch) for k, ch in c]
    assert ("ins", "h") in correct_marked


def test_diff_deletion(app):
    # Student typed "chaat", correct is "chat" — extra 'a'.
    s, c = app.char_diff_ops("chaat", "chat")
    assert ("del", "a") in [(k, ch) for k, ch in s]


def test_diff_replacement(app):
    s, c = app.char_diff_ops("chit", "chat")
    student_marked = [(k, ch) for k, ch in s]
    correct_marked = [(k, ch) for k, ch in c]
    assert ("del", "i") in student_marked
    assert ("ins", "a") in correct_marked


def test_diff_blank_student(app):
    s, c = app.char_diff_ops("", "chat")
    assert s == []
    assert c == [("ins", "c"), ("ins", "h"), ("ins", "a"), ("ins", "t")]
