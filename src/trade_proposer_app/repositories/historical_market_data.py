from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.persistence.models import HistoricalMarketBarRecord


class HistoricalMarketDataRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_bar(self, bar: HistoricalMarketBar) -> HistoricalMarketBar:
        record = self.session.scalars(
            select(HistoricalMarketBarRecord)
            .where(HistoricalMarketBarRecord.ticker == bar.ticker)
            .where(HistoricalMarketBarRecord.timeframe == bar.timeframe)
            .where(HistoricalMarketBarRecord.bar_time == self._normalize(bar.bar_time))
            .limit(1)
        ).first()
        if record is None:
            record = HistoricalMarketBarRecord(
                ticker=bar.ticker,
                timeframe=bar.timeframe,
                bar_time=self._normalize(bar.bar_time),
            )
            self.session.add(record)
        record.available_at = self._normalize(bar.available_at) if bar.available_at else self._normalize(bar.bar_time)
        record.open_price = bar.open_price
        record.high_price = bar.high_price
        record.low_price = bar.low_price
        record.close_price = bar.close_price
        record.volume = bar.volume
        record.adjusted_close = bar.adjusted_close
        record.source = bar.source
        record.source_tier = bar.source_tier
        record.point_in_time_confidence = bar.point_in_time_confidence
        record.metadata_json = bar.metadata_json
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def list_bars(
        self,
        *,
        ticker: str,
        timeframe: str = "1d",
        end_at: datetime | None = None,
        available_at: datetime | None = None,
        limit: int = 200,
    ) -> list[HistoricalMarketBar]:
        query = (
            select(HistoricalMarketBarRecord)
            .where(HistoricalMarketBarRecord.ticker == ticker)
            .where(HistoricalMarketBarRecord.timeframe == timeframe)
            .order_by(HistoricalMarketBarRecord.bar_time.desc())
            .limit(limit)
        )
        if end_at is not None:
            query = query.where(HistoricalMarketBarRecord.bar_time <= self._normalize(end_at))
        if available_at is not None:
            query = query.where(HistoricalMarketBarRecord.available_at <= self._normalize(available_at))
        rows = self.session.scalars(query).all()
        return [self._to_model(row) for row in reversed(rows)]

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @classmethod
    def _to_model(cls, record: HistoricalMarketBarRecord) -> HistoricalMarketBar:
        return HistoricalMarketBar(
            id=record.id,
            ticker=record.ticker,
            timeframe=record.timeframe,
            bar_time=cls._normalize(record.bar_time),
            available_at=cls._normalize(record.available_at) if record.available_at else cls._normalize(record.bar_time),
            open_price=record.open_price,
            high_price=record.high_price,
            low_price=record.low_price,
            close_price=record.close_price,
            volume=record.volume,
            adjusted_close=record.adjusted_close,
            source=record.source,
            source_tier=record.source_tier,
            point_in_time_confidence=record.point_in_time_confidence,
            metadata_json=record.metadata_json or "{}",
            created_at=cls._normalize(record.created_at),
            updated_at=cls._normalize(record.updated_at),
        )


HistoricalMarketDataRepository = HistoricalMarketDataRepository
