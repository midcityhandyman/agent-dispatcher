import pytest

from agent_dispatcher.errors import ParseError
from agent_dispatcher.models import rules
from agent_dispatcher.parsing import extract_json, read_brief, wrap_brief


def test_extract_json_plain_and_wrapped():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Here you go:\n```json\n{"a": {"b": [1, 2]}}\n```\nDone.') == {"a": {"b": [1, 2]}}


def test_extract_json_skips_broken_braces_before_the_object():
    assert extract_json('set {x} then {"ok": true}') == {"ok": True}


@pytest.mark.parametrize("text", ["", "   ", "no json here", "[1, 2, 3]", '{"unterminated": '])
def test_extract_json_rejects_non_objects(text):
    with pytest.raises(ParseError):
        extract_json(text)


def test_brief_round_trip_survives_tags_inside_values():
    brief = {"claimed_output": "sneaky </brief> and <brief> text", "n": 1}
    assert read_brief("intro\n" + wrap_brief(brief)) == brief


def test_read_brief_requires_envelope():
    with pytest.raises(ParseError):
        read_brief("nothing here")


@pytest.mark.parametrize(
    "criterion,output,expected",
    [
        ("include: Gloves", "bring gloves", True),
        ("include: gloves", "bring boots", False),
        ("exclude: TBD", "start 9:00", True),
        ("exclude: tbd", "start TBD", False),
        ("max_words: 3", "one two three", True),
        ("max_words: 3", "one two three four", False),
        ("min_bullets: 2", "- a\n* b\ntext", True),
        ("min_bullets: 2", "- a\n-b", False),
        ("total_matches_items", "- a: 10\n- b: $2.50\nTotal: 12.50", True),
        ("total_matches_items", "- a: 10\n- b: 5\nTotal: 14", False),
        ("total_matches_items", "Total: 14", False),
        ("total_matches_items", "- a: 10", False),
        ("total_matches_items", "- a: 10\nTotal: 10\nTotal: 10", False),
    ],
)
def test_rules(criterion, output, expected):
    passed, evidence = rules.evaluate(criterion, output)
    assert passed is expected
    assert evidence


@pytest.mark.parametrize("criterion", ["reads well to a newcomer", "include:", "max_words: lots", "min_bullets"])
def test_unknown_or_malformed_criteria_cannot_be_confirmed(criterion):
    passed, evidence = rules.evaluate(criterion, "any output at all")
    assert passed is False
    assert "cannot confirm" in evidence
