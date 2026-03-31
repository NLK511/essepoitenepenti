from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from trade_proposer_app.domain.enums import JobType, StrategyHorizon
from trade_proposer_app.domain.models import HistoricalReplayBatch, HistoricalReplaySlice, Run, TickerSignalSnapshot
from trade_proposer_app.repositories.historical_replay import HistoricalReplayRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.historical_market_data import HistoricalMarketDataService
from trade_proposer_app.services.replay_universes import list_replay_universe_presets, resolve_replay_universe


class HistoricalReplayService:
    def __init__(
        self,
        historical_replays: HistoricalReplayRepository,
        jobs: JobRepository,
        runs: RunRepository,
        historical_market_data: HistoricalMarketDataService | None = None,
    ) -> None:
        self.historical_replays = historical_replays
        self.jobs = jobs
        self.runs = runs
        self.historical_market_data = historical_market_data

    def create_batch(
        self,
        *,
        name: str,
        mode: str,
        as_of_start: datetime,
        as_of_end: datetime,
        cadence: str = "daily",
        universe_preset: str | None = None,
        tickers: list[str] | None = None,
        entry_timing: str = "next_open",
        price_provider: str = "yahoo",
        price_source_tier: str = "research",
        bar_timeframe: str = "1d",
        config: dict[str, object] | None = None,
    ) -> HistoricalReplayBatch:
        normalized_start = self._normalize(as_of_start)
        normalized_end = self._normalize(as_of_end)
        if normalized_end < normalized_start:
            raise ValueError("as_of_end must be greater than or equal to as_of_start")
        if mode not in {"strict", "research"}:
            raise ValueError("mode must be either 'strict' or 'research'")
        if cadence != "daily":
            raise ValueError("only daily cadence is currently supported")
        if entry_timing not in {"next_open", "next_close"}:
            raise ValueError("entry_timing must be either 'next_open' or 'next_close'")
        if bar_timeframe != "1d":
            raise ValueError("only 1d bar timeframe is currently supported")

        universe_mode, resolved_preset, resolved_tickers = resolve_replay_universe(
            universe_preset=universe_preset,
            tickers=tickers,
        )
        merged_config = dict(config or {})
        merged_config.update(
            {
                "universe_mode": universe_mode,
                "universe_preset": resolved_preset,
                "ticker_count": len(resolved_tickers),
                "entry_timing": entry_timing,
                "price_provider": price_provider,
                "price_source_tier": price_source_tier,
                "bar_timeframe": bar_timeframe,
            }
        )

        batch = self.historical_replays.create_batch(
            name=name,
            mode=mode,
            universe_mode=universe_mode,
            universe_preset=resolved_preset,
            tickers=resolved_tickers,
            entry_timing=entry_timing,
            price_provider=price_provider,
            price_source_tier=price_source_tier,
            bar_timeframe=bar_timeframe,
            as_of_start=normalized_start,
            as_of_end=normalized_end,
            cadence=cadence,
            config=merged_config,
        )
        self.historical_replays.create_daily_slices(batch.id or 0)
        return self.historical_replays.refresh_batch_status(batch.id or 0)

    def enqueue_batch(self, batch_id: int) -> list[Run]:
        batch = self.historical_replays.get_batch(batch_id)
        slices = self.historical_replays.list_slices(batch_id)
        if not slices:
            raise ValueError("historical replay batch has no slices")
        system_job = self.jobs.get_or_create_system_job(f"historical_replay_batch_{batch_id}", JobType.HISTORICAL_REPLAY)
        self.historical_replays.update_batch_status(batch_id, status="queued", job_id=system_job.id)
        queued_runs: list[Run] = []
        for slice_row in slices:
            if slice_row.run_id is not None:
                continue
            run = self.runs.enqueue(
                system_job.id or 0,
                scheduled_for=slice_row.as_of,
                job_type=JobType.HISTORICAL_REPLAY,
            )
            self.runs.set_artifact(
                run.id or 0,
                {
                    "historical_replay": {
                        "batch_id": batch_id,
                        "slice_id": slice_row.id,
                        "as_of": slice_row.as_of.isoformat(),
                        "mode": batch.mode,
                        "cadence": batch.cadence,
                        "entry_timing": batch.entry_timing,
                        "price_provider": batch.price_provider,
                        "price_source_tier": batch.price_source_tier,
                    }
                },
            )
            self.historical_replays.attach_slice_run(
                slice_row.id or 0,
                job_id=system_job.id or 0,
                run_id=run.id or 0,
                status="queued",
            )
            queued_runs.append(run)
        self.jobs.mark_enqueued(system_job.id or 0)
        self.historical_replays.refresh_batch_status(batch_id)
        return queued_runs

    def hydrate_batch_market_data(self, batch_id: int) -> dict[str, object]:
        if self.historical_market_data is None:
            raise RuntimeError("historical market data service is not configured")
        batch = self.historical_replays.get_batch(batch_id)
        tickers = self._parse_batch_tickers(batch)
        return self.historical_market_data.hydrate_batch_inputs(
            tickers=tickers,
            start_at=batch.as_of_start,
            end_at=batch.as_of_end,
        )

    def mark_slice_running(self, slice_id: int) -> HistoricalReplaySlice:
        return self.historical_replays.update_slice_status(slice_id, status="running")

    def complete_slice(
        self,
        slice_id: int,
        *,
        input_summary: dict[str, object],
        output_summary: dict[str, object],
        timing: dict[str, object],
    ) -> HistoricalReplaySlice:
        slice_row = self.historical_replays.update_slice_status(
            slice_id,
            status="completed",
            input_summary=input_summary,
            output_summary=output_summary,
            timing=timing,
            error_message="",
        )
        self.historical_replays.refresh_batch_status(slice_row.replay_batch_id)
        return slice_row

    def fail_slice(self, slice_id: int, *, error_message: str, timing: dict[str, object] | None = None) -> HistoricalReplaySlice:
        slice_row = self.historical_replays.update_slice_status(
            slice_id,
            status="failed",
            timing=timing,
            error_message=error_message,
        )
        self.historical_replays.refresh_batch_status(slice_row.replay_batch_id)
        return slice_row

    def build_slice_execution_payload(self, batch_id: int, slice_id: int) -> tuple[dict[str, object], dict[str, object]]:
        batch = self.historical_replays.get_batch(batch_id)
        slice_row = self.historical_replays.get_slice(slice_id)
        tickers = self._parse_batch_tickers(batch)
        hydration_summary: dict[str, object] | None = None
        if self.historical_market_data is not None:
            hydration_summary = self.hydrate_batch_market_data(batch_id)
            market_input = self.historical_market_data.build_slice_market_input(tickers=tickers, as_of=slice_row.as_of)
        else:
            market_input = {
                "as_of": slice_row.as_of.isoformat(),
                "ticker_count": len(tickers),
                "covered_ticker_count": 0,
                "coverage_ratio": 0.0,
                "tickers": [],
            }
        dummy_signals = self._build_dummy_signal_snapshots(market_input.get("tickers", []), slice_row.as_of)
        input_summary = {
            "as_of": slice_row.as_of.isoformat(),
            "mode": batch.mode,
            "cadence": batch.cadence,
            "entry_timing": batch.entry_timing,
            "price_provider": batch.price_provider,
            "price_source_tier": batch.price_source_tier,
            "universe_mode": batch.universe_mode,
            "universe_preset": batch.universe_preset,
            "tickers": tickers,
            "market_input": market_input,
            "hydration_summary": hydration_summary,
            "signal_logic": {
                "version": "dummy_placeholder_v1",
                "note": "This replay signal logic is intentionally dummy scaffolding. It must be replaced with the app-native signal pipeline before strict comparisons are made.",
            },
        }
        output_summary = {
            "batch_id": batch.id,
            "slice_id": slice_row.id,
            "message": "Historical replay market-data input assembly completed; plan generation pipeline not implemented yet.",
            "next_step": "connect market-data replay inputs to recommendation plan generation",
            "coverage_ratio": market_input.get("coverage_ratio", 0.0),
            "covered_ticker_count": market_input.get("covered_ticker_count", 0),
            "ticker_count": market_input.get("ticker_count", len(tickers)),
            "dummy_signal_logic": {
                "version": "dummy_placeholder_v1",
                "note": "This replay signal logic is intentionally dummy scaffolding and must be aligned to the app-native signal logic later.",
                "signals": [signal.model_dump(mode="json") for signal in dummy_signals],
            },
        }
        return input_summary, output_summary

    def get_batch_detail(self, batch_id: int) -> dict[str, object]:
        batch = self.historical_replays.get_batch(batch_id)
        return {
            "batch": batch.model_dump(),
            "slices": [slice_row.model_dump() for slice_row in self.historical_replays.list_slices(batch_id)],
            "summary": self.historical_replays.summarize_batch(batch_id),
            "resolved_tickers": self._parse_batch_tickers(batch),
        }

    def list_universe_presets(self) -> list[dict[str, object]]:
        return [
            {
                "key": preset.key,
                "label": preset.label,
                "region": preset.region,
                "description": preset.description,
                "tickers": list(preset.tickers),
                "ticker_count": len(preset.tickers),
            }
            for preset in list_replay_universe_presets()
        ]

    @staticmethod
    def default_batch_window(days: int = 30) -> tuple[datetime, datetime]:
        end = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
        start = (end - timedelta(days=max(0, days - 1))).replace(hour=23, minute=59, second=59, microsecond=0)
        return start, end

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _build_dummy_signal_snapshots(ticker_market_rows: list[dict[str, object]], as_of: datetime) -> list[TickerSignalSnapshot]:
        signals: list[TickerSignalSnapshot] = []
        for row in ticker_market_rows:
            ticker = str(row.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            latest_close = row.get("latest_close")
            latest_bar_time = row.get("latest_bar_time")
            latest_open = row.get("latest_open")
            direction = "neutral"
            technical_score = 0.0
            confidence = 15.0
            status = "ok"
            warnings: list[str] = ["dummy_replay_signal_logic"]
            missing_inputs: list[str] = []
            if latest_close is None:
                status = "degraded"
                missing_inputs.append("latest_close")
            else:
                if latest_open is not None:
                    try:
                        open_value = float(latest_open)
                        close_value = float(latest_close)
                    except (TypeError, ValueError):
                        open_value = 0.0
                        close_value = 0.0
                    if close_value > open_value:
                        direction = "long"
                    elif close_value < open_value:
                        direction = "short"
                    technical_score = round(abs(close_value - open_value) / max(abs(open_value), 1.0) * 100.0, 2)
                    confidence = round(min(75.0, 20.0 + technical_score), 2)
                else:
                    confidence = 20.0
            signals.append(
                TickerSignalSnapshot(
                    ticker=ticker,
                    horizon=StrategyHorizon.ONE_WEEK,
                    computed_at=as_of,
                    status=status,
                    direction=direction,
                    confidence_percent=confidence,
                    swing_probability_percent=confidence,
                    technical_setup_score=technical_score,
                    attention_score=min(100.0, confidence + 5.0),
                    warnings=warnings,
                    missing_inputs=missing_inputs,
                    diagnostics={
                        "mode": "dummy_placeholder",
                        "note": "This is a placeholder replay signal. It must be aligned to the app-native signal pipeline later.",
                        "latest_bar_time": latest_bar_time,
                    },
                )
            )
        return signals

    @staticmethod
    def _parse_batch_tickers(batch: HistoricalReplayBatch) -> list[str]:
        try:
            parsed = json.loads(batch.tickers_json or "[]")
        except json.JSONDecodeError:
            parsed = []
        if not isinstance(parsed, list):
            return []
        return [str(item).strip().upper() for item in parsed if str(item).strip()]
