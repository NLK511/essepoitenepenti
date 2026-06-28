from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.domain.models import HistoricalReplayBatch, HistoricalReplaySlice, Run
from trade_proposer_app.repositories.context_snapshots import ContextSnapshotRepository
from trade_proposer_app.repositories.fundamental_analysis_snapshots import FundamentalAnalysisSnapshotRepository
from trade_proposer_app.repositories.historical_news import HistoricalNewsRepository
from trade_proposer_app.repositories.historical_replay import HistoricalReplayRepository
from trade_proposer_app.repositories.jobs import JobRepository
from trade_proposer_app.repositories.runs import RunRepository
from trade_proposer_app.services.historical_market_data import HistoricalMarketDataService
from trade_proposer_app.services.input_access import normalize_input_access_policy
from trade_proposer_app.services.replay_universes import list_replay_universe_presets, resolve_replay_universe


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
        input_access_policy: str = "cache_then_remote",
    ) -> None:
        self.historical_replays = historical_replays
        self.jobs = jobs
        self.runs = runs
        self.historical_market_data = historical_market_data
        self.historical_news = historical_news
        self.context_snapshots = context_snapshots
        self.fundamental_snapshots = fundamental_snapshots
        self.input_access_policy = normalize_input_access_policy(input_access_policy)

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
        replay_coverage_report: dict[str, object] | None = None
        if self.historical_market_data is not None:
            if self.input_access_policy in {"cache_then_remote", "remote_refresh"}:
                hydration_summary = self.hydrate_batch_market_data(batch_id)
            else:
                hydration_summary = {
                    "provider": getattr(self.historical_market_data.provider, "provider_name", "unknown"),
                    "source_tier": getattr(self.historical_market_data.provider, "source_tier", "unknown"),
                    "policy": self.input_access_policy,
                    "status": "skipped_remote_hydration",
                    "reason": "input_access_policy_disallows_remote_fetch",
                    "ticker_count": len(tickers),
                }
            market_input = self.historical_market_data.build_slice_market_input(tickers=tickers, as_of=slice_row.as_of)
            replay_coverage_report = self.historical_market_data.build_replay_coverage_report(
                tickers=tickers,
                as_of=slice_row.as_of,
                input_policy=self.input_access_policy,
                source="cache" if self.input_access_policy in {"cache_only", "fail_if_missing"} else "cache_plus_remote",
            )
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
        else:
            market_input = {
                "as_of": slice_row.as_of.isoformat(),
                "ticker_count": len(tickers),
                "covered_ticker_count": 0,
                "coverage_ratio": 0.0,
                "tickers": [],
            }
            replay_coverage_report = {
                "as_of": slice_row.as_of.isoformat(),
                "policy": self.input_access_policy,
                "source": "unconfigured",
                "ticker_count": len(tickers),
                "tier_counts": {"tier_a": 0, "tier_b": 0, "tier_c": 0, "ineligible": len(tickers)},
                "tier_a_ratio": 0.0,
                "tickers": [],
                "blockers": ["historical_market_data_service_not_configured"],
                "warnings": [],
            }
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
        try:
            config = json.loads(batch.config_json or "{}")
        except json.JSONDecodeError:
            return None
        if not isinstance(config, dict):
            return None
        override = config.get("plan_generation_tuning_config_override")
        return override if isinstance(override, dict) else None

    def get_slice_coverage_report(self, slice_id: int) -> dict[str, object]:
        slice_row = self.historical_replays.get_slice(slice_id)
        try:
            input_summary = json.loads(slice_row.input_summary_json or "{}")
        except json.JSONDecodeError:
            input_summary = {}
        stored_report = input_summary.get("replay_coverage_report")
        if isinstance(stored_report, dict) and stored_report:
            return {"slice_id": slice_id, "source": "stored_input_summary", "coverage": stored_report}

        batch = self.historical_replays.get_batch(slice_row.replay_batch_id)
        tickers = self._parse_batch_tickers(batch)
        if self.historical_market_data is None:
            return {
                "slice_id": slice_id,
                "source": "computed_without_market_service",
                "coverage": {
                    "as_of": slice_row.as_of.isoformat(),
                    "ticker_count": len(tickers),
                    "tier_counts": {"tier_a": 0, "tier_b": 0, "tier_c": 0, "ineligible": len(tickers)},
                    "tier_a_ratio": 0.0,
                    "tickers": [],
                },
            }
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
        if self.historical_news is None:
            report["news_coverage"] = {"status": "not_configured", "lookback_hours": lookback_hours}
            return report
        normalized_as_of = self._normalize(as_of)
        start_at = normalized_as_of - timedelta(hours=max(1, lookback_hours))
        counts_by_ticker = {
            ticker: self.historical_news.count_news(
                ticker,
                start_at=start_at,
                end_at=normalized_as_of,
                available_at=normalized_as_of,
            )
            for ticker in tickers
        }
        ticker_rows = report.get("tickers")
        if isinstance(ticker_rows, list):
            for row in ticker_rows:
                if isinstance(row, dict):
                    ticker = str(row.get("ticker") or "")
                    row["news"] = {
                        "lookback_start": start_at.isoformat(),
                        "as_of": normalized_as_of.isoformat(),
                        "article_count": counts_by_ticker.get(ticker, 0),
                        "point_in_time_filter": "published_at <= as_of and available_at <= as_of",
                    }
        covered = sum(1 for count in counts_by_ticker.values() if count > 0)
        report["news_coverage"] = {
            "status": "available",
            "lookback_hours": lookback_hours,
            "covered_ticker_count": covered,
            "coverage_ratio": round((covered / len(tickers)) if tickers else 0.0, 4),
            "article_count_by_ticker": counts_by_ticker,
            "point_in_time_filter": "published_at <= as_of and available_at <= as_of",
        }
        return report

    def _with_context_coverage(
        self,
        report: dict[str, object],
        *,
        tickers: list[str],
        as_of: datetime,
    ) -> dict[str, object]:
        if self.context_snapshots is None:
            report["context_coverage"] = {"status": "not_configured"}
            return report
        normalized_as_of = self._normalize(as_of)
        macro = self.context_snapshots.get_latest_macro_context_snapshot_before(normalized_as_of)
        macro_payload = {
            "available": macro is not None,
            "computed_at": macro.computed_at.isoformat() if macro and macro.computed_at else None,
            "status": macro.status if macro else None,
            "point_in_time_filter": "computed_at <= as_of",
        }
        industry_counts = {"available": 0, "missing": 0}
        industry_by_ticker: dict[str, dict[str, object]] = {}
        for ticker in tickers:
            industry_key = self._industry_key_for_ticker(ticker)
            industry = (
                self.context_snapshots.get_latest_industry_context_snapshot_before(
                    industry_key,
                    normalized_as_of,
                )
                if industry_key
                else None
            )
            if industry is None:
                industry_counts["missing"] += 1
            else:
                industry_counts["available"] += 1
            industry_by_ticker[ticker] = {
                "industry_key": industry_key,
                "available": industry is not None,
                "computed_at": industry.computed_at.isoformat() if industry and industry.computed_at else None,
                "status": industry.status if industry else None,
                "point_in_time_filter": "computed_at <= as_of",
            }
        ticker_rows = report.get("tickers")
        if isinstance(ticker_rows, list):
            for row in ticker_rows:
                if isinstance(row, dict):
                    ticker = str(row.get("ticker") or "")
                    row["context"] = industry_by_ticker.get(ticker, {})
        report["context_coverage"] = {
            "status": "available",
            "macro": macro_payload,
            "industry_counts": industry_counts,
            "industry_by_ticker": industry_by_ticker,
            "industry_coverage_ratio": round((industry_counts["available"] / len(tickers)) if tickers else 0.0, 4),
        }
        return report

    def _with_fundamental_coverage(
        self,
        report: dict[str, object],
        *,
        tickers: list[str],
        as_of: datetime,
    ) -> dict[str, object]:
        if self.fundamental_snapshots is None:
            report["fundamental_coverage"] = {"status": "not_configured"}
            return report
        normalized_as_of = self._normalize(as_of)
        snapshots = self.fundamental_snapshots.list_latest_by_tickers(tickers, as_of=normalized_as_of)
        by_ticker: dict[str, dict[str, object]] = {}
        covered = 0
        for ticker in tickers:
            normalized_ticker = ticker.upper()
            snapshot = snapshots.get(normalized_ticker)
            if snapshot is not None:
                covered += 1
            snapshot_as_of = snapshot.get("as_of") if snapshot else None
            by_ticker[normalized_ticker] = {
                "available": snapshot is not None,
                "as_of": snapshot_as_of.isoformat() if isinstance(snapshot_as_of, datetime) else None,
                "coverage_status": snapshot.get("coverage_status") if snapshot else None,
                "freshness_status": snapshot.get("freshness_status") if snapshot else None,
                "point_in_time_filter": "snapshot.as_of <= replay as_of",
            }
        ticker_rows = report.get("tickers")
        if isinstance(ticker_rows, list):
            for row in ticker_rows:
                if isinstance(row, dict):
                    ticker = str(row.get("ticker") or "").upper()
                    row["fundamentals"] = by_ticker.get(ticker, {})
        report["fundamental_coverage"] = {
            "status": "available",
            "covered_ticker_count": covered,
            "coverage_ratio": round((covered / len(tickers)) if tickers else 0.0, 4),
            "by_ticker": by_ticker,
        }
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
        try:
            parsed = json.loads(batch.tickers_json or "[]")
        except json.JSONDecodeError:
            parsed = []
        if not isinstance(parsed, list):
            return []
        return [str(item).strip().upper() for item in parsed if str(item).strip()]
