from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import pstdev
from typing import ClassVar, Iterable

import httpx

from trade_proposer_app.domain.models import NewsArticle, NewsBundle, ProviderCredential
from trade_proposer_app.services.constants import DEFAULT_CONTEXT_FLAGS

MAX_ARTICLES_PER_PROVIDER = 10
NEWS_SUMMARY_ARTICLE_LIMIT = 3
SUMMARY_METHOD_NEWS_DIGEST = "news_digest"

NEWS_API_BASE_URL = "https://newsapi.org/v2/everything"
FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"

CONTINUOUS_CONTEXT_KEYWORDS: dict[str, str] = {
    "earnings": "context_tag_earnings",
    "financial": "context_tag_earnings",
    "release": "context_tag_earnings",
    "geopolitic": "context_tag_geopolitical",
    "conflict": "context_tag_geopolitical",
    "war": "context_tag_geopolitical",
    "merger": "context_tag_industry",
    "regulator": "context_tag_industry",
    "industry": "context_tag_industry",
    "general": "context_tag_general",
}

TITLE_KEYWORD_WEIGHT = 1.5
SUMMARY_KEYWORD_WEIGHT = 1.0
ARTICLE_SCORE_SMOOTHING = 0.5

POSITIVE_KEYWORD_WEIGHTS: dict[str, float] = {
    "beat": 1.3,
    "beats": 1.3,
    "outperform": 1.2,
    "outperforms": 1.2,
    "upgrade": 1.2,
    "upgrades": 1.2,
    "upgraded": 1.2,
    "growth": 1.1,
    "growing": 1.1,
    "surge": 1.3,
    "surges": 1.3,
    "rise": 1.1,
    "rises": 1.1,
    "strong": 1.0,
    "stronger": 1.0,
    "record": 1.2,
    "records": 1.2,
    "expansion": 1.1,
    "expand": 1.1,
    "expands": 1.1,
    "improve": 1.1,
    "improves": 1.1,
    "optimistic": 1.0,
    "positive": 1.0,
    "gain": 1.1,
    "gains": 1.1,
    "momentum": 0.9,
    "accelerate": 1.1,
    "accelerates": 1.1,
    "accelerated": 1.1,
    "bullish": 1.2,
    "rally": 1.1,
    "soar": 1.2,
    "soars": 1.2,
}

NEGATIVE_KEYWORD_WEIGHTS: dict[str, float] = {
    "miss": 1.3,
    "misses": 1.3,
    "missed": 1.3,
    "downgrade": 1.2,
    "downgrades": 1.2,
    "cut": 1.0,
    "cuts": 1.0,
    "decline": 1.2,
    "declines": 1.2,
    "drop": 1.1,
    "drops": 1.1,
    "fall": 1.1,
    "falls": 1.1,
    "weak": 1.0,
    "weaker": 1.0,
    "loss": 1.1,
    "losses": 1.1,
    "risk": 0.9,
    "warning": 1.1,
    "warn": 1.1,
    "concern": 1.0,
    "headwind": 1.0,
    "headwinds": 1.0,
    "bearish": 1.2,
    "scandal": 1.1,
    "investigation": 1.1,
    "litigation": 1.0,
    "recession": 1.2,
    "fail": 1.1,
    "failed": 1.1,
    "failure": 1.1,
    "volatile": 1.0,
    "declining": 1.1,
    "concerns": 1.0,
}

PROVIDER_BUILDERS: dict[str, type["NewsProvider"]] = {}


