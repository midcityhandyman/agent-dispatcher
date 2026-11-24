"""A tiny criteria language the mock verifier can actually evaluate.

Real criteria can be any sentence; a Claude verifier judges those by reading.
The mock has no judgment, so offline runs use criteria written in these forms:

    include: <text>          output contains the text (case insensitive)
    exclude: <text>          output does not contain the text
    max_words: <n>           output has at most n words
    min_bullets: <n>         output has at least n lines starting with "- " or "* "
    total_matches_items      "- label: number" lines add up to the "Total: number" line

Anything else is reported as not confirmable, which the dispatcher treats as a refutation.
"""

from __future__ import annotations

import re

_ITEM = re.compile(r"^\s*[-*]\s+.*:\s*\$?(\d+(?:\.\d+)?)\s*$")
_TOTAL = re.compile(r"^\s*total:\s*\$?(\d+(?:\.\d+)?)\s*$", re.IGNORECASE)
_BULLET = re.compile(r"^\s*[-*]\s+\S")


def _fmt(number: float) -> str:
    return str(int(number)) if number == int(number) else f"{number:.2f}"


def split_criterion(criterion: str) -> tuple[str, str]:
    kind, _, arg = criterion.partition(":")
    return kind.strip().lower(), arg.strip()


def evaluate(criterion: str, output: str) -> tuple[bool, str]:
    """Return (passed, evidence) for one criterion against one output."""
    kind, arg = split_criterion(criterion)
    lowered = output.lower()

    if kind == "include" and arg:
        found = arg.lower() in lowered
        return found, f'"{arg}" {"found" if found else "is missing"}'

    if kind == "exclude" and arg:
        found = arg.lower() in lowered
        return (not found), f'"{arg}" {"is present" if found else "not present"}'

    if kind == "max_words" and arg.isdigit():
        count = len(output.split())
        return count <= int(arg), f"{count} words, limit {arg}"

    if kind == "min_bullets" and arg.isdigit():
        count = sum(1 for line in output.splitlines() if _BULLET.match(line))
        return count >= int(arg), f"{count} bullets, need {arg}"

    if kind == "total_matches_items" and not arg:
        items = [float(m.group(1)) for m in map(_ITEM.match, output.splitlines()) if m]
        totals = [float(m.group(1)) for m in map(_TOTAL.match, output.splitlines()) if m]
        if not items:
            return False, "no priced items found"
        if len(totals) != 1:
            return False, f"expected one Total line, found {len(totals)}"
        actual = sum(items)
        ok = abs(actual - totals[0]) < 0.005
        return ok, f"items add up to {_fmt(actual)}, Total line says {_fmt(totals[0])}"

    return False, "no rule for this criterion, cannot confirm"
