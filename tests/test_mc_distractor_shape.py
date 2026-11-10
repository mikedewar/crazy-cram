"""MC distractor shape-grouping tests.

The MC option picker prefers distractors whose surface shape matches the
correct answer (trailing `!`, year-length number, pure number vs text) so the
right option can't be guessed by shape. Falls back to random when the deck
doesn't have enough shape-matching siblings.
"""
import random

from app import _mc_pick_distractors, _mc_shape_key


def test_shape_key_distinguishes_numbers_and_text():
    assert _mc_shape_key("500")[0] == "number"
    assert _mc_shape_key("hello")[0] == "text"


def test_shape_key_buckets_digit_lengths():
    assert _mc_shape_key("7")[1] == "1"
    assert _mc_shape_key("42")[1] == "2-3"
    assert _mc_shape_key("500")[1] == "2-3"
    assert _mc_shape_key("1066")[1] == "4"
    assert _mc_shape_key("12345")[1] == "5+"


def test_shape_key_captures_trailing_punctuation():
    assert _mc_shape_key("Watch out!")[2] == "!"
    assert _mc_shape_key("Really?")[2] == "?"
    assert _mc_shape_key("End.")[2] == "."
    assert _mc_shape_key("plain")[2] == ""


def test_shape_key_number_ignores_trailing_whitespace():
    assert _mc_shape_key("  500  ") == _mc_shape_key("500")


def test_distractors_prefer_matching_bang():
    random.seed(0)
    correct = "Watch out!"
    pool = [
        "Look behind you!", "Fire!", "Run!",   # same shape
        "quiet", "calm", "still",              # different shape
    ]
    picked = _mc_pick_distractors(correct, pool, 3)
    assert len(picked) == 3
    assert all(p.endswith("!") for p in picked), picked


def test_distractors_prefer_matching_year_length_numbers():
    random.seed(0)
    correct = "500"
    pool = ["42", "100", "750", "hello", "world", "cat"]
    picked = _mc_pick_distractors(correct, pool, 3)
    assert len(picked) == 3
    assert all(p.isdigit() for p in picked), picked


def test_distractors_fall_back_when_pool_too_small_for_shape():
    """If there aren't enough shape-matches, loosen rather than return <N."""
    random.seed(0)
    correct = "Watch out!"
    pool = ["Fire!", "quiet", "calm", "still"]  # only 1 bang-ending sibling
    picked = _mc_pick_distractors(correct, pool, 3)
    assert len(picked) == 3
    assert "Fire!" in picked  # the one shape-match should still get in


def test_distractors_dedupe_on_identity():
    random.seed(0)
    correct = "500"
    pool = ["42", "100", "750"]
    picked = _mc_pick_distractors(correct, pool, 3)
    assert sorted(picked) == ["100", "42", "750"]


def test_distractors_number_group_prefers_same_digit_bucket():
    """A 4-digit year should pull other 4-digit years before 2-digit ones."""
    random.seed(0)
    correct = "1066"
    pool = ["42", "7", "1215", "1492", "1789", "cat", "dog"]
    picked = _mc_pick_distractors(correct, pool, 3)
    assert len(picked) == 3
    assert all(len(p) == 4 and p.isdigit() for p in picked), picked
