from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import re

from trade_proposer_app.services.taxonomy import TickerTaxonomyService

_TAXONOMY_SERVICE = TickerTaxonomyService()

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

POSITIVE_DIRECTION_HINTS = (
    "easing",
    "cut",
    "cuts",
    "cooling",
    "disinflation",
    "rebound",
    "strong",
    "strength",
    "accelerat",
    "beat",
    "approval",
    "growth",
    "recovery",
    "de-escalat",
    "demand strength",
    "pricing discipline",
)

NEGATIVE_DIRECTION_HINTS = (
    "tightening",
    "restrictive",
    "hike",
    "hikes",
    "sticky",
    "pressure",
    "selloff",
    "weak",
    "miss",
    "slowdown",
    "recession",
    "conflict",
    "escalat",
    "sanction",
    "destocking",
    "cost pressure",
)

STATE_TRANSITION_HINTS = {
    "escalating": (
        "escalat",
        "worsen",
        "intensif",
        "retaliat",
        "expand",
        "surge",
        "jump",
        "spike",
        "tightening",
        "hike",
        "crackdown",
        "disruption",
    ),
    "easing": (
        "de-escalat",
        "ease",
        "cooling",
        "relief",
        "ceasefire",
        "truce",
        "cut",
        "cuts",
        "disinflation",
        "approval",
        "rebound",
        "reopen",
    ),
    "stabilizing": (
        "stabiliz",
        "steady",
        "contained",
        "holding",
        "hold steady",
        "flat",
        "normaliz",
        "plateau",
        "balanced",
    ),
}

CATALYST_TYPE_HINTS = {
    "battlefield": ("missile", "drone", "strike", "troops", "attack", "battlefield", "military"),
    "diplomacy": ("ceasefire", "negotiation", "talks", "summit", "deal", "diplomatic"),
    "rhetoric": ("said", "comments", "remark", "speech", "warned", "threat", "rhetoric", "signaled"),
    "sanctions": ("sanction", "tariff", "export control", "blacklist", "embargo"),
    "supply_disruption": ("outage", "shutdown", "disruption", "bottleneck", "delay", "shortage", "halt"),
    "policy": ("policy", "fomc", "fed", "ecb", "treasury", "government", "administration", "regulator"),
    "guidance": ("guidance", "outlook", "forecast", "raised forecast", "cut forecast"),
    "pricing": ("pricing", "price", "discount", "surcharge", "fare", "rate card"),
    "demand": ("demand", "orders", "bookings", "traffic", "consumption", "spending"),
    "regulation": ("regulation", "approval", "antitrust", "compliance", "court", "ruling", "probe"),
}

MARKET_INTERPRETATION_HINTS = {
    "fear": ("fear", "risk off", "selloff", "safe haven", "pressure", "warning", "worsen"),
    "relief": ("relief", "rebound", "bounce", "easing", "de-escalat", "cooling"),
    "inflationary": ("inflation", "sticky prices", "higher prices", "cost pressure", "yield jump"),
    "growth_supportive": ("recovery", "strong demand", "acceleration", "beat", "upside", "soft landing"),
}

ACTOR_HINTS = {
    "Federal Reserve": "central_bank",
    "FOMC": "central_bank",
    "ECB": "central_bank",
    "European Central Bank": "central_bank",
    "Bank of England": "central_bank",
    "Bank of Japan": "central_bank",
    "U.S. Treasury": "government",
    "Treasury": "government",
    "OPEC": "intergovernmental_body",
    "White House": "executive_branch",
    "administration": "executive_branch",
    "government": "government",
    "regulator": "regulator",
    "FDA": "regulator",
    "SEC": "regulator",
    "European Commission": "regulator",
    "NATO": "intergovernmental_body",
    "Pentagon": "defense_establishment",
    "State Department": "government",
    "Commerce Department": "government",
    "Department of Justice": "regulator",
    "DOJ": "regulator",
    "FTC": "regulator",
    "CFPB": "regulator",
    "FAA": "regulator",
    "IRS": "government",
    "EIA": "government",
    "IAEA": "intergovernmental_body",
}

