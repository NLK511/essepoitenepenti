from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from statistics import pstdev
from typing import ClassVar, Iterable, Literal
from urllib.parse import urlparse

import httpx
import yfinance as yf

from trade_proposer_app.domain.models import NewsArticle, NewsBundle, ProviderCredential
from trade_proposer_app.repositories.historical_news import HistoricalNewsRepository
from trade_proposer_app.services.constants import DEFAULT_CONTEXT_FLAGS

MAX_ARTICLES_PER_PROVIDER = 10
NEWS_SUMMARY_ARTICLE_LIMIT = 3
SUMMARY_METHOD_NEWS_DIGEST = "news_digest"

NEWS_API_BASE_URL = "https://newsapi.org/v2/everything"
FINNHUB_NEWS_URL = "https://finnhub.io/api/v1/company-news"
DISABLED_PROVIDER_KEYS = {"newsapi"}

HIGH_QUALITY_NEWS_DOMAINS = [
    "bloomberg.com", "reuters.com", "wsj.com", "ft.com", "cnbc.com",
    "barrons.com", "marketwatch.com", "nikkei.com", "scmp.com",
    "spglobal.com", "thefly.com", "apnews.com", "bbc.com",
    "nytimes.com", "washingtonpost.com", "aljazeera.com",
    "techcrunch.com", "theinformation.com", "arstechnica.com",
    "digitimes.com", "theregister.com", "statnews.com",
    "fiercepharma.com", "fiercebiotech.com", "biopharmadive.com",
    "endpointsnews.com", "freightwaves.com", "supplychaindive.com",
    "oilprice.com", "utilitydive.com", "automotivenews.com",
]

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

TITLE_KEYWORD_WEIGHT = 1.7
SUMMARY_KEYWORD_WEIGHT = 1.2
ARTICLE_SCORE_SMOOTHING = 0.25

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
    "momentum": 1.0,
    "accelerate": 1.1,
    "accelerates": 1.1,
    "accelerated": 1.1,
    "bullish": 1.2,
    "rally": 1.1,
    "soar": 1.2,
    "soars": 1.2,
    "surpass": 1.2,
    "surpasses": 1.2,
    "surpassed": 1.2,
    "exceed": 1.2,
    "exceeds": 1.2,
    "exceeded": 1.2,
    "resilient": 1.1,
    "resilience": 1.1,
    "robust": 1.1,
    "guidance": 1.0,
    "outlook": 1.0,
    "innovation": 1.0,
    "innovations": 1.0,
    "demand": 0.9,
    "tailwind": 0.9,
    "tailwinds": 0.9,
    "win": 0.9,
    "wins": 0.9,
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
    "delay": 1.2,
    "delays": 1.2,
    "delayed": 1.2,
    "slowdown": 1.2,
    "slowdowns": 1.2,
    "shortfall": 1.3,
    "shortfalls": 1.3,
    "shortage": 1.2,
    "shortages": 1.2,
    "uncertain": 1.1,
    "uncertainty": 1.2,
    "drag": 1.0,
    "drags": 1.0,
    "dragging": 1.0,
    "struggle": 1.0,
    "struggles": 1.0,
    "struggled": 1.0,
    "slump": 1.2,
    "slumps": 1.2,
    "slumping": 1.2,
    "trouble": 1.0,
    "troubles": 1.0,
    "downturn": 1.2,
    "downturns": 1.2,
}

POSITIVE_PHRASE_WEIGHTS: dict[str, float] = {
    "beats expectations": 1.4,
    "beats forecasts": 1.3,
    "exceeds expectations": 1.3,
    "strong guidance": 1.2,
    "upside surprise": 1.2,
    "outlook improves": 1.1,
    "record demand": 1.1,
    "guidance raised": 1.1,
}

