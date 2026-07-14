#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from trade_proposer_app.db import SessionLocal
from trade_proposer_app.services.plan_generation_tuning import PlanGenerationTuningService
from trade_proposer_app.services.plan_generation_tuning_parameters import (
    normalize_plan_generation_tuning_config,
)
from trade_proposer_app.services.tuning_evidence_partitions import evidence_date, stable_hash


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _load_candidate_config(path: Path | None, rank: int) -> dict[str, float] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidates = payload.get("top_candidates")
    if not isinstance(candidates, list) or not candidates:
        raise SystemExit(f"no top_candidates in {path}")
    index = max(1, int(rank)) - 1
    if index >= len(candidates):
        raise SystemExit(f"candidate rank {rank} out of range for {path}")
    config = candidates[index].get("config")
    if not isinstance(config, dict):
        raise SystemExit(f"candidate rank {rank} has no config in {path}")
    return normalize_plan_generation_tuning_config(config)


def _bucket() -> dict[str, Any]:
    return {
        "records": 0,
        "baseline_actionable": 0,
        "baseline_wins": 0,
        "baseline_losses": 0,
        "baseline_ev_total": 0.0,
        "candidate_actionable": 0,
        "candidate_wins": 0,
        "candidate_losses": 0,
        "candidate_ev_total": 0.0,
        "overlap_actionable": 0,
        "candidate_only_actionable": 0,
        "baseline_only_actionable": 0,
    }


def _apply_resolution(
    bucket: dict[str, Any],
    prefix: str,
    resolution: tuple[str, float, float] | None,
) -> None:
    if resolution is None:
        return
    outcome, reward_pct, risk_pct = resolution
    bucket[f"{prefix}_actionable"] += 1
    if outcome == "win":
        bucket[f"{prefix}_wins"] += 1
        bucket[f"{prefix}_ev_total"] += float(reward_pct)
    else:
        bucket[f"{prefix}_losses"] += 1
        bucket[f"{prefix}_ev_total"] -= float(risk_pct)


def _finalize(bucket: dict[str, Any]) -> dict[str, Any]:
    output = dict(bucket)
    for prefix in ("baseline", "candidate"):
        actionable = int(output.get(f"{prefix}_actionable") or 0)
        wins = int(output.get(f"{prefix}_wins") or 0)
        ev_total = round(float(output.get(f"{prefix}_ev_total") or 0.0), 4)
        output[f"{prefix}_ev_total"] = ev_total
        output[f"{prefix}_win_rate_percent"] = (
            round(wins / actionable * 100.0, 4) if actionable else None
        )
        output[f"{prefix}_ev_per_actionable"] = (
            round(ev_total / actionable, 6) if actionable else None
        )
    output["candidate_ev_delta"] = round(
        float(output["candidate_ev_total"]) - float(output["baseline_ev_total"]), 4
    )
    candidate_wr = output.get("candidate_win_rate_percent")
    baseline_wr = output.get("baseline_win_rate_percent")
    output["candidate_win_rate_delta"] = (
        round(float(candidate_wr) - float(baseline_wr), 4)
        if candidate_wr is not None and baseline_wr is not None
        else None
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Report plan-generation tuning evidence coverage and recent loser concentration."
        )
    )
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--candidate-artifact", type=Path)
    parser.add_argument("--candidate-rank", type=int, default=1)
    parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args()

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    candidate_config = _load_candidate_config(args.candidate_artifact, args.candidate_rank)

    session = SessionLocal()
    try:
        service = PlanGenerationTuningService(session)
        baseline_version = service._resolve_active_config_version()  # noqa: SLF001
        baseline_config = normalize_plan_generation_tuning_config(baseline_version.config)
        if candidate_config is None:
            candidate_config = baseline_config

        records = service._eligible_records(ticker=None, setup_family=None, limit=None)  # noqa: SLF001
        filtered = [
            record
            for record in records
            if (start is None or evidence_date(record) >= start)
            and (end is None or evidence_date(record) <= end)
        ]

        overall = _bucket()
        by_date: dict[str, dict[str, Any]] = defaultdict(_bucket)
        by_setup: dict[str, dict[str, Any]] = defaultdict(_bucket)
        by_ticker: dict[str, dict[str, Any]] = defaultdict(_bucket)
        candidate_only_losses: dict[str, dict[str, Any]] = defaultdict(_bucket)

        for record in filtered:
            day = evidence_date(record).isoformat()
            setup = str(getattr(record, "setup_family", "") or "unknown")
            ticker = str(getattr(record.plan, "ticker", "") or "unknown")
            baseline = service._candidate_resolution(record, baseline_config)  # noqa: SLF001
            candidate = service._candidate_resolution(record, candidate_config)  # noqa: SLF001
            buckets = [overall, by_date[day], by_setup[setup], by_ticker[ticker]]
            for bucket in buckets:
                bucket["records"] += 1
                _apply_resolution(bucket, "baseline", baseline)
                _apply_resolution(bucket, "candidate", candidate)
                if baseline is not None and candidate is not None:
                    bucket["overlap_actionable"] += 1
                elif baseline is None and candidate is not None:
                    bucket["candidate_only_actionable"] += 1
                elif baseline is not None and candidate is None:
                    bucket["baseline_only_actionable"] += 1

            if baseline is None and candidate is not None and candidate[0] != "win":
                loss_bucket = candidate_only_losses[setup]
                loss_bucket["records"] += 1
                _apply_resolution(loss_bucket, "candidate", candidate)

        output = {
            "generated_at": datetime.now(UTC).isoformat(),
            "window": {
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
            },
            "baseline_config_version_id": baseline_version.id,
            "candidate_config_hash": stable_hash(candidate_config),
            "record_count": len(filtered),
            "distinct_date_count": len({evidence_date(record) for record in filtered}),
            "overall": _finalize(overall),
            "by_date": {key: _finalize(value) for key, value in sorted(by_date.items())},
            "by_setup_family": {
                key: _finalize(value)
                for key, value in sorted(
                    by_setup.items(), key=lambda item: item[1]["candidate_ev_total"]
                )
            },
            "by_ticker_top_losses": {
                key: _finalize(value)
                for key, value in sorted(
                    by_ticker.items(), key=lambda item: item[1]["candidate_ev_total"]
                )[:25]
            },
            "candidate_only_losses_by_setup_family": {
                key: _finalize(value)
                for key, value in sorted(
                    candidate_only_losses.items(),
                    key=lambda item: item[1]["candidate_ev_total"],
                )
            },
        }
        args.artifact.parent.mkdir(parents=True, exist_ok=True)
        args.artifact.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
        print(
            json.dumps(
                {
                    "artifact": str(args.artifact),
                    "record_count": output["record_count"],
                    "distinct_date_count": output["distinct_date_count"],
                    "overall": output["overall"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
