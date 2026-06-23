import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Iterable

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import NewsArticle
from trade_proposer_app.persistence.models import HistoricalNewsRecord


MAX_STORED_LINK_LENGTH = 512
LINK_HASH_SUFFIX_LENGTH = 74  # "__sha256__" + 64 hex chars


class HistoricalNewsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._supports_available_at: bool | None = None
        self._supports_availability_metadata: bool | None = None

    def list_news(
        self,
        ticker: str,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        available_at: datetime | None = None,
        limit: int = 50,
    ) -> list[NewsArticle]:
        query = select(HistoricalNewsRecord).where(HistoricalNewsRecord.ticker == ticker)
        if start_at:
            query = query.where(HistoricalNewsRecord.published_at >= self._normalize_datetime(start_at))
        if end_at:
            query = query.where(HistoricalNewsRecord.published_at <= self._normalize_datetime(end_at))
        if available_at and self._has_available_at_column():
            normalized_available_at = self._normalize_datetime(available_at)
            query = query.where(HistoricalNewsRecord.available_at <= normalized_available_at)
        
        query = query.order_by(HistoricalNewsRecord.published_at.desc()).limit(limit)
        
        records = self.session.scalars(query).all()
        return [self._to_article(record) for record in records]

    def count_news(
        self,
        ticker: str,
        *,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        available_at: datetime | None = None,
    ) -> int:
        query = select(func.count()).select_from(HistoricalNewsRecord).where(HistoricalNewsRecord.ticker == ticker)
        if start_at:
            query = query.where(HistoricalNewsRecord.published_at >= self._normalize_datetime(start_at))
        if end_at:
            query = query.where(HistoricalNewsRecord.published_at <= self._normalize_datetime(end_at))
        if available_at and self._has_available_at_column():
            query = query.where(HistoricalNewsRecord.available_at <= self._normalize_datetime(available_at))
        return int(self.session.scalar(query) or 0)

    def save_news(self, ticker: str, provider: str, articles: Iterable[NewsArticle]) -> None:
        try:
            for article in articles:
                stored_link = self._normalize_link_for_storage(article.link)

                # Check if exists
                exists_query = select(HistoricalNewsRecord).where(
                    HistoricalNewsRecord.ticker == ticker,
                    HistoricalNewsRecord.link == stored_link,
                    HistoricalNewsRecord.published_at == self._normalize_datetime(article.published_at),
                )
                if self.session.scalar(exists_query):
                    continue

                published_at = self._normalize_datetime(article.published_at) or datetime.now(timezone.utc)
                explicit_available_at = self._normalize_datetime(article.available_at)
                available_at = explicit_available_at or published_at
                availability_metadata = dict(article.availability_metadata or {})
                if explicit_available_at is None:
                    availability_metadata.setdefault("available_at_inferred_from", "published_at")
                    availability_metadata.setdefault("point_in_time_confidence", 0.6)
                else:
                    availability_metadata.setdefault("available_at_inferred_from", "provider")
                    availability_metadata.setdefault("point_in_time_confidence", 1.0)

                values = {
                    "ticker": ticker,
                    "published_at": published_at,
                    "title": article.title or "",
                    "summary": article.summary or "",
                    "link": stored_link,
                    "publisher": article.publisher or "",
                    "provider": provider,
                }
                if self._has_available_at_column():
                    values["available_at"] = available_at
                if self._has_availability_metadata_column():
                    values["availability_metadata_json"] = json.dumps(availability_metadata, sort_keys=True)
                record = HistoricalNewsRecord(**values)
                self.session.add(record)

            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def _to_article(self, record: HistoricalNewsRecord) -> NewsArticle:
        metadata: dict[str, object] = {}
        if self._has_availability_metadata_column():
            try:
                loaded = json.loads(record.availability_metadata_json or "{}")
                if isinstance(loaded, dict):
                    metadata = loaded
            except json.JSONDecodeError:
                metadata = {"decode_error": "invalid availability metadata json"}
        available_at = record.available_at if self._has_available_at_column() else record.published_at
        return NewsArticle(
            title=record.title,
            summary=record.summary,
            publisher=record.publisher,
            link=record.link,
            published_at=self._normalize_datetime(record.published_at),
            available_at=self._normalize_datetime(available_at),
            availability_metadata=metadata,
        )

    @staticmethod
    def _normalize_link_for_storage(link: str | None) -> str:
        if not link:
            return ""
        normalized = link.strip()
        if len(normalized) <= MAX_STORED_LINK_LENGTH:
            return normalized
        digest = sha256(normalized.encode("utf-8")).hexdigest()
        prefix_length = MAX_STORED_LINK_LENGTH - LINK_HASH_SUFFIX_LENGTH
        return f"{normalized[:prefix_length]}__sha256__{digest}"

    def _has_available_at_column(self) -> bool:
        if self._supports_available_at is not None:
            return self._supports_available_at
        self._supports_available_at = self._has_column("available_at")
        return self._supports_available_at

    def _has_availability_metadata_column(self) -> bool:
        if self._supports_availability_metadata is not None:
            return self._supports_availability_metadata
        self._supports_availability_metadata = self._has_column("availability_metadata_json")
        return self._supports_availability_metadata

    def _has_column(self, name: str) -> bool:
        bind = self.session.get_bind()
        if bind is None:
            return True
        try:
            columns = inspect(bind).get_columns(HistoricalNewsRecord.__tablename__)
            return any(column.get("name") == name for column in columns)
        except Exception:  # pragma: no cover - schema inspection fallback
            return True

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