NEGATIVE_PHRASE_WEIGHTS: dict[str, float] = {
    "misses guidance": 1.4,
    "misses expectations": 1.3,
    "fails to meet": 1.3,
    "downgrade outlook": 1.2,
    "cut guidance": 1.2,
    "weak demand": 1.1,
    "slows growth": 1.1,
    "margin pressure": 1.2,
    "downturn continues": 1.2,
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


def _first_non_empty(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _domain_from_url(raw_url: str | None) -> str:
    if not raw_url:
        return ""
    try:
        hostname = urlparse(raw_url).hostname or ""
    except ValueError:
        return ""
    return hostname.lower().lstrip("www.")


def _is_whitelisted_domain(raw_url: str | None) -> bool:
    hostname = _domain_from_url(raw_url)
    if not hostname:
        return False
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in HIGH_QUALITY_NEWS_DOMAINS)


def _tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    return re.findall(r"[a-z0-9]+", text.lower())

def _sum_keyword_weights(tokens: Iterable[str], weight_map: dict[str, float], boost: float) -> float:
    return sum(weight_map.get(token, 0.0) * boost for token in tokens)


def _count_keyword_matches(tokens: Iterable[str], weight_map: dict[str, float]) -> int:
    return sum(1 for token in tokens if token in weight_map)


def _phrase_score_and_hits(text: str, weight_map: dict[str, float]) -> tuple[float, int]:
    if not text:
        return 0.0, 0
    total_score = 0.0
    total_hits = 0
    for phrase, score in weight_map.items():
        pattern = rf"\b{re.escape(phrase)}\b"
        matches = len(re.findall(pattern, text))
        total_score += score * matches
        total_hits += matches
    return total_score, total_hits


class NewsFetchError(Exception):
    pass


NewsQueryType = Literal["ticker", "topic"]
NewsRequestMode = Literal["live", "replay"]


@dataclass
class NewsProvider:
    credential: ProviderCredential
    timeout: float = 10.0

    name: ClassVar[str] = "generic"
    provider_key: ClassVar[str] = ""
    supports_ticker: ClassVar[bool] = True
    supports_topic: ClassVar[bool] = True
    supports_live_windowed_queries: ClassVar[bool] = True
    supports_replay_windowed_queries: ClassVar[bool] = False
    counts_as_primary_news: ClassVar[bool] = True
    # Legacy compatibility flag. Capability-based routing is now the source of truth.
    historical_replay_safe: ClassVar[bool] = False

    def fetch(self, ticker: str, limit: int, *, start_at: datetime | None = None, end_at: datetime | None = None) -> list[NewsArticle]:
        raise NotImplementedError

    def fetch_topic(self, topic: str, limit: int, *, start_at: datetime | None = None, end_at: datetime | None = None) -> list[NewsArticle]:
        raise NewsFetchError(f"{self.name} does not support topic queries")


class NewsAPIProvider(NewsProvider):
    name: ClassVar[str] = "NewsAPI"
    provider_key: ClassVar[str] = "newsapi"
    supports_ticker: ClassVar[bool] = True
    supports_topic: ClassVar[bool] = True
    supports_live_windowed_queries: ClassVar[bool] = True
    supports_replay_windowed_queries: ClassVar[bool] = True
    counts_as_primary_news: ClassVar[bool] = True

    def fetch(self, ticker: str, limit: int, *, start_at: datetime | None = None, end_at: datetime | None = None) -> list[NewsArticle]:
        return self._fetch_query(f"{ticker} stock", limit, start_at=start_at, end_at=end_at)

    def fetch_topic(self, topic: str, limit: int, *, start_at: datetime | None = None, end_at: datetime | None = None) -> list[NewsArticle]:
        return self._fetch_query(topic, limit, start_at=start_at, end_at=end_at)

    def _fetch_query(self, query: str, limit: int, *, start_at: datetime | None = None, end_at: datetime | None = None) -> list[NewsArticle]:
        api_key = (self.credential.api_key or "").strip()
        if not api_key:
            raise NewsFetchError("missing NewsAPI api key")
        params = {
            "apiKey": api_key,
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": min(limit, MAX_ARTICLES_PER_PROVIDER),
            "page": 1,
            "domains": ",".join(HIGH_QUALITY_NEWS_DOMAINS),
        }
        if start_at:
            params["from"] = start_at.isoformat()
        if end_at:
            params["to"] = end_at.isoformat()
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
    supports_ticker: ClassVar[bool] = True
    supports_topic: ClassVar[bool] = False
    supports_live_windowed_queries: ClassVar[bool] = True
    supports_replay_windowed_queries: ClassVar[bool] = True
    counts_as_primary_news: ClassVar[bool] = True
    historical_replay_safe: ClassVar[bool] = True

    def fetch(self, ticker: str, limit: int, *, start_at: datetime | None = None, end_at: datetime | None = None) -> list[NewsArticle]:
        api_key = (self.credential.api_key or "").strip()
        if not api_key:
            raise NewsFetchError("missing Finnhub api key")
        
        # Default to last 7 days if no dates provided
        effective_end = end_at or datetime.now(timezone.utc)
        effective_start = start_at or (effective_end - timedelta(days=7))
        
        params = {
            "symbol": ticker,
            "from": effective_start.date().isoformat(),
            "to": effective_end.date().isoformat(),
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


class YahooFinanceProvider(NewsProvider):
    name: ClassVar[str] = "YahooFinance"
    provider_key: ClassVar[str] = "yahoofinance"
    supports_ticker: ClassVar[bool] = True
    supports_topic: ClassVar[bool] = False
    supports_live_windowed_queries: ClassVar[bool] = True
    supports_replay_windowed_queries: ClassVar[bool] = False
    counts_as_primary_news: ClassVar[bool] = False

    def fetch(self, ticker: str, limit: int, *, start_at: datetime | None = None, end_at: datetime | None = None) -> list[NewsArticle]:
        # yfinance news API doesn't support date ranges directly, but we can filter the results
        try:
            raw_news = yf.Ticker(ticker).news
        except Exception as exc:
            raise NewsFetchError(f"failed to fetch news for {ticker} from Yahoo Finance: {exc}") from exc

        if not isinstance(raw_news, list):
            raise NewsFetchError("unexpected response from Yahoo Finance")

        articles: list[NewsArticle] = []
        for entry in raw_news:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content") if isinstance(entry.get("content"), dict) else {}

            title = _cleanup_text(_first_non_empty(entry.get("title"), content.get("title")))
            summary = _cleanup_text(
                _first_non_empty(
                    entry.get("summary"),
                    entry.get("description"),
                    content.get("summary"),
                    content.get("description"),
                )
            )
            publisher = _cleanup_text(
                _first_non_empty(
                    entry.get("provider", {}).get("displayName") if isinstance(entry.get("provider"), dict) else None,
                    content.get("provider", {}).get("displayName") if isinstance(content.get("provider"), dict) else None,
                )
            )

            link_obj = entry.get("clickThroughUrl") or entry.get("canonicalUrl") or content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
            link = _cleanup_text(link_obj.get("url") if isinstance(link_obj, dict) else None)

            published = None
            for raw_date in (content.get("pubDate"), content.get("displayTime"), entry.get("pubDate"), entry.get("displayTime")):
                if not isinstance(raw_date, str):
                    continue
                try:
                    published = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    break
                except ValueError:
                    continue

            if not title and not summary:
                continue

            article = NewsArticle(
                title=title or summary,
                summary=summary,
                publisher=publisher or "Yahoo Finance",
                link=link,
                published_at=published,
            )

            if start_at and article.published_at and article.published_at < start_at:
                continue
            if end_at and article.published_at and article.published_at > end_at:
                continue

            articles.append(article)
        return articles[:limit]


class GoogleNewsProvider(NewsProvider):
    name: ClassVar[str] = "GoogleNews"
    provider_key: ClassVar[str] = "googlenews"
    supports_ticker: ClassVar[bool] = True
    supports_topic: ClassVar[bool] = True
    supports_live_windowed_queries: ClassVar[bool] = True
    supports_replay_windowed_queries: ClassVar[bool] = False
    counts_as_primary_news: ClassVar[bool] = True

    def fetch(self, ticker: str, limit: int, *, start_at: datetime | None = None, end_at: datetime | None = None) -> list[NewsArticle]:
        return self._fetch_query(f"{ticker} stock", limit, start_at=start_at, end_at=end_at)

    def fetch_topic(self, topic: str, limit: int, *, start_at: datetime | None = None, end_at: datetime | None = None) -> list[NewsArticle]:
        return self._fetch_query(topic, limit, start_at=start_at, end_at=end_at)

    def _fetch_query(self, query: str, limit: int, *, start_at: datetime | None = None, end_at: datetime | None = None) -> list[NewsArticle]:
        domain_filters = " OR ".join(f"site:{domain}" for domain in HIGH_QUALITY_NEWS_DOMAINS)
        if start_at and end_at:
            # use after:YYYY-MM-DD before:YYYY-MM-DD
            # We add one day to end_at to make the range inclusive of the end day
            effective_end = end_at + timedelta(days=1)
            date_filter = f"after:{start_at.date().isoformat()} before:{effective_end.date().isoformat()}"
        else:
            date_filter = "when:7d"
        
        full_query = f"{query} ({domain_filters}) {date_filter}"
        response = httpx.get(
            "https://news.google.com/rss/search",
            params={"q": full_query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            timeout=self.timeout,
            follow_redirects=True,
        )
        if response.status_code != 200:
            raise NewsFetchError(f"unexpected status {response.status_code} from Google News")

        try:
            root = ET.fromstring(response.text)
        except ET.ParseError as exc:
            raise NewsFetchError(f"failed to parse Google News XML: {exc}") from exc

        articles: list[NewsArticle] = []
        for item in root.findall(".//item"):
            title_elem = item.find("title")
            link_elem = item.find("link")
            pub_date_elem = item.find("pubDate")
            desc_elem = item.find("description")
            source_elem = item.find("source")

            source_url = source_elem.attrib.get("url") if source_elem is not None else None
            if source_url and not _is_whitelisted_domain(source_url):
                continue

            title = _cleanup_text(title_elem.text if title_elem is not None else None)
            link = _cleanup_text(link_elem.text if link_elem is not None else None)
            desc_raw = desc_elem.text if desc_elem is not None else ""
            summary = _cleanup_text(re.sub(r"<[^>]+>", "", desc_raw))

            publisher = "Google News"
            if source_elem is not None:
                publisher = _cleanup_text(source_elem.text or source_url or "") or "Google News"

            published = None
            if pub_date_elem is not None and pub_date_elem.text:
                try:
                    published = parsedate_to_datetime(pub_date_elem.text)
                except (TypeError, ValueError):
                    pass

            if not title:
                continue

            articles.append(
                NewsArticle(
                    title=title,
                    summary=summary,
                    publisher=publisher,
                    link=link,
                    published_at=published,
                )
            )
        return articles[:limit]


PROVIDER_BUILDERS[NewsAPIProvider.provider_key] = NewsAPIProvider
PROVIDER_BUILDERS[FinnhubProvider.provider_key] = FinnhubProvider
PROVIDER_BUILDERS[YahooFinanceProvider.provider_key] = YahooFinanceProvider
PROVIDER_BUILDERS[GoogleNewsProvider.provider_key] = GoogleNewsProvider


class NaiveSentimentAnalyzer:
    def analyze(self, bundle: NewsBundle) -> dict[str, object]:
        articles = bundle.articles
        contexts: set[str] = set()
        article_scores: list[float] = []
        positives = 0.0
        negatives = 0.0
        total_keyword_hits = 0

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
            article_keyword_hits = (
                _count_keyword_matches(title_tokens, POSITIVE_KEYWORD_WEIGHTS)
                + _count_keyword_matches(summary_tokens, POSITIVE_KEYWORD_WEIGHTS)
                + _count_keyword_matches(title_tokens, NEGATIVE_KEYWORD_WEIGHTS)
                + _count_keyword_matches(summary_tokens, NEGATIVE_KEYWORD_WEIGHTS)
            )
            phrase_positive, phrase_positive_hits = _phrase_score_and_hits(text, POSITIVE_PHRASE_WEIGHTS)
            phrase_negative, phrase_negative_hits = _phrase_score_and_hits(text, NEGATIVE_PHRASE_WEIGHTS)
            article_positive += phrase_positive
            article_negative += phrase_negative
            article_keyword_hits += phrase_positive_hits + phrase_negative_hits
            total_keyword_hits += article_keyword_hits
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
        coverage_insights: list[str] = []
        if not articles:
            coverage_insights.append("news: no articles fetched; providers may be missing or rate limited.")
        elif total_keyword_hits == 0:
            coverage_insights.append(
                "news: articles arrived but no sentiment keywords matched, so the score stays neutral per the signal integrity policy."
            )
        if bundle.feed_errors:
            coverage_insights.append(f"news: provider issues ({'; '.join(bundle.feed_errors)})")
        coverage_insights = list(dict.fromkeys(coverage_insights))

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
            "keyword_hits": total_keyword_hits,
            "coverage_insights": coverage_insights,
            "polarity_trend": polarity,
            "sentiment_volatility": volatility,
            "problems": bundle.feed_errors,
        }

class NewsIngestionService:
    def __init__(
        self,
        providers: Iterable[NewsProvider] | None = None,
        *,
        max_articles: int = 12,
        historical_news: HistoricalNewsRepository | None = None,
    ) -> None:
        self.providers = list(providers or [])
        self.max_articles = max_articles
        self.historical_news = historical_news
        self._sentiment_analyzer = NaiveSentimentAnalyzer()

    @classmethod
    def from_provider_credentials(
        cls,
        provider_credentials: dict[str, ProviderCredential],
        *,
        max_articles: int = 12,
        historical_news: HistoricalNewsRepository | None = None,
    ) -> "NewsIngestionService":
        providers: list[NewsProvider] = []

        finnhub_credential = provider_credentials.get(FinnhubProvider.provider_key)
        if finnhub_credential and (finnhub_credential.api_key or finnhub_credential.api_secret):
            providers.append(FinnhubProvider(finnhub_credential))

        # Always include the free, real-time providers for live/non-historical flows.
        providers.append(GoogleNewsProvider(credential=ProviderCredential(provider="googlenews")))
        providers.append(YahooFinanceProvider(credential=ProviderCredential(provider="yahoofinance")))

        for key, builder in PROVIDER_BUILDERS.items():
            if key in DISABLED_PROVIDER_KEYS or key in (
                GoogleNewsProvider.provider_key,
                YahooFinanceProvider.provider_key,
                FinnhubProvider.provider_key,
            ):
                continue
            credential = provider_credentials.get(key)
            if credential and (credential.api_key or credential.api_secret):
                providers.append(builder(credential))
        return cls(providers, max_articles=max_articles, historical_news=historical_news)

    def fetch(
        self,
        ticker: str,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        request_mode: NewsRequestMode = "live",
        primary_only: bool = False,
    ) -> NewsBundle:
        bundle = NewsBundle(ticker=ticker)

        # 1. Try local DB first if date range is provided
        if self.historical_news and (start_at or end_at):
            local_articles = self.historical_news.list_news(
                ticker=ticker,
                start_at=start_at,
                end_at=end_at,
                limit=self.max_articles,
            )
            if len(local_articles) >= 3:
                bundle.articles = local_articles
                bundle.feeds_used.append("database")
                return bundle

        providers, selection_errors = self._providers_for_request(
            query_type="ticker",
            request_mode=request_mode,
            primary_only=primary_only,
            start_at=start_at,
            end_at=end_at,
        )
        if not providers:
            bundle.feed_errors.extend(selection_errors)
            return bundle
        seen_links: set[str] = set()
        for provider in providers:
            try:
                articles = provider.fetch(ticker, self.max_articles, start_at=start_at, end_at=end_at)
            except Exception as exc:  # noqa: BLE001
                bundle.feed_errors.append(f"{provider.name}: {exc}")
                continue
            filtered_articles = self._filter_articles_for_window(articles, start_at=start_at, end_at=end_at)

            if self.historical_news and filtered_articles:
                try:
                    self.historical_news.save_news(ticker, provider.provider_key, filtered_articles)
                except Exception:
                    pass

            self._merge_articles(bundle, filtered_articles, seen_links)
            if filtered_articles:
                bundle.feeds_used.append(provider.name)
        bundle.articles = bundle.articles[: self.max_articles]
        bundle.feed_errors = list(dict.fromkeys(bundle.feed_errors))
        return bundle

    def fetch_topic(
        self,
        topic: str,
        *,
        limit: int | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        request_mode: NewsRequestMode = "live",
        primary_only: bool = False,
    ) -> NewsBundle:
        bundle = NewsBundle(ticker=topic)
        fetch_limit = min(limit or self.max_articles, self.max_articles)

        if self.historical_news and (start_at or end_at):
            local_articles = self.historical_news.list_news(
                ticker=topic,
                start_at=start_at,
                end_at=end_at,
                limit=fetch_limit,
            )
            if len(local_articles) >= 2:
                bundle.articles = local_articles
                bundle.feeds_used.append("database")
                return bundle

        providers, selection_errors = self._providers_for_request(
            query_type="topic",
            request_mode=request_mode,
            primary_only=primary_only,
            start_at=start_at,
            end_at=end_at,
        )
        if not providers:
            bundle.feed_errors.extend(selection_errors)
            return bundle
        seen_links: set[str] = set()
        for provider in providers:
            try:
                articles = provider.fetch_topic(topic, fetch_limit, start_at=start_at, end_at=end_at)
            except Exception as exc:  # noqa: BLE001
                bundle.feed_errors.append(f"{provider.name}: {exc}")
                continue
            filtered_articles = self._filter_articles_for_window(articles, start_at=start_at, end_at=end_at)

            if self.historical_news and filtered_articles:
                try:
                    self.historical_news.save_news(topic, provider.provider_key, filtered_articles)
                except Exception:
                    pass

            self._merge_articles(bundle, filtered_articles, seen_links)
            if filtered_articles:
                bundle.feeds_used.append(provider.name)
        bundle.articles = bundle.articles[:fetch_limit]
        bundle.feed_errors = list(dict.fromkeys(bundle.feed_errors))
        return bundle

    def fetch_topics(
        self,
        subject: str,
        queries: list[str],
        *,
        per_query_limit: int = 4,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        request_mode: NewsRequestMode = "live",
        primary_only: bool = False,
    ) -> NewsBundle:
        bundle = NewsBundle(ticker=subject)
        if not self.providers:
            bundle.feed_errors.append("news: no providers configured")
            return bundle
        seen_links: set[str] = set()
        normalized_queries = [query.strip() for query in queries if isinstance(query, str) and query.strip()]
        if not normalized_queries:
            normalized_queries = [subject]
        for query in normalized_queries[:5]:
            query_bundle = self.fetch_topic(
                query,
                limit=per_query_limit,
                start_at=start_at,
                end_at=end_at,
                request_mode=request_mode,
                primary_only=primary_only,
            )
            self._merge_articles(bundle, query_bundle.articles, seen_links)
            bundle.feeds_used.extend(query_bundle.feeds_used)
            bundle.feed_errors.extend(query_bundle.feed_errors)
            if len(bundle.articles) >= self.max_articles:
                break
        bundle.feeds_used = list(dict.fromkeys(bundle.feeds_used))
        bundle.feed_errors = list(dict.fromkeys(bundle.feed_errors))
        bundle.articles = bundle.articles[: self.max_articles]
        return bundle

    def fetch_many(
        self,
        symbols: list[str],
        *,
        per_symbol_limit: int = 3,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        request_mode: NewsRequestMode = "live",
        primary_only: bool = False,
    ) -> NewsBundle:
        subject = ", ".join(symbols[:4]) if symbols else "news"
        bundle = NewsBundle(ticker=subject)
        if not self.providers:
            bundle.feed_errors.append("news: no providers configured")
            return bundle
        seen_links: set[str] = set()
        normalized_symbols = [symbol.strip().upper() for symbol in symbols if isinstance(symbol, str) and symbol.strip()]
        for symbol in list(dict.fromkeys(normalized_symbols))[:6]:
            symbol_bundle = self.fetch(
                symbol,
                start_at=start_at,
                end_at=end_at,
                request_mode=request_mode,
                primary_only=primary_only,
            )
            self._merge_articles(bundle, symbol_bundle.articles[:per_symbol_limit], seen_links)
            bundle.feeds_used.extend(symbol_bundle.feeds_used)
            bundle.feed_errors.extend(symbol_bundle.feed_errors)
            if len(bundle.articles) >= self.max_articles:
                break
        bundle.feeds_used = list(dict.fromkeys(bundle.feeds_used))
        bundle.feed_errors = list(dict.fromkeys(bundle.feed_errors))
        bundle.articles = bundle.articles[: self.max_articles]
        return bundle

    def analyze(
        self,
        ticker: str,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        request_mode: NewsRequestMode = "live",
        primary_only: bool = False,
    ) -> dict[str, object]:
        bundle = self.fetch(
            ticker,
            start_at=start_at,
            end_at=end_at,
            request_mode=request_mode,
            primary_only=primary_only,
        )
        sentiment = self._sentiment_analyzer.analyze(bundle)
        return {"bundle": bundle, "sentiment": sentiment}

    def analyze_bundle(self, bundle: NewsBundle) -> dict[str, object]:
        return {"bundle": bundle, "sentiment": self._sentiment_analyzer.analyze(bundle)}

    def _providers_for_request(
        self,
        *,
        query_type: NewsQueryType,
        request_mode: NewsRequestMode,
        primary_only: bool,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> tuple[list[NewsProvider], list[str]]:
        if not self.providers:
            return [], ["news: no providers configured"]
        windowed = bool(start_at or end_at)
        selected: list[NewsProvider] = []
        exclusions: list[str] = []
        for provider in self.providers:
            reason = self._provider_exclusion_reason(
                provider,
                query_type=query_type,
                request_mode=request_mode,
                primary_only=primary_only,
                windowed=windowed,
            )
            if reason is None:
                selected.append(provider)
            else:
                exclusions.append(f"{provider.name}({reason})")
        if selected:
            return selected, []
        details = [
            (
                f"news: no providers eligible for query_type={query_type} "
                f"mode={request_mode} windowed={'true' if windowed else 'false'} "
                f"primary_only={'true' if primary_only else 'false'}"
            )
        ]
        if exclusions:
            details.append(f"news: provider exclusions: {', '.join(exclusions)}")
        return [], details

    @staticmethod
    def _provider_exclusion_reason(
        provider: NewsProvider,
        *,
        query_type: NewsQueryType,
        request_mode: NewsRequestMode,
        primary_only: bool,
        windowed: bool,
    ) -> str | None:
        if query_type == "ticker" and not getattr(provider, "supports_ticker", True):
            return "ticker unsupported"
        if query_type == "topic" and not getattr(provider, "supports_topic", True):
            return "topic unsupported"
        if primary_only and not getattr(provider, "counts_as_primary_news", True):
            return "not primary news"
        if not windowed:
            return None
        if request_mode == "live" and not getattr(provider, "supports_live_windowed_queries", True):
            return "live window unsupported"
        if request_mode == "replay" and not getattr(provider, "supports_replay_windowed_queries", False):
            return "replay window unsupported"
        return None

    @staticmethod
    def _filter_articles_for_window(
        articles: list[NewsArticle],
        *,
        start_at: datetime | None,
        end_at: datetime | None,
    ) -> list[NewsArticle]:
        require_timestamp = bool(start_at or end_at)
        filtered: list[NewsArticle] = []
        for article in articles:
            published_at = article.published_at
            if require_timestamp and published_at is None:
                continue
            if published_at is not None and published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)
            if start_at and published_at and published_at < start_at:
                continue
            if end_at and published_at and published_at > end_at:
                continue
            filtered.append(article)
        return filtered

    @staticmethod
    def _merge_articles(bundle: NewsBundle, articles: list[NewsArticle], seen_links: set[str]) -> None:
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
