"""Tolerant JSON extraction for model replies, and the brief envelope used in prompts."""

from __future__ import annotations

import json

from .errors import ParseError

BRIEF_OPEN = "<brief>"
BRIEF_CLOSE = "</brief>"


def extract_json(text: str) -> dict:
    """Return the first JSON object found in `text`.

    Models sometimes wrap JSON in prose or code fences. This scans for the first
    position where a complete object decodes, and refuses anything that is not an object.
    """
    if not isinstance(text, str) or not text.strip():
        raise ParseError("empty reply")
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(value, dict):
            return value
        start = text.find("{", start + 1)
    raise ParseError("no JSON object in reply")


def wrap_brief(brief: dict) -> str:
    """Serialize a brief deterministically inside its envelope."""
    return f"{BRIEF_OPEN}\n{json.dumps(brief, indent=2, sort_keys=True)}\n{BRIEF_CLOSE}"


def read_brief(prompt: str) -> dict:
    """Inverse of wrap_brief. Uses the outermost tags so quoted tags inside values are harmless."""
    start = prompt.find(BRIEF_OPEN)
    end = prompt.rfind(BRIEF_CLOSE)
    if start == -1 or end == -1 or end < start:
        raise ParseError("prompt has no brief envelope")
    try:
        value = json.loads(prompt[start + len(BRIEF_OPEN) : end])
    except json.JSONDecodeError as exc:
        raise ParseError(f"brief is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ParseError("brief is not an object")
    return value