ACTOR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(the )?(federal reserve|fomc)\b", re.IGNORECASE), "central_bank"),
    (re.compile(r"\b(ecb|european central bank|bank of england|bank of japan)\b", re.IGNORECASE), "central_bank"),
    (re.compile(r"\b(u\.s\. treasury|treasury|white house|state department|commerce department|department of justice|doj)\b", re.IGNORECASE), "government"),
    (re.compile(r"\b(sec|fda|ftc|cfpb|faa|european commission|regulator)\b", re.IGNORECASE), "regulator"),
    (re.compile(r"\b(opec|nato|iaea)\b", re.IGNORECASE), "intergovernmental_body"),
    (re.compile(r"\b([A-Z][A-Za-z&.-]+(?:\s+[A-Z][A-Za-z&.-]+){0,2})\s+(?:said|says|warned|signaled|announced|approved|cut|raised)\b"), "named_actor"),
)


@dataclass(frozen=True)
class EventDefinition:
    key: str
    label: str
    phrases: tuple[str, ...]
    tags: tuple[str, ...] = ()
    category: str = "general"
    window_hint: str = "unknown"
    transmission_channels: tuple[str, ...] = ()
    beneficiary_tags: tuple[str, ...] = ()
    loser_tags: tuple[str, ...] = ()


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
    previous_events: list[dict[str, object]] | None = None,
    max_events: int = 5,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    previous_map = {
        str(item.get("key", "")).strip(): item
        for item in (previous_events or [])
        if isinstance(item, dict) and str(item.get("key", "")).strip()
    }
    for definition in definitions:
        primary_matches = _dedupe_matches(_match_items(primary_items, definition.phrases, source_type="news"))
        supporting_matches = _dedupe_matches(_match_items(supporting_items, definition.phrases, source_type="social"))
        if not primary_matches and not supporting_matches:
            continue
        all_matches = primary_matches + supporting_matches
        source_priority = _best_priority(all_matches)
        official_count = sum(1 for item in primary_matches if item["source_priority"] == "official")
        trade_count = sum(1 for item in primary_matches if item["source_priority"] == "trade")
        major_count = sum(1 for item in primary_matches if item["source_priority"] == "major")
        event_score = round(sum(float(item["event_weight"]) for item in all_matches), 3)
        evidence_samples: list[str] = []
        for item in sorted(
            all_matches,
            key=lambda match: (float(match["event_weight"]), int(match["match_count"])),
            reverse=True,
        )[:4]:
            sample = str(item["sample"])
            if sample not in evidence_samples:
                evidence_samples.append(sample)
        previous = previous_map.get(definition.key)
        latest_published_at = _latest_timestamp(all_matches)
        evidence_direction = _event_direction(all_matches)
        contradiction_reasons = _contradiction_reasons(all_matches, previous)
        state_transition = _state_transition(all_matches, previous)
        catalyst_type = _catalyst_type(all_matches)
        trigger_actor, trigger_actor_role, trigger_source_type = _trigger_actor(all_matches)
        market_interpretation = _market_interpretation(all_matches, evidence_direction, state_transition)
        state_change_reason = _state_change_reason(all_matches, catalyst_type, state_transition, market_interpretation)
        events.append(
            {
                "key": definition.key,
                "label": definition.label,
                "category": definition.category,
                "news_evidence_count": len(primary_matches),
                "social_evidence_count": len(supporting_matches),
                "evidence_count": (len(primary_matches) * 2) + len(supporting_matches),
                "unique_evidence_count": len(all_matches),
                "publisher_count": len({item.get("publisher", "") for item in all_matches if item.get("publisher")}),
                "source_priority": source_priority,
                "source_priority_detail": _key_label_detail("source_priority", source_priority),
                "official_source_count": official_count,
                "trade_source_count": trade_count,
                "major_source_count": major_count,
                "event_score": event_score,
                # Spread saliency across the 0-1 range instead of flattening most
                # multi-source events to 1.0. A score of ~4.5 now maps to ~0.63.
                "saliency_weight": round(1.0 - math.exp(-event_score / 4.5), 3),
                "regime_tags": list(definition.tags),
                "transmission_channels": list(definition.transmission_channels),
                "beneficiary_tags": list(definition.beneficiary_tags),
                "loser_tags": list(definition.loser_tags),
                "window_hint": definition.window_hint,
                "window_hint_detail": _key_label_detail("window_hint", definition.window_hint),
                "latest_published_at": latest_published_at.isoformat() if latest_published_at is not None else None,
                "recency_bucket": _recency_bucket(latest_published_at),
                "recency_bucket_detail": _key_label_detail("recency_bucket", _recency_bucket(latest_published_at)),
                "evidence_direction": evidence_direction,
                "state_transition": state_transition,
                "catalyst_type": catalyst_type,
                "trigger_actor": trigger_actor,
                "trigger_actor_role": trigger_actor_role,
                "trigger_source_type": trigger_source_type,
                "market_interpretation": market_interpretation,
                "state_change_reason": state_change_reason,
                "persistence_state": _persistence_state(previous, event_score, len(all_matches)),
                "persistence_state_detail": _key_label_detail("persistence_state", _persistence_state(previous, event_score, len(all_matches))),
                "previous_event_score": _float_value(previous.get("event_score")) if isinstance(previous, dict) else None,
                "score_change_percent": _score_change_percent(previous, event_score),
                "contradiction_flag": bool(contradiction_reasons),
                "contradiction_count": len(contradiction_reasons),
                "contradiction_reasons": contradiction_reasons,
                "contradiction_reason_details": _contradiction_reason_details(contradiction_reasons),
                "evidence_samples": evidence_samples,
            }
        )
    events.sort(
        key=lambda item: (
            _priority_sort_key(str(item.get("source_priority", "other"))),
            float(item.get("event_score", 0.0) or 0.0),
            _persistence_sort_key(str(item.get("persistence_state", "new"))),
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
                "persistence_state": event.get("persistence_state"),
                "state_transition": event.get("state_transition"),
                "catalyst_type": event.get("catalyst_type"),
                "market_interpretation": event.get("market_interpretation"),
                "window_hint": event.get("window_hint"),
                "contradiction_flag": event.get("contradiction_flag"),
            }
        )
    return summary