def _normalize_timestamp(value: str | int | float | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _cleanup_text(value: str | None) -> str:
    if not value:
        return ""
    return value.strip()


def _tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    return re.findall(r"[a-z0-9]+", text.lower())


def _sum_keyword_weights(tokens: Iterable[str], weight_map: dict[str, float], boost: float) -> float:
    return sum(weight_map.get(token, 0.0) * boost for token in tokens)


class NewsFetchError(Exception):
    pass


@dataclass
class NewsProvider:
    credential: ProviderCredential
    timeout: float = 10.0

    name: ClassVar[str] = "generic"
    provider_key: ClassVar[str] = ""

    def fetch(self, ticker: str, limit: int) -> list[NewsArticle]:
        raise NotImplementedError


class NewsAPIProvider(NewsProvider):
    name: ClassVar[str] = "NewsAPI"
    provider_key: ClassVar[str] = "newsapi"

    def fetch(self, ticker: str, limit: int) -> list[NewsArticle]:
        api_key = (self.credential.api_key or "").strip()
        if not api_key:
            raise NewsFetchError("missing NewsAPI api key")
        params = {
            "apiKey": api_key,
            "q": f"{ticker} stock",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": min(limit, MAX_ARTICLES_PER_PROVIDER),
            "page": 1,
        }
        response = httpx.get(NEWS_API_BASE_URL, params=params, timeout=self.timeout)
        if response.status_code != 200:
            raise NewsFetchError(f"unexpected status {response.status_code}")
        payload = response.json()
        if payload.get("status") != "ok":
            raise NewsFetchError(payload.get("message", "invalid payload"))
        articles: list[NewsArticle] = []
        for entry in payload.get("articles", []):
            if not isinstance(entry, dict):
                continue
            published = _normalize_timestamp(entry.get("publishedAt"))
            articles.append(
                NewsArticle(
                    title=_cleanup_text(entry.get("title")),
                    summary=_cleanup_text(entry.get("description") or entry.get("content")),
                    publisher=_cleanup_text(entry.get("source", {}).get("name")),
                    link=_cleanup_text(entry.get("url")),
                    published_at=published,
                )
            )
        return articles[:limit]


class FinnhubProvider(NewsProvider):
    name: ClassVar[str] = "Finnhub"
    provider_key: ClassVar[str] = "finnhub"

    def fetch(self, ticker: str, limit: int) -> list[NewsArticle]:
        api_key = (self.credential.api_key or "").strip()
        if not api_key:
            raise NewsFetchError("missing Finnhub api key")
        today = date.today()
        start = today - timedelta(days=7)
        params = {
            "symbol": ticker,
            "from": start.isoformat(),
            "to": today.isoformat(),
            "token": api_key,
        }
        response = httpx.get(FINNHUB_NEWS_URL, params=params, timeout=self.timeout)
        if response.status_code != 200:
            raise NewsFetchError(f"unexpected status {response.status_code}")
        payload = response.json()
        if not isinstance(payload, list):
            raise NewsFetchError("unexpected response payload")
        articles: list[NewsArticle] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            published = _normalize_timestamp(entry.get("datetime"))
            articles.append(
                NewsArticle(
                    title=_cleanup_text(entry.get("headline")),
                    summary=_cleanup_text(entry.get("summary") or entry.get("source")),
                    publisher=_cleanup_text(entry.get("source")),
                    link=_cleanup_text(entry.get("url")),
                    published_at=published,
                )
            )
        return articles[:limit]


PROVIDER_BUILDERS[NewsAPIProvider.provider_key] = NewsAPIProvider
PROVIDER_BUILDERS[FinnhubProvider.provider_key] = FinnhubProvider


class NaiveSentimentAnalyzer:
    def analyze(self, bundle: NewsBundle) -> dict[str, object]:
        articles = bundle.articles
        contexts: set[str] = set()
        article_scores: list[float] = []
        positives = 0.0
        negatives = 0.0

        for article in articles:
            title_tokens = _tokenize(article.title)
            summary_tokens = _tokenize(article.summary)
            text = f"{article.title or ''} {article.summary or ''}".lower()
            article_positive = (
                _sum_keyword_weights(title_tokens, POSITIVE_KEYWORD_WEIGHTS, TITLE_KEYWORD_WEIGHT)
                + _sum_keyword_weights(summary_tokens, POSITIVE_KEYWORD_WEIGHTS, SUMMARY_KEYWORD_WEIGHT)
            )
            article_negative = (
                _sum_keyword_weights(title_tokens, NEGATIVE_KEYWORD_WEIGHTS, TITLE_KEYWORD_WEIGHT)
                + _sum_keyword_weights(summary_tokens, NEGATIVE_KEYWORD_WEIGHTS, SUMMARY_KEYWORD_WEIGHT)
            )
            positives += article_positive
            negatives += article_negative
            hits = article_positive + article_negative
            if hits == 0:
                article_score = 0.0
            else:
                article_score = (article_positive - article_negative) / (hits + ARTICLE_SCORE_SMOOTHING)
            article_score = max(-1.0, min(1.0, article_score))
            article_scores.append(article_score)
            for keyword, tag in CONTINUOUS_CONTEXT_KEYWORDS.items():
                if keyword in text:
                    contexts.add(tag)
        score = sum(article_scores) / len(article_scores) if article_scores else 0.0
        score = max(-1.0, min(1.0, score))
        label = "NEUTRAL"
        if score > 0.15:
            label = "POSITIVE"
        elif score < -0.15:
            label = "NEGATIVE"
        polarity = (positives - negatives) / max(positives + negatives, 1)
        volatility = pstdev(article_scores) if len(article_scores) > 1 else 0.0
        context_flags = dict(DEFAULT_CONTEXT_FLAGS)
        for context in contexts:
            if context in context_flags:
                context_flags[context] = 1.0
        news_items = [
            {
                "title": article.title or "",
                "summary": article.summary or "",
                "publisher": article.publisher or "",
                "link": article.link or "",
                "published_at": article.published_at.isoformat() if article.published_at else None,
                "compound": float(article_score) if isinstance(article_score, (int, float)) else 0.0,
            }
            for article, article_score in zip(articles, article_scores)
        ]
        return {
            "score": score,
            "label": label,
            "contexts": list(contexts),
            "context_flags": context_flags,
            "sources": bundle.feeds_used,
            "news_items": news_items,
            "news_points": news_items,
            "news_point_count": len(news_items),
            "polarity_trend": polarity,
            "sentiment_volatility": volatility,
            "problems": bundle.feed_errors,
        }


class NewsIngestionService:
    def __init__(self, providers: Iterable[NewsProvider] | None = None, *, max_articles: int = 12) -> None:
        self.providers = list(providers or [])
        self.max_articles = max_articles
        self._sentiment_analyzer = NaiveSentimentAnalyzer()

    @classmethod
    def from_provider_credentials(cls, provider_credentials: dict[str, ProviderCredential], *, max_articles: int = 12) -> "NewsIngestionService":
        providers: list[NewsProvider] = []
        for key, builder in PROVIDER_BUILDERS.items():
            credential = provider_credentials.get(key)
            if credential and (credential.api_key or credential.api_secret):
                providers.append(builder(credential))
        return cls(providers, max_articles=max_articles)

    def fetch(self, ticker: str) -> NewsBundle:
        bundle = NewsBundle(ticker=ticker)
        if not self.providers:
            bundle.feed_errors.append("news: no providers configured")
            return bundle
        seen_links: set[str] = set()
        for provider in self.providers:
            try:
                articles = provider.fetch(ticker, self.max_articles)
            except Exception as exc:  # noqa: BLE001
                bundle.feed_errors.append(f"{provider.name}: {exc}")
                continue
            unique_articles = []
            for article in articles:
                link = article.link or ""
                if link and link in seen_links:
                    continue
                if link:
                    seen_links.add(link)
                unique_articles.append(article)
            if unique_articles:
                bundle.articles.extend(unique_articles)
            bundle.feeds_used.append(provider.name)
        bundle.articles = bundle.articles[: self.max_articles]
        return bundle

    def analyze(self, ticker: str) -> dict[str, object]:
        bundle = self.fetch(ticker)
        sentiment = self._sentiment_analyzer.analyze(bundle)
        return {"bundle": bundle, "sentiment": sentiment}
