from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService


@dataclass(frozen=True)
class ReplayActionabilityPlanRow:
    as_of: datetime
    ticker: str
    action: str
    confidence_percent: float
    entry_price_low: float | None
    entry_price_high: float | None
    stop_loss: float | None
    take_profit: float | None
    signal_breakdown: dict[str, Any]
    evidence_summary: dict[str, Any]
    outcome: str
    outcome_status: str


class ActionabilityFloorCalibrationService:
    """Rescore replay artifacts across downstream actionability floors.

    This service intentionally does not rerun replay or mutate active tuning
    config. It is a periodic diagnostic/proposal layer for one narrow parameter:
    global.actionable_confidence_floor_percent.
    """

    DEFAULT_FLOORS = tuple(float(value) for value in range(40, 61))

    def __init__(self, session: Session) -> None:
        self.session = session

    def run(
        self,
        *,
        replay_batch_id: int | None = None,
        floors: Iterable[float] | None = None,
        min_resolved_trades: int = 10,
    ) -> dict[str, Any]:
        selected_batch = self._resolve_replay_batch(replay_batch_id)
        if selected_batch is None:
            return {
                "mode": "actionability_floor_calibration",
                "status": "skipped",
                "reason": "no_completed_replay_batch",
                "floors": list(floors or self.DEFAULT_FLOORS),
            }
        batch_id = int(selected_batch["id"])
        rows = self._load_rows(batch_id)
        eligibility_guardrail = self._eligibility_guardrail(batch_id)
        floor_values = [float(value) for value in (floors or self.DEFAULT_FLOORS)]
        summaries = [self._summarize(rows, floor) for floor in floor_values]
        active_floor = self._active_actionability_floor()
        active_summary = self._summary_for_floor(summaries, active_floor)
        candidates = [item for item in summaries if int(item["resolved_count"]) >= min_resolved_trades]
        best = max(candidates, key=lambda item: (float(item["ev_percent_points"]), float(item["ev_per_actionable"] or -9999.0)), default=None)
        recommendation = self._recommendation(best, active_summary, min_resolved_trades=min_resolved_trades)
        return {
            "mode": "actionability_floor_calibration",
            "status": "completed",
            "purpose": "weekly diagnostic/proposal check for downstream actionability confidence floor only",
            "replay_batch": selected_batch,
            "plan_count": len(rows),
            "replay_eligibility_guardrail": eligibility_guardrail,
            "floors": floor_values,
            "active_floor": active_floor,
            "min_resolved_trades": min_resolved_trades,
            "best_floor": best["floor"] if best else None,
            "active_floor_summary": active_summary,
            "best_floor_summary": best,
            "recommendation": recommendation,
            "summaries": summaries,
        }

    def _eligibility_guardrail(self, batch_id: int) -> dict[str, Any]:
        row = self.session.execute(
            text(
                """
                select
                    (select count(*) from replay_plan_outcomes where replay_batch_id = :batch_id) as outcome_count,
                    (select count(*) from replay_eligibility_records where replay_batch_id = :batch_id) as eligibility_count,
                    (select count(*) from replay_eligibility_records where replay_batch_id = :batch_id and eligible_for_tuning = true) as eligible_count
                """
            ),
            {"batch_id": batch_id},
        ).mappings().first()
        outcome_count = int(row["outcome_count"] or 0) if row else 0
        eligibility_count = int(row["eligibility_count"] or 0) if row else 0
        eligible_count = int(row["eligible_count"] or 0) if row else 0
        status = "ok"
        warning = None
        if outcome_count > 0 and eligibility_count == 0:
            status = "missing_eligibility_rows"
            warning = "replay outcomes exist but no replay eligibility rows exist; run reclassify_replay_eligibility before using this as tuning evidence"
        elif outcome_count > 0 and eligible_count == 0:
            status = "zero_eligible_rows"
            warning = "replay outcomes exist but zero rows are eligible for tuning; inspect coverage/provenance blockers before trusting this batch"
        return {
            "status": status,
            "outcome_count": outcome_count,
            "eligibility_count": eligibility_count,
            "eligible_count": eligible_count,
            "warning": warning,
        }

    def _resolve_replay_batch(self, replay_batch_id: int | None) -> dict[str, Any] | None:
        if replay_batch_id is not None:
            row = self.session.execute(
                text(
                    """
                    select id, name, status, as_of_start, as_of_end, completed_at
                    from historical_replay_batches
                    where id = :id
                    """
                ),
                {"id": replay_batch_id},
            ).mappings().first()
        else:
            row = self.session.execute(
                text(
                    """
                    select b.id, b.name, b.status, b.as_of_start, b.as_of_end, b.completed_at
                    from historical_replay_batches b
                    where b.status = 'completed'
                      and exists (
                        select 1
                        from replay_plan_outcomes rpo
                        where rpo.replay_batch_id = b.id
                      )
                    order by b.as_of_end desc, b.completed_at desc nulls last, b.id desc
                    limit 1
                    """
                )
            ).mappings().first()
        return dict(row) if row is not None else None

    def _load_rows(self, batch_id: int) -> list[ReplayActionabilityPlanRow]:
        rows = self.session.execute(
            text(
                """
                select hs.as_of,
                       p.ticker,
                       p.action,
                       p.confidence_percent,
                       p.entry_price_low,
                       p.entry_price_high,
                       p.stop_loss,
                       p.take_profit,
                       p.signal_breakdown_json,
                       p.evidence_summary_json,
                       rpo.outcome,
                       rpo.status as outcome_status
                from replay_plan_outcomes rpo
                join recommendation_plans p on p.id = rpo.recommendation_plan_id
                join historical_replay_slices hs on hs.id = rpo.replay_slice_id
                where rpo.replay_batch_id = :batch_id
                order by hs.as_of, p.ticker, p.id
                """
            ),
            {"batch_id": batch_id},
        ).all()
        return [
            ReplayActionabilityPlanRow(
                as_of=row.as_of,
                ticker=str(row.ticker),
                action=str(row.action),
                confidence_percent=float(row.confidence_percent or 0.0),
                entry_price_low=float(row.entry_price_low) if row.entry_price_low is not None else None,
                entry_price_high=float(row.entry_price_high) if row.entry_price_high is not None else None,
                stop_loss=float(row.stop_loss) if row.stop_loss is not None else None,
                take_profit=float(row.take_profit) if row.take_profit is not None else None,
                signal_breakdown=self._json_dict(row.signal_breakdown_json),
                evidence_summary=self._json_dict(row.evidence_summary_json),
                outcome=str(row.outcome),
                outcome_status=str(row.outcome_status),
            )
            for row in rows
        ]

    def _summarize(self, rows: list[ReplayActionabilityPlanRow], floor: float) -> dict[str, Any]:
        selected: list[ReplayActionabilityPlanRow] = [row for row in rows if self._effective_action(row, floor)]
        outcomes: Counter[str] = Counter()
        tickers: Counter[str] = Counter()
        setup_families: Counter[str] = Counter()
        by_ticker: dict[str, Counter[str]] = defaultdict(Counter)
        ev = 0.0
        wins = 0
        losses = 0
        missing_levels = 0
        for row in selected:
            outcome = self._normalized_outcome(row)
            outcomes[outcome] += 1
            tickers[row.ticker] += 1
            setup = str(row.evidence_summary.get("setup_family") or row.signal_breakdown.get("setup_family") or "unknown")
            setup_families[setup] += 1
            by_ticker[row.ticker][outcome] += 1
            risk_reward = self._risk_reward(row)
            if risk_reward is None:
                missing_levels += 1
                continue
            risk, reward = risk_reward
            if outcome == "win":
                wins += 1
                ev += reward
            elif outcome == "loss":
                losses += 1
                ev -= risk
        resolved_count = wins + losses
        no_entry = int(outcomes.get("no_entry", 0))
        top_ticker_count = tickers.most_common(1)[0][1] if tickers else 0
        return {
            "floor": floor,
            "actionable_count": len(selected),
            "wins": wins,
            "losses": losses,
            "resolved_count": resolved_count,
            "resolved_win_rate_percent": round((wins / resolved_count) * 100.0, 2) if resolved_count else None,
            "ev_percent_points": round(ev, 4),
            "ev_per_actionable": round(ev / len(selected), 4) if selected else None,
            "resolved_ev_per_trade": round(ev / resolved_count, 4) if resolved_count else None,
            "no_entry_count": no_entry,
            "no_entry_rate_percent": round((no_entry / len(selected)) * 100.0, 2) if selected else None,
            "open_count": int(outcomes.get("open", 0) + outcomes.get("pending", 0)),
            "expired_count": int(outcomes.get("expired", 0)),
            "top_ticker_concentration_percent": round((top_ticker_count / len(selected)) * 100.0, 2) if selected else None,
            "outcomes": dict(outcomes),
            "top_tickers": tickers.most_common(20),
            "setup_families": dict(setup_families),
            "missing_level_count": missing_levels,
            "by_ticker_outcomes": {ticker: dict(counter) for ticker, counter in sorted(by_ticker.items())},
        }

    def _active_actionability_floor(self) -> float | None:
        try:
            config = PlanGenerationTuningService(self.session)._resolve_active_config_version().config  # noqa: SLF001
        except Exception:
            return None
        value = config.get("global.actionable_confidence_floor_percent")
        return float(value) if isinstance(value, (int, float)) else None

    @classmethod
    def _summary_for_floor(cls, summaries: list[dict[str, Any]], floor: float | None) -> dict[str, Any] | None:
        if floor is None:
            return None
        return min(summaries, key=lambda item: abs(float(item["floor"]) - floor), default=None)

    @staticmethod
    def _recommendation(best: dict[str, Any] | None, active: dict[str, Any] | None, *, min_resolved_trades: int) -> dict[str, Any]:
        if best is None:
            return {
                "decision": "no_change",
                "reason": "no floor met the minimum resolved-trade sample size",
                "min_resolved_trades": min_resolved_trades,
            }
        active_ev = float(active.get("ev_percent_points", 0.0)) if active else 0.0
        best_ev = float(best.get("ev_percent_points", 0.0))
        if best_ev <= active_ev:
            return {"decision": "no_change", "reason": "best eligible floor does not beat active floor EV", "candidate_floor": best["floor"]}
        return {
            "decision": "propose_paper_config",
            "reason": "best eligible floor beats active floor EV in replay rescore; operator/replay confirmation still required before promotion",
            "candidate_floor": best["floor"],
            "ev_delta_percent_points": round(best_ev - active_ev, 4),
        }

    @classmethod
    def _effective_action(cls, row: ReplayActionabilityPlanRow, floor: float) -> str | None:
        if row.confidence_percent < floor:
            return None
        if row.action in {"long", "short"}:
            return row.action
        intended = cls._intended_action(row)
        if row.action in {"no_action", "watchlist"} and intended and cls._is_threshold_blocked(row):
            return intended
        return None

    @staticmethod
    def _json_dict(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _action_reason(row: ReplayActionabilityPlanRow) -> str:
        return str(row.evidence_summary.get("action_reason") or "").strip()

    @classmethod
    def _is_threshold_blocked(cls, row: ReplayActionabilityPlanRow) -> bool:
        return cls._action_reason(row) in {"below_calibrated_action_threshold", "below_action_confidence_threshold"}

    @staticmethod
    def _intended_action(row: ReplayActionabilityPlanRow) -> str | None:
        action = str(row.signal_breakdown.get("intended_action") or "").strip().lower()
        return action if action in {"long", "short"} else None

    @staticmethod
    def _normalized_outcome(row: ReplayActionabilityPlanRow) -> str:
        if row.outcome.startswith("phantom_"):
            return row.outcome.removeprefix("phantom_")
        return row.outcome

    @staticmethod
    def _risk_reward(row: ReplayActionabilityPlanRow) -> tuple[float, float] | None:
        entry_values = [value for value in (row.entry_price_low, row.entry_price_high) if value is not None]
        if not entry_values or row.stop_loss is None or row.take_profit is None:
            return None
        entry = sum(float(value) for value in entry_values) / len(entry_values)
        if entry <= 0:
            return None
        risk = abs((entry - float(row.stop_loss)) / entry) * 100.0
        reward = abs((float(row.take_profit) - entry) / entry) * 100.0
        if risk <= 0 or reward <= 0:
            return None
        return risk, reward
