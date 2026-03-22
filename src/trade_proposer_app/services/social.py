from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from typing import ClassVar
from urllib.parse import quote, urljoin

import httpx

from trade_proposer_app.domain.models import SignalBundle, SignalEngagement, SignalItem

NITTER_SEARCH_PATH = "/search"
TIMELINE_ITEM_PATTERN = re.compile(r'<div class="timeline-item(?P<body>.*?)<div class="timeline-footer">', re.DOTALL)
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


class NitterProvider(SocialProvider):
    name: ClassVar[str] = "Nitter"

    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 6.0,
        max_items_per_query: int = 12,
        query_window_hours: int = 12,
        include_replies: bool = False,
    ) -> None:
        super().__init__(timeout=timeout)
        self.base_url = base_url.rstrip("/")
        self.max_items_per_query = max(1, max_items_per_query)
        self.query_window_hours = max(1, query_window_hours)
        self.include_replies = include_replies

    def fetch(self, ticker: str) -> SignalBundle:
        query = f'"${ticker}" OR "{ticker}"'
        url = f"{self.base_url}{NITTER_SEARCH_PATH}?f=tweets&q={quote(query)}"
        try:
            response = httpx.get(url, timeout=self.timeout, follow_redirects=True)
        except Exception as exc:  # noqa: BLE001
            raise SocialFetchError(f"request failed: {exc}") from exc
        if response.status_code != 200:
            raise SocialFetchError(f"unexpected status {response.status_code}")
        items = self._parse_search_html(response.text)
        return SignalBundle(
            ticker=ticker,
            items=items[: self.max_items_per_query],
            feeds_used=[self.name] if items else [],
            feed_errors=[],
            coverage={
                "social_count": len(items[: self.max_items_per_query]),
                "query_window_hours": self.query_window_hours,
            },
            query_diagnostics={
                "ticker_queries": [query],
                "base_url": self.base_url,
                "include_replies": self.include_replies,
            },
        )

    def _parse_search_html(self, html: str) -> list[SignalItem]:
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
                    matched_entities={"ticker": []},
                    scope_tags=["ticker"],
                    quality_score=0.5,
                    credibility_score=0.4,
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


class SocialIngestionService:
    def __init__(self, providers: list[SocialProvider] | None = None) -> None:
        self.providers = list(providers or [])

    @classmethod
    def from_settings(cls, social_settings: dict[str, str] | None = None) -> "SocialIngestionService":
        values = social_settings or {}
        enabled = (values.get("social_sentiment_enabled") or "false").strip().lower() == "true"
        nitter_enabled = (values.get("social_nitter_enabled") or "false").strip().lower() == "true"
        if not enabled or not nitter_enabled:
            return cls([])
        provider = NitterProvider(
            base_url=(values.get("social_nitter_base_url") or "http://127.0.0.1:8080").strip(),
            timeout=_parse_float(values.get("social_nitter_timeout_seconds"), 6.0),
            max_items_per_query=_parse_int(values.get("social_nitter_max_items_per_query"), 12),
            query_window_hours=_parse_int(values.get("social_nitter_query_window_hours"), 12),
            include_replies=(values.get("social_nitter_include_replies") or "false").strip().lower() == "true",
        )
        return cls([provider])

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
