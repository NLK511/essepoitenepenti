#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trade_proposer_app.services.phantom_selectivity_promotion_preflight import (
    build_phantom_selectivity_promotion_preflight,
)


def _read_json(path: Path | None) -> dict[str, object] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a read-only phantom selectivity promotion preflight artifact."
    )
    parser.add_argument("--candidate-replay-artifact", type=Path, required=True)
    parser.add_argument("--evidence-lineage-artifact", type=Path)
    parser.add_argument("--driver-quality-artifact", type=Path)
    parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args()

    candidate_replay = _read_json(args.candidate_replay_artifact)
    if candidate_replay is None:
        raise FileNotFoundError(args.candidate_replay_artifact)
    evidence_lineage = _read_json(args.evidence_lineage_artifact)
    driver_quality = _read_json(args.driver_quality_artifact)
    report = build_phantom_selectivity_promotion_preflight(
        candidate_replay=candidate_replay,
        evidence_lineage=evidence_lineage,
        driver_quality=driver_quality,
        source_artifacts={
            "candidate_replay": str(args.candidate_replay_artifact),
            "evidence_lineage": str(args.evidence_lineage_artifact or ""),
            "driver_quality": str(args.driver_quality_artifact or ""),
        },
    )
    _write_json(args.artifact, report)
    print(
        json.dumps(
            {
                "artifact": str(args.artifact),
                "verdict": report["verdict"],
                "blockers": report["blockers"],
                "warnings": report["warnings"],
                "decision": report["decision"],
                "proposed_shadow_policy": report["proposed_shadow_policy"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
