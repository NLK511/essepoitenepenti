from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

OFFICIAL_SOURCE_HINTS = (
    "federal reserve",
    "fomc",
    "u.s. treasury",
    "treasury",
    "bureau of labor statistics",
    "bls",
    "bea",
    "ecb",
    "european central bank",
    "bank of england",
    "boj",
    "bank of japan",
    "opec",
    "imf",
    "world bank",
    "european commission",
    "eurostat",
)

TRADE_SOURCE_HINTS = (
    "digitimes",
    "semianalysis",
    "semiconductor engineering",
    "sourcing journal",
    "automotive news",
    "supply chain dive",
    "air current",
    "fierce",
    "endpoints",
    "freightwaves",
    "ad age",
    "payments dive",
    "banking dive",
    "retail dive",
    "utility dive",
    "construction dive",
)

MAJOR_NEWS_SOURCE_HINTS = (
    "reuters",
    "bloomberg",
    "financial times",
    "wall street journal",
    "wsj",
    "cnbc",
    "associated press",
    "ap",
    "marketwatch",
    "the information",
    "nikkei",
)

SOURCE_PRIORITY_SCORES = {
    "official": 1.0,
    "trade": 0.92,
    "major": 0.82,
    "other": 0.66,
    "social": 0.38,
}


@dataclass(frozen=True)
class EventDefinition:
    key: str
    label: str
    phrases: tuple[str, ...]
    tags: tuple[str, ...] = ()
    category: str = "general"


def classify_source_priority(publisher: str | None, *, source_type: str) -> str:
    if source_type == "social":
        return "social"
    normalized = (publisher or "").strip().lower()
    if not normalized:
        return "other"
    if any(hint in normalized for hint in OFFICIAL_SOURCE_HINTS):
        return "official"
    if any(hint in normalized for hint in TRADE_SOURCE_HINTS):
        return "trade"
    if any(hint in normalized for hint in MAJOR_NEWS_SOURCE_HINTS):
        return "major"
    return "other"


