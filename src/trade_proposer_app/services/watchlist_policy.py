from __future__ import annotations

from trade_proposer_app.domain.enums import JobType, StrategyHorizon
from trade_proposer_app.domain.models import Job, Watchlist, WatchlistEvaluationPolicy


class WatchlistPolicyService:
    def describe_watchlist(self, watchlist: Watchlist) -> WatchlistEvaluationPolicy:
        warnings: list[str] = []
        if watchlist.optimize_evaluation_timing and not watchlist.timezone.strip():
            warnings.append("optimize_evaluation_timing is enabled but watchlist timezone is missing")

        if watchlist.optimize_evaluation_timing and watchlist.timezone.strip():
            primary_cron, primary_label, secondary_label = self._optimized_windows(watchlist.default_horizon)
            return WatchlistEvaluationPolicy(
                watchlist_id=watchlist.id,
                watchlist_name=watchlist.name,
                default_horizon=watchlist.default_horizon,
                schedule_source="watchlist_optimized",
                schedule_timezone=watchlist.timezone.strip(),
                primary_cron=primary_cron,
                primary_window_label=primary_label,
                secondary_window_label=secondary_label,
                warnings=warnings,
            )

        return WatchlistEvaluationPolicy(
            watchlist_id=watchlist.id,
            watchlist_name=watchlist.name,
            default_horizon=watchlist.default_horizon,
            schedule_source="manual_or_unscheduled",
            schedule_timezone=watchlist.timezone.strip(),
            primary_cron=None,
            primary_window_label="No automatic watchlist schedule derived",
            secondary_window_label="",
            warnings=warnings,
        )

    def resolve_job_schedule(self, job: Job, watchlist: Watchlist | None) -> tuple[str, str, str] | None:
        if job.cron:
            return job.cron, "UTC", "job_cron"
        if job.job_type != JobType.PROPOSAL_GENERATION:
            return None
        if watchlist is None:
            return None
        policy = self.describe_watchlist(watchlist)
        if policy.primary_cron is None:
            return None
        if policy.warnings:
            return None
        return policy.primary_cron, policy.schedule_timezone, policy.schedule_source

    @staticmethod
    def _optimized_windows(horizon: StrategyHorizon) -> tuple[str, str, str]:
        if horizon == StrategyHorizon.ONE_DAY:
            return (
                "20 9 * * MON-FRI",
                "09:20 local weekday opening scan",
                "15:45 local focused re-check for shortlisted names",
            )
        if horizon == StrategyHorizon.ONE_MONTH:
            return (
                "30 10 * * MON,WED,FRI",
                "10:30 local Monday/Wednesday/Friday context refresh",
                "15:30 local event-driven deep analysis when a ticker is shortlisted",
            )
        return (
            "0 10 * * MON-FRI",
            "10:00 local weekday swing scan",
            "15:30 local deeper follow-up for shortlisted names",
        )
