from datetime import datetime, time, timedelta, timezone

from sqlalchemy import inspect, insert, select, update
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.persistence.models import HistoricalMarketBarRecord


class HistoricalMarketDataRepository:
    def __init__(self, session: Session) -> None:
        self.session = session
        self._supports_available_at: bool | None = None

    def upsert_bars(self, bars: list[HistoricalMarketBar]) -> int:
        if not bars:
            return 0
        
        table = HistoricalMarketBarRecord.__table__
        has_available_at = self._has_available_at_column()
        
        records = []
        for bar in bars:
            normalized_bar_time = self._normalize(bar.bar_time)
            values = {
                "ticker": bar.ticker,
                "timeframe": bar.timeframe,
                "bar_time": normalized_bar_time,
                "open_price": bar.open_price,
                "high_price": bar.high_price,
                "low_price": bar.low_price,
                "close_price": bar.close_price,
                "volume": bar.volume,
                "adjusted_close": bar.adjusted_close,
                "source": bar.source,
                "source_tier": bar.source_tier,
                "point_in_time_confidence": bar.point_in_time_confidence,
                "metadata_json": bar.metadata_json,
            }
            if has_available_at:
                values["available_at"] = self._normalize(bar.available_at) if bar.available_at else normalized_bar_time
            records.append(values)

        dialect = self.session.bind.dialect.name if self.session.bind else "postgresql"
        
        if dialect == "postgresql":
            # For Postgres, use ON CONFLICT DO UPDATE
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            
            # Determine unique keys for ON CONFLICT
            index_elements = ["ticker", "timeframe", "bar_time"]
            
            stmt = pg_insert(HistoricalMarketBarRecord).values(records)
            update_cols = {
                col.name: stmt.excluded[col.name] 
                for col in HistoricalMarketBarRecord.__table__.columns 
                if col.name not in (index_elements + ["id", "created_at"])
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=index_elements,
                set_=update_cols
            )
            result = self.session.execute(stmt)
            self.session.commit()
            return result.rowcount
        else:
            # Fallback for SQLite or other dialects
            count = 0
            for record in records:
                self.session.execute(insert(table).values(**record).prefix_with("OR REPLACE"))
                count += 1
            self.session.commit()
            return count

    def upsert_bar(self, bar: HistoricalMarketBar) -> HistoricalMarketBar:
        table = HistoricalMarketBarRecord.__table__
        normalized_bar_time = self._normalize(bar.bar_time)
        values = {
            "ticker": bar.ticker,
            "timeframe": bar.timeframe,
            "bar_time": normalized_bar_time,
            "open_price": bar.open_price,
            "high_price": bar.high_price,
            "low_price": bar.low_price,
            "close_price": bar.close_price,
            "volume": bar.volume,
            "adjusted_close": bar.adjusted_close,
            "source": bar.source,
            "source_tier": bar.source_tier,
            "point_in_time_confidence": bar.point_in_time_confidence,
            "metadata_json": bar.metadata_json,
        }
        if self._has_available_at_column():
            values["available_at"] = self._normalize(bar.available_at) if bar.available_at else normalized_bar_time
        existing_id = self.session.execute(
            select(table.c.id)
            .where(table.c.ticker == bar.ticker)
            .where(table.c.timeframe == bar.timeframe)
            .where(table.c.bar_time == normalized_bar_time)
            .limit(1)
        ).scalar_one_or_none()
        if existing_id is None:
            self.session.execute(insert(table).values(**values))
        else:
            self.session.execute(update(table).where(table.c.id == existing_id).values(**values))
        self.session.commit()
        stored = self.session.execute(
            self._select_bar_rows(bar.ticker, bar.timeframe, normalized_bar_time, normalized_bar_time, values.get("available_at"), limit=1)
        ).mappings().first()
        if stored is None:
            return HistoricalMarketBar(
                ticker=bar.ticker,
                timeframe=bar.timeframe,
                bar_time=normalized_bar_time,
                available_at=values.get("available_at") or self._infer_available_at(normalized_bar_time, bar.timeframe),
                open_price=bar.open_price,
                high_price=bar.high_price,
                low_price=bar.low_price,
                close_price=bar.close_price,
                volume=bar.volume,
                adjusted_close=bar.adjusted_close,
                source=bar.source,
                source_tier=bar.source_tier,
                point_in_time_confidence=bar.point_in_time_confidence,
                metadata_json=bar.metadata_json,
            )
        return self._to_model_from_row(stored)

    def list_bars(
        self,
        *,
        ticker: str,
        timeframe: str = "1d",
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        available_at: datetime | None = None,
        limit: int = 200,
    ) -> list[HistoricalMarketBar]:
        rows = self.session.execute(
            self._select_bar_rows(ticker, timeframe, start_at, end_at, available_at, limit=limit)
        ).mappings().all()
        return [self._to_model_from_row(row) for row in reversed(rows)]

    def _select_bar_rows(
        self,
        ticker: str,
        timeframe: str,
        start_at: datetime | None,
        end_at: datetime | None,
        available_at: datetime | None,
        *,
        limit: int,
    ):
        table = HistoricalMarketBarRecord.__table__
        columns = [
            table.c.id,
            table.c.ticker,
            table.c.timeframe,
            table.c.bar_time,
            table.c.open_price,
            table.c.high_price,
            table.c.low_price,
            table.c.close_price,
            table.c.volume,
            table.c.adjusted_close,
            table.c.source,
            table.c.source_tier,
            table.c.point_in_time_confidence,
            table.c.metadata_json,
            table.c.created_at,
            table.c.updated_at,
        ]
        if self._has_available_at_column():
            columns.insert(4, table.c.available_at)
        query = select(*columns).where(table.c.ticker == ticker).where(table.c.timeframe == timeframe)
        if start_at is not None:
            query = query.where(table.c.bar_time >= self._normalize(start_at))
        if end_at is not None:
            query = query.where(table.c.bar_time <= self._normalize(end_at))
        if available_at is not None and self._has_available_at_column():
            query = query.where(table.c.available_at <= self._normalize(available_at))
        return query.order_by(table.c.bar_time.desc()).limit(limit)

    @staticmethod
    def _normalize(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _has_available_at_column(self) -> bool:
        if self._supports_available_at is not None:
            return self._supports_available_at
        bind = self.session.get_bind()
        if bind is None:
            self._supports_available_at = True
            return True
        try:
            columns = inspect(bind).get_columns(HistoricalMarketBarRecord.__tablename__)
            self._supports_available_at = any(column.get("name") == "available_at" for column in columns)
        except Exception:  # pragma: no cover - schema inspection fallback
            self._supports_available_at = True
        return self._supports_available_at

    @staticmethod
    def _infer_available_at(bar_time: datetime | None, timeframe: str) -> datetime | None:
        if bar_time is None:
            return None
        normalized_bar_time = HistoricalMarketDataRepository._normalize(bar_time)
        if normalized_bar_time is None:
            return None
        if timeframe in {"1d", "1wk", "1mo"}:
            return datetime.combine(normalized_bar_time.date(), time(23, 59, 59), tzinfo=timezone.utc)
        intraday_deltas = {
            "1m": timedelta(minutes=1),
            "2m": timedelta(minutes=2),
            "5m": timedelta(minutes=5),
            "15m": timedelta(minutes=15),
            "30m": timedelta(minutes=30),
            "60m": timedelta(minutes=60),
            "1h": timedelta(hours=1),
        }
        delta = intraday_deltas.get(timeframe)
        if delta is not None:
            return normalized_bar_time + delta
        return normalized_bar_time

    @classmethod
    def _to_model_from_row(cls, row: dict[str, object]) -> HistoricalMarketBar:
        bar_time = cls._normalize(row.get("bar_time"))
        timeframe = str(row.get("timeframe") or "")
        available_at = row.get("available_at") if "available_at" in row else None
        normalized_available_at = cls._normalize(available_at) if available_at else cls._infer_available_at(bar_time, timeframe)
        return HistoricalMarketBar(
            id=int(row.get("id") or 0),
            ticker=str(row.get("ticker") or ""),
            timeframe=timeframe,
            bar_time=bar_time,
            available_at=normalized_available_at,
            open_price=float(row.get("open_price") or 0.0),
            high_price=float(row.get("high_price") or 0.0),
            low_price=float(row.get("low_price") or 0.0),
            close_price=float(row.get("close_price") or 0.0),
            volume=float(row.get("volume") or 0.0),
            adjusted_close=(float(row["adjusted_close"]) if row.get("adjusted_close") is not None else None),
            source=str(row.get("source") or ""),
            source_tier=str(row.get("source_tier") or "tier_a"),
            point_in_time_confidence=float(row.get("point_in_time_confidence") or 1.0),
            metadata_json=str(row.get("metadata_json") or "{}"),
            created_at=cls._normalize(row.get("created_at")),
            updated_at=cls._normalize(row.get("updated_at")),
        )


HistoricalMarketDataRepository = HistoricalMarketDataRepository