def extract_ranked_events(
    primary_items: list[object],
    supporting_items: list[object],
    definitions: list[EventDefinition],
    *,
    max_events: int = 5,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for definition in definitions:
        primary_matches = _match_items(primary_items, definition.phrases, source_type="news")
        supporting_matches = _match_items(supporting_items, definition.phrases, source_type="social")
        if not primary_matches and not supporting_matches:
            continue
        source_priority = _best_priority(primary_matches + supporting_matches)
        official_count = sum(1 for item in primary_matches if item["source_priority"] == "official")
        trade_count = sum(1 for item in primary_matches if item["source_priority"] == "trade")
        major_count = sum(1 for item in primary_matches if item["source_priority"] == "major")
        event_score = round(sum(float(item["event_weight"]) for item in primary_matches + supporting_matches), 3)
        evidence_samples: list[str] = []
        for item in sorted(
            primary_matches + supporting_matches,
            key=lambda match: (float(match["event_weight"]), int(match["match_count"])),
            reverse=True,
        )[:4]:
            sample = str(item["sample"])
            if sample not in evidence_samples:
                evidence_samples.append(sample)
        events.append(
            {
                "key": definition.key,
                "label": definition.label,
                "category": definition.category,
                "news_evidence_count": len(primary_matches),
                "social_evidence_count": len(supporting_matches),
                "evidence_count": (len(primary_matches) * 2) + len(supporting_matches),
                "source_priority": source_priority,
                "official_source_count": official_count,
                "trade_source_count": trade_count,
                "major_source_count": major_count,
                "event_score": event_score,
                "saliency_weight": round(min(1.0, event_score / 3.2), 3),
                "regime_tags": list(definition.tags),
                "evidence_samples": evidence_samples,
            }
        )
    events.sort(
        key=lambda item: (
            _priority_sort_key(str(item.get("source_priority", "other"))),
            float(item.get("event_score", 0.0) or 0.0),
            int(item.get("news_evidence_count", 0) or 0),
            int(item.get("social_evidence_count", 0) or 0),
        ),
        reverse=True,
    )
    return events[:max_events]


def source_priority_counts(items: list[object], *, source_type: str = "news") -> dict[str, int]:
    counts = {"official": 0, "trade": 0, "major": 0, "other": 0, "social": 0}
    for raw_item in items:
        priority = classify_source_priority(_item_publisher(raw_item), source_type=source_type)
        counts[priority] = counts.get(priority, 0) + 1
    return counts


def summarize_source_priorities(items: list[object], *, source_type: str = "news") -> list[str]:
    counts = source_priority_counts(items, source_type=source_type)
    return [f"{key}:{value}" for key, value in counts.items() if value > 0]


def top_event_labels(events: list[dict[str, object]], *, limit: int = 3) -> list[str]:
    labels: list[str] = []
    for event in events[:limit]:
        label = str(event.get("label", "")).strip()
        if label:
            labels.append(label)
    return labels


def event_keys(events: list[dict[str, object]], *, limit: int = 5) -> list[str]:
    keys: list[str] = []
    for event in events[:limit]:
        key = str(event.get("key", "")).strip()
        if key:
            keys.append(key)
    return keys


def highest_source_priority(items: list[object], *, source_type: str = "news") -> str | None:
    counts = source_priority_counts(items, source_type=source_type)
    for key in ("official", "trade", "major", "other", "social"):
        if counts.get(key, 0) > 0:
            return key
    return None


def publisher_summary(items: list[object], *, limit: int = 5) -> list[str]:
    publishers: list[str] = []
    for raw_item in items:
        publisher = _item_publisher(raw_item)
        if publisher and publisher not in publishers:
            publishers.append(publisher)
        if len(publishers) >= limit:
            break
    return publishers


def coverage_quality_label(items: list[object], *, source_type: str = "news") -> str:
    highest = highest_source_priority(items, source_type=source_type)
    if highest in {"official", "trade"}:
        return "high"
    if highest == "major":
        return "medium"
    if highest in {"other", "social"}:
        return "low"
    return "missing"


def count_events_above_saliency(events: list[dict[str, object]], *, threshold: float = 0.45) -> int:
    return sum(1 for event in events if float(event.get("saliency_weight", 0.0) or 0.0) >= threshold)


def filter_event_keys_by_category(events: list[dict[str, object]], category: str) -> list[str]:
    keys: list[str] = []
    for event in events:
        if str(event.get("category", "")) == category:
            key = str(event.get("key", "")).strip()
            if key:
                keys.append(key)
    return keys


def extract_event_tags(events: list[dict[str, object]]) -> list[str]:
    tags: list[str] = []
    for event in events:
        raw_tags = event.get("regime_tags")
        if isinstance(raw_tags, list):
            for tag in raw_tags:
                if isinstance(tag, str):
                    tags.append(tag)
    return list(dict.fromkeys(tags))


def summarize_event_scores(events: list[dict[str, object]], *, limit: int = 3) -> list[dict[str, object]]:
    summary: list[dict[str, object]] = []
    for event in events[:limit]:
        summary.append(
            {
                "key": event.get("key"),
                "label": event.get("label"),
                "source_priority": event.get("source_priority"),
                "event_score": event.get("event_score"),
                "saliency_weight": event.get("saliency_weight"),
            }
        )
    return summary


def _match_items(items: list[object], phrases: tuple[str, ...], *, source_type: str) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    for raw_item in items:
        text = _item_text(raw_item).lower()
        if not text:
            continue
        hit_count = sum(1 for phrase in phrases if phrase.lower() in text)
        if hit_count <= 0:
            continue
        publisher = _item_publisher(raw_item)
        source_priority = classify_source_priority(publisher, source_type=source_type)
        source_score = SOURCE_PRIORITY_SCORES[source_priority]
        recency_score = _recency_weight(_item_published_at(raw_item))
        event_weight = source_score * recency_score * (1.0 + min(0.75, (hit_count - 1) * 0.18))
        matches.append(
            {
                "match_count": hit_count,
                "source_priority": source_priority,
                "event_weight": round(event_weight, 3),
                "sample": _item_sample(raw_item, publisher, source_priority),
            }
        )
    return matches


def _priority_sort_key(priority: str) -> int:
    order = {"official": 5, "trade": 4, "major": 3, "other": 2, "social": 1}
    return order.get(priority, 0)


def _best_priority(matches: list[dict[str, object]]) -> str:
    if not matches:
        return "other"
    return max((str(item.get("source_priority", "other")) for item in matches), key=_priority_sort_key)


def _item_text(raw_item: object) -> str:
    if not isinstance(raw_item, dict):
        return ""
    parts: list[str] = []
    for key in ("title", "body", "summary"):
        value = raw_item.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " — ".join(parts)


def _item_publisher(raw_item: object) -> str:
    if not isinstance(raw_item, dict):
        return ""
    for key in ("publisher", "provider", "author", "author_handle"):
        value = raw_item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _item_published_at(raw_item: object) -> datetime | None:
    if not isinstance(raw_item, dict):
        return None
    value = raw_item.get("published_at")
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _recency_weight(published_at: datetime | None) -> float:
    if published_at is None:
        return 0.8
    age_days = max(0.0, (datetime.now(timezone.utc) - published_at).total_seconds() / 86400.0)
    if age_days <= 2:
        return 1.0
    if age_days <= 7:
        return 0.92
    if age_days <= 21:
        return 0.8
    return 0.68


def _item_sample(raw_item: object, publisher: str, source_priority: str) -> str:
    text = _item_text(raw_item)
    prefix = f"[{source_priority}]"
    if publisher:
        return f"{prefix} {publisher}: {text[:140]}"
    return f"{prefix} {text[:140]}"


__all__ = [
    "EventDefinition",
    "classify_source_priority",
    "coverage_quality_label",
    "count_events_above_saliency",
    "event_keys",
    "extract_event_tags",
    "extract_ranked_events",
    "filter_event_keys_by_category",
    "highest_source_priority",
    "publisher_summary",
    "source_priority_counts",
    "summarize_event_scores",
    "summarize_source_priorities",
    "top_event_labels",
]
