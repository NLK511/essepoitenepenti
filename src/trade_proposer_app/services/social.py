from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import unescape
from statistics import pstdev
from typing import Any, ClassVar
from urllib.parse import quote, urljoin

import httpx

from trade_proposer_app.domain.models import SignalBundle, SignalEngagement, SignalItem
from trade_proposer_app.services.news import (
    NEGATIVE_KEYWORD_WEIGHTS,
    NEGATIVE_PHRASE_WEIGHTS,
    POSITIVE_KEYWORD_WEIGHTS,
    POSITIVE_PHRASE_WEIGHTS,
    SUMMARY_KEYWORD_WEIGHT,
    TITLE_KEYWORD_WEIGHT,
    _count_keyword_matches,
    _phrase_score_and_hits,
    _sum_keyword_weights,
    _tokenize,
)
from trade_proposer_app.services.taxonomy import TickerTaxonomyService

NITTER_SEARCH_PATH = "/search"
TIMELINE_ITEM_PATTERN = re.compile(
    r'<div class="timeline-item\b(?P<body>.*?)(?=<div class="timeline-item\b|<div class="show-more|</main>|$)',
    re.DOTALL,
)
STATUS_LINK_PATTERN = re.compile(r'href="(?P<link>/[^\"]+/status/(?P<status_id>\d+)[^\"]*)"')
CONTENT_PATTERN = re.compile(r'<div class="tweet-content[^\"]*"[^>]*>(?P<content>.*?)</div>', re.DOTALL)
FULLNAME_PATTERN = re.compile(r'<a[^>]*class="fullname"[^>]*>(?P<value>.*?)</a>', re.DOTALL)
USERNAME_PATTERN = re.compile(r'<a[^>]*class="username"[^>]*>(?P<value>.*?)</a>', re.DOTALL)
DATE_PATTERN = re.compile(r'title="(?P<value>[^\"]+)"')
STAT_PATTERN_TEMPLATE = r'<span class="icon-{name}"></span>\s*(?P<value>[\d,]+)'
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


class SocialFetchError(Exception):
    pass


@dataclass
class SocialProvider:
    timeout: float = 6.0

    name: ClassVar[str] = "generic-social"

    def fetch(self, ticker: str) -> SignalBundle:
        raise NotImplementedError

    def fetch_subject(self, subject_key: str, queries: list[str], *, scope_tag: str) -> SignalBundle:
        raise NotImplementedError


