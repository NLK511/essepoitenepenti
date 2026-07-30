from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from trade_proposer_app.domain.models import HistoricalMarketBar
from trade_proposer_app.repositories.historical_market_data import HistoricalMarketDataRepository
from trade_proposer_app.services.historical_market_data import HistoricalBarProvider
from trade_proposer_app.services.input_access import stable_hash


@dataclass(frozen=True)
class EtoroBarShadowComparisonConfig:
    timeframe: str = "1m"
    lookback_days: int = 6
    max_tickers: int = 15
    min_compared_ticker_ratio: float = 0.8
    max_median_abs_close_diff_bps: float = 5.0
    max_p95_abs_close_diff_bps: float = 25.0
    excluded_suffixes: tuple[str, ...] = (".KS", ".SS", ".SZ", ".TW")


class EtoroBarShadowComparisonService:
    def __init__(
        self,
        *,
        repository: HistoricalMarketDataRepository,
        etoro_provider: HistoricalBarProvider | None,
        unavailable_reason: str | None = None,
        config: EtoroBarShadowComparisonConfig | None = None,
    ) -> None:
        self.repository = repository
        self.etoro_provider = etoro_provider
        self.unavailable_reason = unavailable_reason
        self.config = config or EtoroBarShadowComparisonConfig()

    def compare(
        self,
        *,
        tickers: list[str],
        end_at: datetime | None = None,
    ) -> dict[str, object]:
        normalized_end = self._normalize(end_at or datetime.now(UTC))
        start_at = normalized_end - timedelta(days=self.config.lookback_days)
        universe = list(
            dict.fromkeys(ticker.strip().upper() for ticker in tickers if ticker.strip())
        )
        eligible = self._eligible_tickers(universe)
        sampled = self._sample_tickers(eligible, seed=normalized_end)
        if self.etoro_provider is None:
            return {
                "status": "failed",
                "reason": self.unavailable_reason or "etoro_provider_unavailable",
                "candidate_provider": "etoro",
                "primary_provider": "local_yfinance_cache",
                "timeframe": self.config.timeframe,
                "start_at": start_at.isoformat(),
                "end_at": normalized_end.isoformat(),
                "universe_ticker_count": len(universe),
                "eligible_ticker_count": len(eligible),
                "excluded_ticker_count": len(universe) - len(eligible),
                "sampled_ticker_count": len(sampled),
                "tickers": [],
                "warnings": [self.unavailable_reason or "etoro_provider_unavailable"],
            }

        ticker_results: list[dict[str, object]] = []
        all_diffs: list[float] = []
        compared_ticker_count = 0
        primary_missing_count = 0
        candidate_empty_count = 0
        error_count = 0
        no_overlap_count = 0
        primary_bar_count = 0
        candidate_bar_count = 0
        overlap_bar_count = 0

        for ticker in sampled:
            primary_bars = self.repository.list_bars(
                ticker=ticker,
                timeframe=self.config.timeframe,
                start_at=start_at,
                end_at=normalized_end,
                available_at=normalized_end,
                limit=None,
            )
            primary_bar_count += len(primary_bars)
            if not primary_bars:
                primary_missing_count += 1
                ticker_results.append(
                    {
                        "ticker": ticker,
                        "status": "primary_missing",
                        "primary_bar_count": 0,
                        "candidate_bar_count": 0,
                        "overlap_bar_count": 0,
                    }
                )
                continue

            try:
                fetched = self.etoro_provider.fetch_bars(
                    ticker,
                    self.config.timeframe,
                    start_at,
                    normalized_end,
                )
                candidate_bars = fetched.bars
            except Exception as exc:  # noqa: BLE001
                error_count += 1
                ticker_results.append(
                    {
                        "ticker": ticker,
                        "status": "candidate_error",
                        "error": str(exc),
                        "primary_bar_count": len(primary_bars),
                        "candidate_bar_count": 0,
                        "overlap_bar_count": 0,
                    }
                )
                continue

            candidate_bar_count += len(candidate_bars)
            if not candidate_bars:
                candidate_empty_count += 1
                ticker_results.append(
                    {
                        "ticker": ticker,
                        "status": "candidate_empty",
                        "primary_bar_count": len(primary_bars),
                        "candidate_bar_count": 0,
                        "overlap_bar_count": 0,
                    }
                )
                continue

            diffs = self._close_diff_bps(primary_bars, candidate_bars)
            overlap_bar_count += len(diffs)
            if not diffs:
                no_overlap_count += 1
                ticker_results.append(
                    {
                        "ticker": ticker,
                        "status": "no_overlap",
                        "primary_bar_count": len(primary_bars),
                        "candidate_bar_count": len(candidate_bars),
                        "overlap_bar_count": 0,
                    }
                )
                continue

            compared_ticker_count += 1
            all_diffs.extend(diffs)
            ticker_results.append(
                {
                    "ticker": ticker,
                    "status": "compared",
                    "primary_bar_count": len(primary_bars),
                    "candidate_bar_count": len(candidate_bars),
                    "overlap_bar_count": len(diffs),
                    "median_abs_close_diff_bps": self._median(diffs),
                    "p95_abs_close_diff_bps": self._percentile(diffs, 95),
                    "max_abs_close_diff_bps": max(diffs),
                }
            )

        metrics = {
            "universe_ticker_count": len(universe),
            "eligible_ticker_count": len(eligible),
            "excluded_ticker_count": len(universe) - len(eligible),
            "sampled_ticker_count": len(sampled),
            "compared_ticker_count": compared_ticker_count,
            "primary_missing_count": primary_missing_count,
            "candidate_empty_count": candidate_empty_count,
            "candidate_error_count": error_count,
            "no_overlap_count": no_overlap_count,
            "primary_bar_count": primary_bar_count,
            "candidate_bar_count": candidate_bar_count,
            "overlap_bar_count": overlap_bar_count,
            "compared_ticker_ratio": round(
                compared_ticker_count / len(sampled), 4
            )
            if sampled
            else 0.0,
            "median_abs_close_diff_bps": self._median(all_diffs),
            "p95_abs_close_diff_bps": self._percentile(all_diffs, 95),
            "max_abs_close_diff_bps": max(all_diffs) if all_diffs else None,
        }
        warnings = self._warnings(metrics)
        return {
            "status": "passed" if not warnings else "completed_with_warnings",
            "candidate_provider": "etoro",
            "primary_provider": "local_yfinance_cache",
            "timeframe": self.config.timeframe,
            "start_at": start_at.isoformat(),
            "end_at": normalized_end.isoformat(),
            "config": {
                "lookback_days": self.config.lookback_days,
                "max_tickers": self.config.max_tickers,
                "excluded_suffixes": list(self.config.excluded_suffixes),
                "min_compared_ticker_ratio": self.config.min_compared_ticker_ratio,
                "max_median_abs_close_diff_bps": self.config.max_median_abs_close_diff_bps,
                "max_p95_abs_close_diff_bps": self.config.max_p95_abs_close_diff_bps,
                "non_mutating": True,
            },
            "metrics": metrics,
            "warnings": warnings,
            "tickers": ticker_results,
        }

    def _warnings(self, metrics: dict[str, object]) -> list[str]:
        warnings: list[str] = []
        compared_ratio = float(metrics.get("compared_ticker_ratio") or 0.0)
        median_diff = metrics.get("median_abs_close_diff_bps")
        p95_diff = metrics.get("p95_abs_close_diff_bps")
        if compared_ratio < self.config.min_compared_ticker_ratio:
            warnings.append("etoro_shadow_low_compared_ticker_ratio")
        if (
            median_diff is not None
            and float(median_diff) > self.config.max_median_abs_close_diff_bps
        ):
            warnings.append("etoro_shadow_median_price_diff_exceeded")
        if p95_diff is not None and float(p95_diff) > self.config.max_p95_abs_close_diff_bps:
            warnings.append("etoro_shadow_p95_price_diff_exceeded")
        return warnings

    def _sample_tickers(self, tickers: list[str], *, seed: datetime) -> list[str]:
        if len(tickers) <= self.config.max_tickers:
            return tickers
        seed_label = seed.strftime("%G-W%V")
        return sorted(
            tickers,
            key=lambda ticker: stable_hash(f"{seed_label}:{ticker}"),
        )[: self.config.max_tickers]

    def _eligible_tickers(self, tickers: list[str]) -> list[str]:
        suffixes = tuple(suffix.upper() for suffix in self.config.excluded_suffixes)
        return [ticker for ticker in tickers if not ticker.endswith(suffixes)]

    @classmethod
    def _close_diff_bps(
        cls,
        primary_bars: list[HistoricalMarketBar],
        candidate_bars: list[HistoricalMarketBar],
    ) -> list[float]:
        primary_by_time = {
            cls._normalize(bar.bar_time): bar
            for bar in primary_bars
            if bar.close_price and bar.close_price > 0
        }
        diffs: list[float] = []
        for candidate in candidate_bars:
            primary = primary_by_time.get(cls._normalize(candidate.bar_time))
            if primary is None or primary.close_price <= 0:
                continue
            diff_bps = (
                abs(candidate.close_price - primary.close_price)
                / primary.close_price
                * 10000
            )
            diffs.append(diff_bps)
        return diffs

    @staticmethod
    def _median(values: list[float]) -> float | None:
        if not values:
            return None
        return round(float(statistics.median(values)), 6)

    @staticmethod
    def _percentile(values: list[float], percentile: int) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, round((percentile / 100) * (len(ordered) - 1))))
        return round(float(ordered[index]), 6)

    @staticmethod
    def _normalize(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
