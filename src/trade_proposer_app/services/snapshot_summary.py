from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from trade_proposer_app.domain.models import SentimentSnapshot


@dataclass(frozen=True)
class SnapshotSummaryContext:
    scope: str
    subject_label: str
    score: float
    label: str
    drivers: list[str]
    coverage_insights: list[str]
    previous_snapshot: SentimentSnapshot | None = None


def build_snapshot_summary(context: SnapshotSummaryContext) -> str:
    subject_label = context.subject_label.strip() or context.scope.title()
    label = context.label.strip().upper() or "NEUTRAL"
    intro = f"{subject_label} remains {label.lower()} overall."
    focus = _pick_focus(context.drivers, context.coverage_insights)
    previous_snapshot = context.previous_snapshot
    if previous_snapshot is None:
        if focus:
            return f"{intro} Current focus is {focus}."
        return f"{intro} No material new developments were captured in this run."

    previous_focus = _pick_focus(
        _coerce_text_list(_parse_json_field(previous_snapshot.drivers_json, [])),
        _coerce_text_list(_parse_json_field(previous_snapshot.diagnostics_json, {}).get("warnings", [])),
    )
    previous_summary = _clean_text(previous_snapshot.summary_text or "")
    score_delta = context.score - float(previous_snapshot.score or 0.0)
    movement = _describe_movement(score_delta)
    if focus and previous_summary and _overlaps(focus, previous_summary):
        return (
            f"{intro} Compared with the prior snapshot, the backdrop is {movement}; "
            f"the main focus remains {focus}."
        )
    if focus and previous_focus and _overlaps(focus, previous_focus):
        return (
            f"{intro} Compared with the prior snapshot, the backdrop is {movement}; "
            f"the main focus remains {focus}."
        )
    if focus:
        return f"{intro} Compared with the prior snapshot, the backdrop is {movement}; the main update is {focus}."
    if previous_summary:
        prior_sentence = _first_sentence(previous_summary).rstrip(".")
        return (
            f"{intro} Compared with the prior snapshot, the backdrop is {movement}; "
            f"the earlier summary centered on {prior_sentence}."
        )
    if previous_focus:
        return f"{intro} Compared with the prior snapshot, the backdrop is {movement}; the previous focus around {previous_focus} still appears to hold."
    return f"{intro} Compared with the prior snapshot, the backdrop is {movement}, with no material new developments captured here."


def _pick_focus(drivers: Sequence[str], coverage_insights: Sequence[str]) -> str:
    for candidate in list(drivers) + list(coverage_insights):
        cleaned = _clean_text(candidate)
        if cleaned:
            return cleaned
    return ""


def _first_sentence(text: str) -> str:
    sentence = text.split(".", 1)[0].strip()
    return sentence or text


def _describe_movement(delta: float) -> str:
    if abs(delta) < 0.05:
        return "broadly unchanged"
    if delta > 0:
        return "slightly firmer"
    return "slightly softer"


def _overlaps(left: str, right: str) -> bool:
    left_tokens = {token for token in _tokenize(left) if len(token) > 2}
    right_tokens = {token for token in _tokenize(right) if len(token) > 2}
    return bool(left_tokens & right_tokens)


def _clean_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = " ".join(value.replace("\n", " ").split()).strip().rstrip(".;:")
    return cleaned


def _coerce_text_list(values: Any) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return []
    return [text for text in (_clean_text(value) for value in values) if text]


def _parse_json_field(value: str | None, default: Any) -> Any:
    if not value:
        return default
    import json

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _tokenize(text: str) -> list[str]:
    return [token for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if token]
