from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import Watchlist
from trade_proposer_app.persistence.models import WatchlistRecord


class WatchlistRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[Watchlist]:
        rows = self.session.scalars(select(WatchlistRecord).order_by(WatchlistRecord.name)).all()
        return [self._to_model(row) for row in rows]

    def create(self, name: str, tickers: list[str]) -> Watchlist:
        normalized_tickers = [ticker for ticker in tickers if ticker]
        if not normalized_tickers:
            raise ValueError("watchlist requires at least one ticker")
        duplicate_tickers = self._find_tickers_already_assigned(normalized_tickers)
        if duplicate_tickers:
            duplicates = ", ".join(duplicate_tickers)
            raise ValueError(f"ticker already assigned to another watchlist: {duplicates}")
        record = WatchlistRecord(name=name, tickers_csv=",".join(normalized_tickers))
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def create_unique(self, base_name: str, tickers: list[str]) -> Watchlist:
        normalized_base_name = base_name.strip()
        if not normalized_base_name:
            raise ValueError("watchlist name is required")

        existing_names = set(self.session.scalars(select(WatchlistRecord.name)).all())
        candidate = normalized_base_name
        suffix = 2
        while candidate in existing_names:
            candidate = f"{normalized_base_name} ({suffix})"
            suffix += 1
        return self.create(candidate, tickers)

    def get(self, watchlist_id: int) -> Watchlist:
        record = self.session.get(WatchlistRecord, watchlist_id)
        if record is None:
            raise ValueError(f"Watchlist {watchlist_id} not found")
        return self._to_model(record)

    def _find_tickers_already_assigned(self, tickers: list[str]) -> list[str]:
        wanted = set(tickers)
        duplicates: list[str] = []
        existing_watchlists = self.session.scalars(select(WatchlistRecord)).all()
        for watchlist in existing_watchlists:
            existing_tickers = {ticker for ticker in watchlist.tickers_csv.split(",") if ticker}
            for ticker in tickers:
                if ticker in wanted and ticker in existing_tickers and ticker not in duplicates:
                    duplicates.append(ticker)
        return duplicates

    @staticmethod
    def _to_model(record: WatchlistRecord) -> Watchlist:
        return Watchlist(
            id=record.id,
            name=record.name,
            tickers=[ticker for ticker in record.tickers_csv.split(",") if ticker],
        )
