from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.persistence.models import (
    BrokerOrderExecutionRecord,
    BrokerPositionRecord,
    WatchlistRecord,
)


class MonitoredTickerService:
    ACTIVE_ORDER_STATUSES = {"queued", "submitted", "accepted", "open", "new", "partially_filled"}
    ACTIVE_POSITION_STATUSES = {"submitted", "open", "closing"}

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_monitored_tickers(self) -> list[str]:
        return [item["ticker"] for item in self.list_monitored_tickers_with_provenance()]

    def list_monitored_tickers_with_provenance(self) -> list[dict[str, object]]:
        provenance: dict[str, set[str]] = {}
        for record in self.session.scalars(select(WatchlistRecord)).all():
            for ticker in str(record.tickers_csv or "").split(","):
                self._add(provenance, ticker, "watchlist")
        for record in self.session.scalars(select(BrokerOrderExecutionRecord)).all():
            if str(record.status or "").strip().lower() in self.ACTIVE_ORDER_STATUSES:
                self._add(provenance, record.ticker, "broker_order")
        for record in self.session.scalars(select(BrokerPositionRecord)).all():
            current_units = (
                record.current_unit_quantity
                if record.current_unit_quantity is not None
                else record.current_quantity
            )
            if (
                str(record.status or "").strip().lower() in self.ACTIVE_POSITION_STATUSES
                and float(current_units or 0.0) > 0.0
            ):
                self._add(provenance, record.ticker, "broker_position")
        return [
            {"ticker": ticker, "provenance": sorted(values)}
            for ticker, values in sorted(provenance.items())
        ]

    @staticmethod
    def _add(provenance: dict[str, set[str]], ticker: object, source: str) -> None:
        normalized = str(ticker or "").strip().upper()
        if not normalized:
            return
        provenance.setdefault(normalized, set()).add(source)