class NitterProvider(SocialProvider):
    name: ClassVar[str] = "Nitter"

    def __init__(
        self,
        *,
        base_url: str,
        taxonomy_service: TickerTaxonomyService | None = None,
        timeout: float = 6.0,
        max_items_per_query: int = 12,
        query_window_hours: int = 12,
        include_replies: bool = False,
        max_queries_per_subject: int | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        self.base_url = base_url.rstrip("/")
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()
        self.max_items_per_query = max(1, max_items_per_query)
        self.query_window_hours = max(1, query_window_hours)
        self.include_replies = include_replies
        self.max_queries_per_subject = None if max_queries_per_subject is None or max_queries_per_subject < 1 else max_queries_per_subject

    def fetch(self, ticker: str) -> SignalBundle:
        query_profile = self.taxonomy_service.build_query_profile(ticker)
        ticker_queries = self._limit_queries(query_profile.get("ticker_queries", []))
        return self._fetch_queries(
            subject_key=ticker,
            queries=ticker_queries,
            scope_tag="ticker",
            ticker=ticker,
            query_profile=query_profile,
        )

    def fetch_subject(self, subject_key: str, queries: list[str], *, scope_tag: str) -> SignalBundle:
        query_profile = {
            "ticker_queries": queries if scope_tag == "ticker" else [],
            "industry_queries": queries if scope_tag == "industry" else [],
            "macro_queries": queries if scope_tag == "macro" else [],
            "exclude_keywords": [],
        }
        return self._fetch_queries(
            subject_key=subject_key,
            queries=self._limit_queries(queries),
            scope_tag=scope_tag,
            ticker=subject_key,
            query_profile=query_profile,
        )

    def _limit_queries(self, queries: list[str]) -> list[str]:
        if self.max_queries_per_subject is None:
            return queries
        return queries[: self.max_queries_per_subject]

    def _fetch_queries(
        self,
        *,
        subject_key: str,
        queries: list[str],
        scope_tag: str,
        ticker: str,
        query_profile: dict[str, list[str]],
    ) -> SignalBundle:
        fetched_items: list[SignalItem] = []
        executed_queries: list[str] = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.query_window_hours)
        for query in queries:
            url = f"{self.base_url}{NITTER_SEARCH_PATH}?f=tweets&q={quote(query)}"
            try:
                response = httpx.get(url, timeout=self.timeout, follow_redirects=True)
            except Exception as exc:  # noqa: BLE001
                raise SocialFetchError(f"request failed for query '{query}': {exc}") from exc
            if response.status_code != 200:
                raise SocialFetchError(f"unexpected status {response.status_code} for query '{query}'")
            items = self._parse_search_html(response.text, ticker=ticker, query_profile=query_profile)
            filtered_items = [
                item
                for item in items
                if (item.published_at is None or item.published_at >= cutoff)
                and not any(term in item.body.lower() for term in query_profile.get("exclude_keywords", []))
            ]
            if scope_tag:
                for item in filtered_items:
                    if scope_tag not in item.scope_tags:
                        item.scope_tags = list(dict.fromkeys(item.scope_tags + [scope_tag]))
            fetched_items.extend(filtered_items)
            executed_queries.append(query)
        return SignalBundle(
            ticker=subject_key,
            items=fetched_items[: self.max_items_per_query],
            feeds_used=[self.name] if fetched_items else [],
            feed_errors=[],
            coverage={
                "social_count": len(fetched_items[: self.max_items_per_query]),
                "query_window_hours": self.query_window_hours,
            },
            query_diagnostics={
                f"{scope_tag}_queries": executed_queries,
                "industry_queries": query_profile.get("industry_queries", []),
                "macro_queries": query_profile.get("macro_queries", []),
                "base_url": self.base_url,
                "include_replies": self.include_replies,
            },
        )

    def _parse_search_html(self, html: str, *, ticker: str, query_profile: dict[str, list[str]]) -> list[SignalItem]:
        items: list[SignalItem] = []
        for match in TIMELINE_ITEM_PATTERN.finditer(html):
            body = match.group("body")
            status_match = STATUS_LINK_PATTERN.search(body)
            content_match = CONTENT_PATTERN.search(body)
            if content_match is None:
                continue
            content = self._clean_html(content_match.group("content"))
            if not content:
                continue
            author = self._extract(FULLNAME_PATTERN, body)
            handle = self._extract(USERNAME_PATTERN, body).lstrip("@") or None
            status_link = None
            status_id = None
            if status_match is not None:
                status_link = urljoin(f"{self.base_url}/", status_match.group("link").lstrip("/"))
                status_id = status_match.group("status_id")
            engagement = SignalEngagement(
                replies=self._extract_stat("reply", body),
                retweets=self._extract_stat("retweet", body),
                likes=self._extract_stat("heart", body),
                quotes=0,
            )
            published_at = self._extract_datetime(body)
            lower_content = content.lower()
            scope_tags = self._infer_scope_tags(lower_content, query_profile)
            if not scope_tags:
                scope_tags = ["ticker"]
            items.append(
                SignalItem(
                    source_type="social",
                    provider="nitter",
                    item_id=status_id,
                    title=content[:140],
                    body=content,
                    author=author or None,
                    author_handle=handle,
                    publisher=self.name,
                    link=status_link,
                    published_at=published_at,
                    engagement=engagement,
                    raw_metadata={"status_id": status_id},
                    matched_entities={"ticker": [ticker.upper()]},
                    scope_tags=scope_tags,
                    quality_score=self._estimate_quality_score(content, engagement),
                    credibility_score=self._estimate_credibility_score(handle, engagement),
                    dedupe_key=status_link or status_id or content[:80],
                )
            )
        return items

    def _extract(self, pattern: re.Pattern[str], body: str) -> str:
        match = pattern.search(body)
        if match is None:
            return ""
        return self._clean_html(match.group("value"))

    def _extract_stat(self, name: str, body: str) -> int:
        pattern = re.compile(STAT_PATTERN_TEMPLATE.format(name=re.escape(name)))
        match = pattern.search(body)
        if match is None:
            return 0
        raw = match.group("value").replace(",", "").strip()
        try:
            return int(raw)
        except ValueError:
            return 0

    def _extract_datetime(self, body: str) -> datetime | None:
        match = DATE_PATTERN.search(body)
        if match is None:
            return None
        raw = unescape(match.group("value")).strip()
        for fmt in ("%b %d, %Y · %I:%M %p UTC", "%b %d, %Y · %H:%M UTC", "%Y-%m-%d %H:%M:%S %Z"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    @staticmethod
    def _clean_html(value: str) -> str:
        text = TAG_RE.sub(" ", unescape(value or ""))
        return WHITESPACE_RE.sub(" ", text).strip()

    @staticmethod
    def _infer_scope_tags(text: str, query_profile: dict[str, list[str]]) -> list[str]:
        scopes: list[str] = []
        if any(term.lower() in text for term in query_profile.get("macro_queries", [])):
            scopes.append("macro")
        if any(term.lower() in text for term in query_profile.get("industry_queries", [])):
            scopes.append("industry")
        if any(term.lower() in text for term in query_profile.get("ticker_queries", [])):
            scopes.append("ticker")
        return scopes

    @staticmethod
    def _estimate_quality_score(content: str, engagement: SignalEngagement) -> float:
        content_factor = min(len(content.split()) / 20.0, 1.0)
        engagement_factor = min((engagement.likes + engagement.retweets + engagement.replies) / 100.0, 1.0)
        return round(min(1.0, (content_factor * 0.7) + (engagement_factor * 0.3)), 3)

    @staticmethod
    def _estimate_credibility_score(handle: str | None, engagement: SignalEngagement) -> float:
        base = 0.35 if not handle else 0.45
        if handle and any(token in handle.lower() for token in ("news", "markets", "finance", "journal")):
            base += 0.2
        if engagement.retweets > 25:
            base += 0.1
        if engagement.likes > 100:
            base += 0.1
        return round(min(1.0, base), 3)


class SocialSentimentAnalyzer:
    def analyze(self, bundle: SignalBundle) -> dict[str, Any]:
        scores: list[float] = []
        keyword_hits = 0
        weighted_sum = 0.0
        weight_total = 0.0
        scope_totals: dict[str, dict[str, float]] = {
            "macro": {"weighted_sum": 0.0, "weight_total": 0.0, "item_count": 0.0},
            "industry": {"weighted_sum": 0.0, "weight_total": 0.0, "item_count": 0.0},
            "ticker": {"weighted_sum": 0.0, "weight_total": 0.0, "item_count": 0.0},
        }
        for item in bundle.items:
            text = f"{item.title} {item.body}".strip().lower()
            title_tokens = _tokenize(item.title)
            body_tokens = _tokenize(item.body)
            positive = (
                _sum_keyword_weights(title_tokens, POSITIVE_KEYWORD_WEIGHTS, TITLE_KEYWORD_WEIGHT)
                + _sum_keyword_weights(body_tokens, POSITIVE_KEYWORD_WEIGHTS, SUMMARY_KEYWORD_WEIGHT)
            )
            negative = (
                _sum_keyword_weights(title_tokens, NEGATIVE_KEYWORD_WEIGHTS, TITLE_KEYWORD_WEIGHT)
                + _sum_keyword_weights(body_tokens, NEGATIVE_KEYWORD_WEIGHTS, SUMMARY_KEYWORD_WEIGHT)
            )
            phrase_positive, positive_hits = _phrase_score_and_hits(text, POSITIVE_PHRASE_WEIGHTS)
            phrase_negative, negative_hits = _phrase_score_and_hits(text, NEGATIVE_PHRASE_WEIGHTS)
            positive += phrase_positive
            negative += phrase_negative
            keyword_hits += (
                _count_keyword_matches(title_tokens, POSITIVE_KEYWORD_WEIGHTS)
                + _count_keyword_matches(body_tokens, POSITIVE_KEYWORD_WEIGHTS)
                + _count_keyword_matches(title_tokens, NEGATIVE_KEYWORD_WEIGHTS)
                + _count_keyword_matches(body_tokens, NEGATIVE_KEYWORD_WEIGHTS)
                + positive_hits
                + negative_hits
            )
            gross = positive + negative
            score = 0.0 if gross == 0 else max(-1.0, min(1.0, (positive - negative) / (gross + 0.35)))
            weight = self._item_weight(item)
            scores.append(score)
            weighted_sum += score * weight
            weight_total += weight
            for scope in item.scope_tags:
                if scope not in scope_totals:
                    continue
                scope_totals[scope]["weighted_sum"] += score * weight
                scope_totals[scope]["weight_total"] += weight
                scope_totals[scope]["item_count"] += 1.0
        final_score = weighted_sum / weight_total if weight_total else 0.0
        final_score = max(-1.0, min(1.0, final_score))
        label = "NEUTRAL"
        if final_score > 0.15:
            label = "POSITIVE"
        elif final_score < -0.15:
            label = "NEGATIVE"
        coverage_insights: list[str] = []
        if not bundle.items:
            coverage_insights.append("social: no items fetched from Nitter for the current subject query profile.")
        elif keyword_hits == 0:
            coverage_insights.append("social: posts arrived but no sentiment keywords matched, so the score stays neutral per the signal integrity policy.")
        if bundle.feed_errors:
            coverage_insights.append(f"social: provider issues ({'; '.join(bundle.feed_errors)})")
        social_items = [
            {
                "title": item.title,
                "body": item.body,
                "author": item.author,
                "author_handle": item.author_handle,
                "link": item.link,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "scope_tags": item.scope_tags,
                "quality_score": item.quality_score,
                "credibility_score": item.credibility_score,
                "engagement": item.engagement.model_dump(),
            }
            for item in bundle.items
        ]
        scope_breakdown = {
            scope: {
                "score": (values["weighted_sum"] / values["weight_total"]) if values["weight_total"] else 0.0,
                "label": self._label_score((values["weighted_sum"] / values["weight_total"]) if values["weight_total"] else 0.0),
                "item_count": int(values["item_count"]),
            }
            for scope, values in scope_totals.items()
        }
        return {
            "score": final_score,
            "label": label,
            "keyword_hits": keyword_hits,
            "coverage_insights": coverage_insights,
            "sentiment_volatility": pstdev(scores) if len(scores) > 1 else 0.0,
            "item_count": len(bundle.items),
            "sources": bundle.feeds_used,
            "items": social_items,
            "scope_breakdown": scope_breakdown,
        }

    @staticmethod
    def _label_score(score: float) -> str:
        if score > 0.15:
            return "POSITIVE"
        if score < -0.15:
            return "NEGATIVE"
        return "NEUTRAL"

    def _item_weight(self, item: SignalItem) -> float:
        engagement = item.engagement.likes + (item.engagement.retweets * 2) + item.engagement.replies
        engagement_weight = 1.0 + min(engagement / 200.0, 0.3)
        recency_weight = 1.0
        if item.published_at is not None:
            age_hours = max((datetime.now(timezone.utc) - item.published_at).total_seconds() / 3600.0, 0.0)
            recency_weight = max(0.35, 1.0 - min(age_hours / 24.0, 0.65))
        credibility_weight = max(0.35, float(item.credibility_score or 0.0))
        quality_weight = max(0.35, float(item.quality_score or 0.0))
        return engagement_weight * recency_weight * credibility_weight * quality_weight


class SocialIngestionService:
    def __init__(
        self,
        providers: list[SocialProvider] | None = None,
        *,
        taxonomy_service: TickerTaxonomyService | None = None,
    ) -> None:
        self.providers = list(providers or [])
        self.taxonomy_service = taxonomy_service or TickerTaxonomyService()
        self.sentiment_analyzer = SocialSentimentAnalyzer()

    @classmethod
    def from_settings(cls, social_settings: dict[str, str] | None = None) -> "SocialIngestionService":
        values = social_settings or {}
        taxonomy_service = TickerTaxonomyService()
        enabled = (values.get("social_sentiment_enabled") or "false").strip().lower() == "true"
        nitter_enabled = (values.get("social_nitter_enabled") or "false").strip().lower() == "true"
        if not enabled or not nitter_enabled:
            return cls([], taxonomy_service=taxonomy_service)
        provider = NitterProvider(
            base_url=(values.get("social_nitter_base_url") or "http://127.0.0.1:8080").strip(),
            taxonomy_service=taxonomy_service,
            timeout=_parse_float(values.get("social_nitter_timeout_seconds"), 6.0),
            max_items_per_query=_parse_int(values.get("social_nitter_max_items_per_query"), 12),
            query_window_hours=_parse_int(values.get("social_nitter_query_window_hours"), 12),
            include_replies=(values.get("social_nitter_include_replies") or "false").strip().lower() == "true",
        )
        return cls([provider], taxonomy_service=taxonomy_service)

    def fetch(self, ticker: str) -> SignalBundle:
        bundle = SignalBundle(ticker=ticker)
        if not self.providers:
            bundle.feed_errors.append("social: no providers configured")
            bundle.coverage = {"social_count": 0}
            return bundle
        for provider in self.providers:
            try:
                provider_bundle = provider.fetch(ticker)
            except Exception as exc:  # noqa: BLE001
                bundle.feed_errors.append(f"{provider.name}: {exc}")
                continue
            bundle.items.extend(provider_bundle.items)
            bundle.feeds_used.extend(provider_bundle.feeds_used)
            bundle.feed_errors.extend(provider_bundle.feed_errors)
            bundle.coverage.update(provider_bundle.coverage)
            if provider_bundle.query_diagnostics:
                bundle.query_diagnostics[provider.name.lower()] = provider_bundle.query_diagnostics
        deduped: list[SignalItem] = []
        seen: set[str] = set()
        for item in bundle.items:
            key = item.dedupe_key or item.link or item.item_id or item.body
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        bundle.items = deduped
        bundle.feeds_used = list(dict.fromkeys(bundle.feeds_used))
        bundle.feed_errors = list(dict.fromkeys(bundle.feed_errors))
        bundle.coverage.setdefault("social_count", len(bundle.items))
        return bundle

    def analyze(self, ticker: str) -> dict[str, Any]:
        bundle = self.fetch(ticker)
        sentiment = self.sentiment_analyzer.analyze(bundle)
        profile = self.taxonomy_service.get_ticker_profile(ticker)
        return {
            "bundle": bundle,
            "sentiment": sentiment,
            "profile": profile,
        }

    def analyze_subject(self, subject_key: str, subject_label: str, queries: list[str], *, scope_tag: str) -> dict[str, Any]:
        bundle = SignalBundle(ticker=subject_key)
        if not self.providers:
            bundle.feed_errors.append("social: no providers configured")
            sentiment = self.sentiment_analyzer.analyze(bundle)
            return {"bundle": bundle, "sentiment": sentiment, "profile": {"subject_label": subject_label}}
        for provider in self.providers:
            try:
                provider_bundle = provider.fetch_subject(subject_key, queries, scope_tag=scope_tag)
            except Exception as exc:  # noqa: BLE001
                bundle.feed_errors.append(f"{provider.name}: {exc}")
                continue
            bundle.items.extend(provider_bundle.items)
            bundle.feeds_used.extend(provider_bundle.feeds_used)
            bundle.feed_errors.extend(provider_bundle.feed_errors)
            bundle.coverage.update(provider_bundle.coverage)
            bundle.query_diagnostics.update(provider_bundle.query_diagnostics)
        bundle.feeds_used = list(dict.fromkeys(bundle.feeds_used))
        bundle.feed_errors = list(dict.fromkeys(bundle.feed_errors))
        sentiment = self.sentiment_analyzer.analyze(bundle)
        return {
            "bundle": bundle,
            "sentiment": sentiment,
            "profile": {"subject_label": subject_label, "scope_tag": scope_tag},
        }


def _parse_float(value: str | None, default: float) -> float:
    try:
        return float((value or "").strip())
    except (TypeError, ValueError):
        return default


def _parse_int(value: str | None, default: int) -> int:
    try:
        return int((value or "").strip())
    except (TypeError, ValueError):
        return default