def summarize_event_lifecycle(
    events: list[dict[str, object]],
    *,
    previous_events: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    labels_by_state = {
        "new": [],
        "escalating": [],
        "persistent": [],
        "fading": [],
    }
    contradiction_labels: list[str] = []
    current_keys: list[str] = []
    current_key_set: set[str] = set()
    windows: list[str] = []
    for event in events:
        key = str(event.get("key", "")).strip()
        label = str(event.get("label", "")).strip()
        state = str(event.get("persistence_state", "new") or "new")
        window = str(event.get("window_hint", "") or "").strip()
        if key:
            current_keys.append(key)
            current_key_set.add(key)
        if label and state in labels_by_state:
            labels_by_state[state].append(label)
        if bool(event.get("contradiction_flag")) and label:
            contradiction_labels.append(label)
        if window and window not in windows:
            windows.append(window)
    dropped_event_keys: list[str] = []
    dropped_event_labels: list[str] = []
    for previous in previous_events or []:
        if not isinstance(previous, dict):
            continue
        key = str(previous.get("key", "")).strip()
        label = str(previous.get("label", "")).strip()
        if key and key not in current_key_set:
            dropped_event_keys.append(key)
            if label:
                dropped_event_labels.append(label)
    return {
        "new_event_labels": labels_by_state["new"],
        "escalating_event_labels": labels_by_state["escalating"],
        "persistent_event_labels": labels_by_state["persistent"],
        "fading_event_labels": labels_by_state["fading"],
        "contradictory_event_labels": contradiction_labels,
        "dropped_event_labels": dropped_event_labels,
        "dropped_event_keys": dropped_event_keys,
        "current_event_keys": current_keys,
        "window_hints": windows,
        "new_event_count": len(labels_by_state["new"]),
        "escalating_event_count": len(labels_by_state["escalating"]),
        "persistent_event_count": len(labels_by_state["persistent"]),
        "fading_event_count": len(labels_by_state["fading"]),
        "contradiction_count": len(contradiction_labels),
        "dropped_event_count": len(dropped_event_labels),
    }


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
        published_at = _item_published_at(raw_item)
        recency_score = _recency_weight(published_at)
        event_weight = source_score * recency_score * (1.0 + min(0.75, (hit_count - 1) * 0.18))
        matches.append(
            {
                "match_count": hit_count,
                "source_priority": source_priority,
                "event_weight": round(event_weight, 3),
                "sample": _item_sample(raw_item, publisher, source_priority),
                "publisher": publisher,
                "published_at": published_at,
                "signature": _item_signature(raw_item),
                "direction": _text_direction(text),
                "text": text,
            }
        )
    return matches


def _dedupe_matches(matches: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: dict[str, dict[str, object]] = {}
    for match in matches:
        signature = str(match.get("signature", "")).strip() or str(match.get("sample", "")).strip()
        existing = deduped.get(signature)
        if existing is None:
            deduped[signature] = match
            continue
        if float(match.get("event_weight", 0.0) or 0.0) > float(existing.get("event_weight", 0.0) or 0.0):
            deduped[signature] = match
    return list(deduped.values())


def _priority_sort_key(priority: str) -> int:
    order = {"official": 5, "trade": 4, "major": 3, "other": 2, "social": 1}
    return order.get(priority, 0)


def _persistence_sort_key(state: str) -> int:
    order = {"escalating": 4, "new": 3, "persistent": 2, "fading": 1}
    return order.get(state, 0)


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


def _item_signature(raw_item: object) -> str:
    return _normalize_text(_item_text(raw_item))


def _normalize_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    return re.sub(r"[^a-z0-9 ]+", "", normalized)


def _text_direction(text: str) -> str:
    positive_hits = sum(1 for hint in POSITIVE_DIRECTION_HINTS if hint in text)
    negative_hits = sum(1 for hint in NEGATIVE_DIRECTION_HINTS if hint in text)
    if positive_hits and negative_hits:
        return "mixed"
    if positive_hits:
        return "positive"
    if negative_hits:
        return "negative"
    return "neutral"


def _event_direction(matches: list[dict[str, object]]) -> str:
    counts = {"positive": 0, "negative": 0, "mixed": 0}
    for item in matches:
        direction = str(item.get("direction", "neutral"))
        if direction in counts:
            counts[direction] += 1
    if counts["mixed"] > 0 or (counts["positive"] > 0 and counts["negative"] > 0):
        return "mixed"
    if counts["positive"] > 0:
        return "positive"
    if counts["negative"] > 0:
        return "negative"
    return "neutral"


def _contradiction_reasons(matches: list[dict[str, object]], previous: dict[str, object] | None) -> list[str]:
    reasons: list[str] = []
    current_direction = _event_direction(matches)
    directions = {str(item.get("direction", "neutral")) for item in matches}
    if "positive" in directions and "negative" in directions:
        reasons.append("mixed_directional_evidence")
    if "mixed" in directions:
        reasons.append("ambiguous_evidence_text")
    previous_direction = str(previous.get("evidence_direction", "neutral")) if isinstance(previous, dict) else "neutral"
    if previous_direction in {"positive", "negative"} and current_direction in {"positive", "negative"} and previous_direction != current_direction:
        reasons.append("direction_changed_vs_previous_snapshot")
    return list(dict.fromkeys(reasons))


def _contradiction_reason_details(reasons: list[str]) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    seen: set[str] = set()
    for reason in reasons:
        detail = _key_label_detail("contradiction_reason", reason)
        key = str(detail.get("key", reason)).strip() or reason
        if key in seen:
            continue
        seen.add(key)
        details.append({"key": key, "label": str(detail.get("label", reason.replace("_", " "))).strip() or reason.replace("_", " ")})
    return details


def _state_transition(matches: list[dict[str, object]], previous: dict[str, object] | None) -> str:
    scores = {"escalating": 0, "easing": 0, "stabilizing": 0}
    for item in matches:
        text = str(item.get("text", "") or "").lower()
        for state, hints in STATE_TRANSITION_HINTS.items():
            scores[state] += sum(1 for hint in hints if hint in text)
    if max(scores.values(), default=0) <= 0:
        direction = _event_direction(matches)
        previous_direction = str(previous.get("evidence_direction", "neutral")) if isinstance(previous, dict) else "neutral"
        if direction == "positive":
            return "easing"
        if direction == "negative":
            return "escalating"
        if previous_direction == direction == "neutral":
            return "unknown"
        return "mixed" if direction == "mixed" else "unknown"
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if len(ordered) > 1 and ordered[0][1] == ordered[1][1] and ordered[0][1] > 0:
        return "mixed"
    return ordered[0][0]


def _catalyst_type(matches: list[dict[str, object]]) -> str:
    scores = {key: 0 for key in CATALYST_TYPE_HINTS}
    for item in matches:
        text = str(item.get("text", "") or "").lower()
        for catalyst, hints in CATALYST_TYPE_HINTS.items():
            scores[catalyst] += sum(1 for hint in hints if hint in text)
    best = max(scores.items(), key=lambda item: item[1], default=("other", 0))
    return best[0] if best[1] > 0 else "other"


def _trigger_actor(matches: list[dict[str, object]]) -> tuple[str | None, str | None, str | None]:
    scored: list[tuple[float, str, str, str]] = []
    for item in matches:
        text = str(item.get("text", "") or "")
        weight = float(item.get("event_weight", 0.0) or 0.0)
        for actor, role in ACTOR_HINTS.items():
            if actor.lower() in text.lower():
                scored.append((weight + 1.0, actor, role, "text_match"))
        for pattern, role in ACTOR_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            actor = match.group(1) if role == "named_actor" and match.groups() else match.group(0)
            cleaned_actor = re.sub(r"^(the )", "", str(actor), flags=re.IGNORECASE).strip(" .,:;-")
            if cleaned_actor:
                resolved_role = _normalize_actor_role(cleaned_actor, role)
                scored.append((weight + 0.8, cleaned_actor, resolved_role, "regex_match"))
        publisher = str(item.get("publisher", "") or "").strip()
        if publisher:
            scored.append((weight + 0.25, publisher, "source_publisher", "publisher"))
    if not scored:
        return None, None, None
    scored.sort(key=lambda item: item[0], reverse=True)
    _, actor, role, source_type = scored[0]
    return actor, role, source_type


def _normalize_actor_role(actor: str, fallback_role: str) -> str:
    lowered = actor.lower()
    for known_actor, role in ACTOR_HINTS.items():
        if known_actor.lower() == lowered:
            return role
    if fallback_role != "named_actor":
        return fallback_role
    if any(token in lowered for token in ("department", "ministry", "treasury", "government", "administration")):
        return "government"
    if any(token in lowered for token in ("commission", "agency", "sec", "fda", "ftc", "regulator")):
        return "regulator"
    if any(token in lowered for token in ("bank", "federal reserve", "ecb", "fomc")):
        return "central_bank"
    if any(token in lowered for token in ("opec", "nato", "iaea")):
        return "intergovernmental_body"
    return "named_actor"


def _market_interpretation(matches: list[dict[str, object]], evidence_direction: str, state_transition: str) -> str:
    scores = {key: 0 for key in MARKET_INTERPRETATION_HINTS}
    for item in matches:
        text = str(item.get("text", "") or "").lower()
        for interpretation, hints in MARKET_INTERPRETATION_HINTS.items():
            scores[interpretation] += sum(1 for hint in hints if hint in text)
    best_key, best_score = max(scores.items(), key=lambda item: item[1], default=("unknown", 0))
    if best_score > 0:
        leaders = [key for key, score in scores.items() if score == best_score and score > 0]
        return leaders[0] if len(leaders) == 1 else "mixed"
    if evidence_direction == "positive" or state_transition == "easing":
        return "relief"
    if evidence_direction == "negative" or state_transition == "escalating":
        return "fear"
    if evidence_direction == "mixed" or state_transition == "mixed":
        return "mixed"
    return "unknown"


def _state_change_reason(
    matches: list[dict[str, object]],
    catalyst_type: str,
    state_transition: str,
    market_interpretation: str,
) -> str | None:
    top_sample = ""
    if matches:
        top = max(matches, key=lambda item: float(item.get("event_weight", 0.0) or 0.0))
        top_sample = str(top.get("sample", "") or "").strip()
    catalyst_text = catalyst_type.replace("_", " ") if catalyst_type else "unclear catalyst"
    state_text = state_transition.replace("_", " ") if state_transition else "unclear state"
    interpretation_text = market_interpretation.replace("_", " ") if market_interpretation else "unclear interpretation"
    if top_sample:
        return f"{state_text} signal led by {catalyst_text}; current read looks {interpretation_text}. Evidence: {top_sample[:180]}"
    return f"{state_text} signal led by {catalyst_text}; current read looks {interpretation_text}."


def _key_label_detail(kind: str, value: str) -> dict[str, str]:
    if kind == "source_priority":
        definition = _TAXONOMY_SERVICE.get_event_source_priority_definition(value)
    elif kind == "persistence_state":
        definition = _TAXONOMY_SERVICE.get_event_persistence_state_definition(value)
    elif kind == "window_hint":
        definition = _TAXONOMY_SERVICE.get_event_window_hint_definition(value)
    elif kind == "recency_bucket":
        definition = _TAXONOMY_SERVICE.get_event_recency_bucket_definition(value)
    else:
        definition = _TAXONOMY_SERVICE.get_contradiction_reason_definition(value)
    key = str(definition.get("key", value)).strip() or value
    label = str(definition.get("label", value.replace("_", " "))).strip() or value.replace("_", " ")
    return {"key": key, "label": label}


def _latest_timestamp(matches: list[dict[str, object]]) -> datetime | None:
    timestamps = [item.get("published_at") for item in matches if isinstance(item.get("published_at"), datetime)]
    if not timestamps:
        return None
    return max(timestamps)


def _recency_bucket(published_at: datetime | None) -> str:
    if published_at is None:
        return "unknown"
    age_days = max(0.0, (datetime.now(timezone.utc) - published_at).total_seconds() / 86400.0)
    if age_days <= 2:
        return "fresh"
    if age_days <= 7:
        return "recent"
    if age_days <= 21:
        return "aging"
    return "stale"


def _persistence_state(previous: dict[str, object] | None, current_score: float, current_match_count: int) -> str:
    if not isinstance(previous, dict):
        return "new"
    previous_score = _float_value(previous.get("event_score")) or 0.0
    previous_count = int(previous.get("unique_evidence_count", previous.get("evidence_count", 0)) or 0)
    if previous_score <= 0.0:
        return "new"
    if current_score >= previous_score * 1.22 or current_match_count >= previous_count + 2:
        return "escalating"
    if current_score <= previous_score * 0.72:
        return "fading"
    return "persistent"


def _score_change_percent(previous: dict[str, object] | None, current_score: float) -> float | None:
    if not isinstance(previous, dict):
        return None
    previous_score = _float_value(previous.get("event_score"))
    if previous_score is None or previous_score <= 0.0:
        return None
    return round(((current_score - previous_score) / previous_score) * 100.0, 1)


def _float_value(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    "summarize_event_lifecycle",
    "summarize_event_scores",
    "summarize_source_priorities",
    "top_event_labels",
]
