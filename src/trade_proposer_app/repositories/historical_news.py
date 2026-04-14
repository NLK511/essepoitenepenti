from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import NewsArticle
from trade_proposer_app.persistence.models import HistoricalNewsRecord


class HistoricalNewsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_news(
        self,
        ticker: str,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        limit: int = 50,
    ) -> list[NewsArticle]:
        query = select(HistoricalNewsRecord).where(HistoricalNewsRecord.ticker == ticker)
        if start_at:
            query = query.where(HistoricalNewsRecord.published_at >= self._normalize_datetime(start_at))
        if end_at:
            query = query.where(HistoricalNewsRecord.published_at <= self._normalize_datetime(end_at))
        
        query = query.order_by(HistoricalNewsRecord.published_at.desc()).limit(limit)
        
        records = self.session.scalars(query).all()
        return [
            NewsArticle(
                title=r.title,
                summary=r.summary,
                publisher=r.publisher,
                link=r.link,
                published_at=self._normalize_datetime(r.published_at),
            )
            for r in records
        ]

    def save_news(self, ticker: str, provider: str, articles: Iterable[NewsArticle]) -> None:
        try:
            for article in articles:
                # Check if exists
                exists_query = select(HistoricalNewsRecord).where(
                    HistoricalNewsRecord.ticker == ticker,
                    HistoricalNewsRecord.link == (article.link or ""),
                    HistoricalNewsRecord.published_at == self._normalize_datetime(article.published_at),
                )
                if self.session.scalar(exists_query):
                    continue

                record = HistoricalNewsRecord(
                    ticker=ticker,
                    published_at=self._normalize_datetime(article.published_at) or datetime.now(timezone.utc),
                    title=article.title or "",
                    summary=article.summary or "",
                    link=article.link or "",
                    publisher=article.publisher or "",
                    provider=provider,
                )
                self.session.add(record)

            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
