from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import (
    BrokerOrderExecutionRecord,
    HistoricalMarketBarRecord,
    HistoricalNewsRecord,
    WatchlistRecord,
)


BROKER_REJECT_STATUSES = {"failed", "rejected", "canceled", "expired"}


@dataclass(slots=True)
class TickerQualityAuditItem:
    ticker: str
    watchlists: list[str] = field(default_factory=list)
    bar_count: int = 0
    latest_bar_at: datetime | None = None
    news_count: int = 0
    latest_news_at: datetime | None = None
    broker_reject_count: int = 0
    latest_broker_reject_at: datetime | None = None
    latest_broker_reject_message: str = ""
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "watchlists": self.watchlists,
            "bar_count": self.bar_count,
            "latest_bar_at": self.latest_bar_at.isoformat() if self.latest_bar_at else None,
            "news_count": self.news_count,
            "latest_news_at": self.latest_news_at.isoformat() if self.latest_news_at else None,
            "broker_reject_count": self.broker_reject_count,
            "latest_broker_reject_at": self.latest_broker_reject_at.isoformat() if self.latest_broker_reject_at else None,
            "latest_broker_reject_message": self.latest_broker_reject_message,
            "issues": self.issues,
        }


class DataQualityAuditService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def summarize(
        self,
        *,
        watchlist_id: int | None = None,
        ticker: str | None = None,
        limit: int = 200,
        stale_after_days: int = 14,
        now: datetime | None = None,
    ) -> dict[str, object]:
        reference_now = now or datetime.now(timezone.utc)
        stale_cutoff = reference_now - timedelta(days=max(1, stale_after_days))
        watchlist_tickers = self._watchlist_tickers(watchlist_id=watchlist_id, ticker=ticker)
        tickers = sorted(watchlist_tickers)
        bar_stats = self._bar_stats(tickers)
        news_stats = self._news_stats(tickers)
        broker_stats = self._broker_reject_stats(tickers)

        items: list[TickerQualityAuditItem] = []
        issue_counts: dict[str, int] = {}
        for symbol in tickers:
            bar_count, latest_bar_at = bar_stats.get(symbol, (0, None))
            news_count, latest_news_at = news_stats.get(symbol, (0, None))
            reject_count, latest_reject_at, latest_message = broker_stats.get(symbol, (0, None, ""))
            issues: list[str] = []
            if bar_count <= 0:
                issues.append("no_bars")
            elif latest_bar_at is not None and self._normalize_datetime(latest_bar_at) < stale_cutoff:
                issues.append("stale_bars")
            if news_count <= 0:
                issues.append("no_news")
            elif latest_news_at is not None and self._normalize_datetime(latest_news_at) < stale_cutoff:
                issues.append("stale_news")
            if reject_count > 0:
                issues.append("broker_rejected")
            if not issues:
                continue
            for issue in issues:
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
            items.append(
                TickerQualityAuditItem(
                    ticker=symbol,
                    watchlists=watchlist_tickers.get(symbol, []),
                    bar_count=bar_count,
                    latest_bar_at=latest_bar_at,
                    news_count=news_count,
                    latest_news_at=latest_news_at,
                    broker_reject_count=reject_count,
                    latest_broker_reject_at=latest_reject_at,
                    latest_broker_reject_message=latest_message,
                    issues=issues,
                )
            )

        items.sort(key=lambda item: (-len(item.issues), item.ticker))
        clipped = items[: max(1, limit)]
        return {
            "generated_at": reference_now.isoformat(),
            "watchlist_id": watchlist_id,
            "ticker": ticker.strip().upper() if ticker else None,
            "stale_after_days": stale_after_days,
            "ticker_count": len(tickers),
            "issue_ticker_count": len(items),
            "issue_counts": issue_counts,
            "items": [item.to_dict() for item in clipped],
        }

    def _watchlist_tickers(self, *, watchlist_id: int | None, ticker: str | None) -> dict[str, list[str]]:
        query = select(WatchlistRecord)
        if watchlist_id is not None:
            query = query.where(WatchlistRecord.id == watchlist_id)
        rows = list(self.session.scalars(query).all())
        requested = ticker.strip().upper() if ticker else None
        result: dict[str, list[str]] = {}
        for row in rows:
            for raw_symbol in (row.tickers_csv or "").split(","):
                symbol = raw_symbol.strip().upper()
                if not symbol or (requested and symbol != requested):
                    continue
                result.setdefault(symbol, []).append(row.name)
        if requested and requested not in result:
            result[requested] = []
        return result

    def _bar_stats(self, tickers: list[str]) -> dict[str, tuple[int, datetime | None]]:
        if not tickers:
            return {}
        rows = self.session.execute(
            select(
                HistoricalMarketBarRecord.ticker,
                func.count(HistoricalMarketBarRecord.id),
                func.max(HistoricalMarketBarRecord.bar_time),
            )
            .where(HistoricalMarketBarRecord.ticker.in_(tickers))
            .group_by(HistoricalMarketBarRecord.ticker)
        ).all()
        return {str(ticker).upper(): (int(count or 0), latest) for ticker, count, latest in rows}

    def _news_stats(self, tickers: list[str]) -> dict[str, tuple[int, datetime | None]]:
        if not tickers:
            return {}
        rows = self.session.execute(
            select(
                HistoricalNewsRecord.ticker,
                func.count(HistoricalNewsRecord.id),
                func.max(HistoricalNewsRecord.published_at),
            )
            .where(HistoricalNewsRecord.ticker.in_(tickers))
            .group_by(HistoricalNewsRecord.ticker)
        ).all()
        return {str(ticker).upper(): (int(count or 0), latest) for ticker, count, latest in rows}

    def _broker_reject_stats(self, tickers: list[str]) -> dict[str, tuple[int, datetime | None, str]]:
        if not tickers:
            return {}
        rows = list(
            self.session.scalars(
                select(BrokerOrderExecutionRecord)
                .where(BrokerOrderExecutionRecord.ticker.in_(tickers))
                .where(BrokerOrderExecutionRecord.status.in_(BROKER_REJECT_STATUSES))
                .order_by(BrokerOrderExecutionRecord.updated_at.desc())
            ).all()
        )
        result: dict[str, tuple[int, datetime | None, str]] = {}
        counts: dict[str, int] = {}
        for row in rows:
            symbol = row.ticker.upper()
            counts[symbol] = counts.get(symbol, 0) + 1
            if symbol not in result:
                result[symbol] = (0, row.updated_at, row.error_message or "")
        for symbol, count in counts.items():
            _, latest_at, message = result[symbol]
            result[symbol] = (count, latest_at, message)
        return result

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
