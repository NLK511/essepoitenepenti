from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.domain.models import HistoricalReplayBatch, HistoricalReplaySlice, Run
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.fundamental_analysis_snapshots import FundamentalAnalysisSnapshotRepository
from trade_proposer_app.repositories.historical_news import HistoricalNewsRepository
from trade_proposer_app.repositories.historical_replay import HistoricalReplayRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.context_input_access import (
    ContextSnapshotAccessService,
    FundamentalSnapshotAccessService,
    HistoricalNewsAccessService,
)
from trade_proposer_app.services.historical_bars_access import HistoricalBarsAccessService
from trade_proposer_app.services.historical_market_data import HistoricalMarketDataService
from trade_proposer_app.services.input_access import normalize_input_access_policy
from trade_proposer_app.services.json_artifact_validation import JsonArtifactValidationService
from trade_proposer_app.services.replay_universes import list_replay_universe_presets, resolve_replay_universe
from trade_proposer_app.utils.json_payloads import loads_json_list, loads_json_object


class HistoricalReplayService:
    def __init__(
        self,
        historical_replays: HistoricalReplayRepository,
        jobs: JobRepository,
        runs: RunRepository,
        historical_market_data: HistoricalMarketDataService | None = None,
        historical_news: HistoricalNewsRepository | None = None,
        context_snapshots: ContextSnapshotRepository | None = None,
        fundamental_snapshots: FundamentalAnalysisSnapshotRepository | None = None,
        input_access_policy: str = "cache_only",
        historical_bars_access: HistoricalBarsAccessService | None = None,
    ) -> None:
        self.historical_replays = historical_replays
        self.jobs = jobs
        self.runs = runs
        self.historical_market_data = historical_market_data
        self.historical_bars_access = historical_bars_access or (HistoricalBarsAccessService(historical_market_data) if historical_market_data is not None else None)
        self.historical_news = historical_news
        self.context_snapshots = context_snapshots
        self.fundamental_snapshots = fundamental_snapshots
        self.historical_news_access = HistoricalNewsAccessService(historical_news)
        self.context_snapshot_access = ContextSnapshotAccessService(context_snapshots)
        self.fundamental_snapshot_access = FundamentalSnapshotAccessService(fundamental_snapshots)
        requested_policy = normalize_input_access_policy(input_access_policy, default="cache_only")
        # Replay execution is cache-only by policy; backfills must be run as
        # explicit bars-refresh/recovery jobs before a replay starts.
        self.requested_input_access_policy = requested_policy
        self.input_access_policy = "cache_only"

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
        validated_input = JsonArtifactValidationService.validate_replay_input_summary(input_summary)
        validated_output = JsonArtifactValidationService.validate_replay_output_summary(output_summary)
        slice_status = "degraded" if validated_input.degraded or validated_output.degraded else "completed"
        slice_row = self.historical_replays.update_slice_status(
            slice_id,
            status=slice_status,
            input_summary=validated_input.payload,
            output_summary=validated_output.payload,
            timing=timing,
            error_message="; ".join(validated_input.missing_fields + validated_output.missing_fields),
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
        replay_coverage_report: dict[str, object] | None = None
        if self.historical_bars_access is None:
            raise RuntimeError("historical bars access service is required for replay execution")
        if self.historical_bars_access is not None:
            access_result = self.historical_bars_access.replay_market_inputs(
                tickers=tickers,
                batch_start=batch.as_of_start,
                batch_end=batch.as_of_end,
                as_of=slice_row.as_of,
                policy=self.input_access_policy,
            )
            hydration_summary = access_result.hydration_summary
            market_input = access_result.market_input
            replay_coverage_report = access_result.coverage_report
            replay_coverage_report = self._with_news_coverage(
                replay_coverage_report,
                tickers=tickers,
                as_of=slice_row.as_of,
            )
            replay_coverage_report = self._with_context_coverage(
                replay_coverage_report,
                tickers=tickers,
                as_of=slice_row.as_of,
            )
            replay_coverage_report = self._with_fundamental_coverage(
                replay_coverage_report,
                tickers=tickers,
                as_of=slice_row.as_of,
            )
        input_summary = {
            "replay_batch_id": batch.id,
            "replay_slice_id": slice_row.id,
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
            "replay_coverage_report": replay_coverage_report,
            "plan_generation_tuning_config_override": self._plan_generation_tuning_config_override(batch),
            "hydration_summary": hydration_summary,
            "pipeline_stage": "market_inputs_prepared",
        }
        output_summary = {
            "batch_id": batch.id,
            "slice_id": slice_row.id,
            "message": "Historical replay market-data input assembly completed.",
            "next_step": "connect market-data replay inputs to recommendation plan generation",
            "coverage_ratio": market_input.get("coverage_ratio", 0.0),
            "covered_ticker_count": market_input.get("covered_ticker_count", 0),
            "replay_tier_counts": replay_coverage_report.get("tier_counts", {}) if replay_coverage_report else {},
            "replay_tier_a_ratio": replay_coverage_report.get("tier_a_ratio", 0.0) if replay_coverage_report else 0.0,
            "ticker_count": market_input.get("ticker_count", len(tickers)),
            "pipeline_stage": "market_inputs_prepared",
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

    @staticmethod
    def _plan_generation_tuning_config_override(batch: HistoricalReplayBatch) -> dict[str, object] | None:
        config = loads_json_object(batch.config_json)
        override = config.get("plan_generation_tuning_config_override")
        return override if isinstance(override, dict) else None

    def get_slice_coverage_report(self, slice_id: int) -> dict[str, object]:
        slice_row = self.historical_replays.get_slice(slice_id)
        input_summary = loads_json_object(slice_row.input_summary_json)
        stored_report = input_summary.get("replay_coverage_report")
        if isinstance(stored_report, dict) and stored_report:
            return {"slice_id": slice_id, "source": "stored_input_summary", "coverage": stored_report}

        batch = self.historical_replays.get_batch(slice_row.replay_batch_id)
        tickers = self._parse_batch_tickers(batch)
        if self.historical_bars_access is None:
            raise RuntimeError("historical bars access service is required for replay coverage")
        report = self.historical_market_data.build_replay_coverage_report(
            tickers=tickers,
            as_of=slice_row.as_of,
            input_policy=self.input_access_policy,
            source="cache",
        )
        report = self._with_news_coverage(report, tickers=tickers, as_of=slice_row.as_of)
        report = self._with_context_coverage(report, tickers=tickers, as_of=slice_row.as_of)
        report = self._with_fundamental_coverage(report, tickers=tickers, as_of=slice_row.as_of)
        return {"slice_id": slice_id, "source": "computed", "coverage": report}

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

    def _with_news_coverage(
        self,
        report: dict[str, object],
        *,
        tickers: list[str],
        as_of: datetime,
        lookback_hours: int = 24,
    ) -> dict[str, object]:
        normalized_as_of = self._normalize(as_of)
        result = self.historical_news_access.replay_coverage(tickers=tickers, as_of=normalized_as_of, lookback_hours=lookback_hours)
        coverage = result.coverage
        counts_by_ticker = coverage.get("article_count_by_ticker") if isinstance(coverage.get("article_count_by_ticker"), dict) else {}
        ticker_rows = report.get("tickers")
        if isinstance(ticker_rows, list):
            for row in ticker_rows:
                if isinstance(row, dict):
                    ticker = str(row.get("ticker") or "")
                    row["news"] = {
                        "lookback_start": coverage.get("lookback_start"),
                        "as_of": normalized_as_of.isoformat(),
                        "article_count": counts_by_ticker.get(ticker, 0),
                        "point_in_time_filter": coverage.get("point_in_time_filter"),
                    }
        report["news_coverage"] = coverage
        report.setdefault("input_access_provenance", {})["news"] = result.provenance
        return report

    def _with_context_coverage(
        self,
        report: dict[str, object],
        *,
        tickers: list[str],
        as_of: datetime,
    ) -> dict[str, object]:
        result = self.context_snapshot_access.replay_coverage(tickers=tickers, as_of=self._normalize(as_of))
        coverage = result.coverage
        industry_by_ticker = coverage.get("industry_by_ticker") if isinstance(coverage.get("industry_by_ticker"), dict) else {}
        ticker_rows = report.get("tickers")
        if isinstance(ticker_rows, list):
            for row in ticker_rows:
                if isinstance(row, dict):
                    ticker = str(row.get("ticker") or "")
                    row["context"] = industry_by_ticker.get(ticker, {})
        report["context_coverage"] = coverage
        report.setdefault("input_access_provenance", {})["context"] = result.provenance
        return report

    def _with_fundamental_coverage(
        self,
        report: dict[str, object],
        *,
        tickers: list[str],
        as_of: datetime,
    ) -> dict[str, object]:
        result = self.fundamental_snapshot_access.replay_coverage(tickers=tickers, as_of=self._normalize(as_of))
        coverage = result.coverage
        by_ticker = coverage.get("by_ticker") if isinstance(coverage.get("by_ticker"), dict) else {}
        ticker_rows = report.get("tickers")
        if isinstance(ticker_rows, list):
            for row in ticker_rows:
                if isinstance(row, dict):
                    ticker = str(row.get("ticker") or "").upper()
                    row["fundamentals"] = by_ticker.get(ticker, {})
        report["fundamental_coverage"] = coverage
        report.setdefault("input_access_provenance", {})["fundamentals"] = result.provenance
        return report

    def _industry_key_for_ticker(self, ticker: str) -> str:
        if self.context_snapshots is None:
            return ""
        try:
            profile = self.context_snapshots.taxonomy_service.get_industry_profile(ticker)
        except Exception:
            return ""
        return str(profile.get("subject_key") or "").strip()

    @staticmethod
    def _normalize(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_batch_tickers(batch: HistoricalReplayBatch) -> list[str]:
        parsed = loads_json_list(batch.tickers_json)
        return [str(item).strip().upper() for item in parsed if str(item).strip()]
