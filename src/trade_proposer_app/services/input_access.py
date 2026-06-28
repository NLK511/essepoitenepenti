from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

InputAccessPolicy = Literal["cache_only", "cache_then_remote", "remote_refresh", "fail_if_missing"]
CoverageTier = Literal["tier_a", "tier_b", "tier_c", "ineligible"]


@dataclass(frozen=True)
class ArtifactProvenance:
    as_of: str | None
    source: str
    input_coverage_hash: str
    code_version: str | None = None
    settings_hash: str | None = None
    replay_batch_id: int | None = None
    replay_slice_id: int | None = None
    plan_generation_config_hash: str | None = None

    MANDATORY_REPLAY_FIELDS = ("as_of", "code_version", "settings_hash", "input_coverage_hash")

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ArtifactProvenance":
        return cls(
            as_of=str(payload.get("as_of")) if payload.get("as_of") is not None else None,
            source=str(payload.get("source") or "unknown"),
            input_coverage_hash=str(payload.get("input_coverage_hash") or ""),
            code_version=str(payload.get("code_version")) if payload.get("code_version") is not None else None,
            settings_hash=str(payload.get("settings_hash")) if payload.get("settings_hash") is not None else None,
            replay_batch_id=cls._int_or_none(payload.get("replay_batch_id")),
            replay_slice_id=cls._int_or_none(payload.get("replay_slice_id")),
            plan_generation_config_hash=(
                str(payload.get("plan_generation_config_hash"))
                if payload.get("plan_generation_config_hash") is not None
                else None
            ),
        )

    def missing_replay_mandatory_fields(self) -> list[str]:
        values = self.to_dict()
        return [field for field in self.MANDATORY_REPLAY_FIELDS if not values.get(field)]

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "source": self.source,
            "input_coverage_hash": self.input_coverage_hash,
            "code_version": self.code_version,
            "settings_hash": self.settings_hash,
            "replay_batch_id": self.replay_batch_id,
            "replay_slice_id": self.replay_slice_id,
            "plan_generation_config_hash": self.plan_generation_config_hash,
        }

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True)
class TickerCoverageReport:
    ticker: str
    tier: CoverageTier
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str = "cache"
    generation: dict[str, object] = field(default_factory=dict)
    resolution: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "tier": self.tier,
            "source": self.source,
            "generation": self.generation,
            "resolution": self.resolution,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class InputCoverageReport:
    as_of: str
    ticker_count: int
    tier_counts: dict[str, int]
    tickers: list[dict[str, object]]
    policy: str = "cache_only"
    source: str = "cache"
    lookback_days: int | None = None
    resolution_days: int | None = None
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def tier_a_ratio(self) -> float:
        return round((int(self.tier_counts.get("tier_a", 0)) / self.ticker_count) if self.ticker_count else 0.0, 4)

    def to_dict(self) -> dict[str, object]:
        payload = {
            "as_of": self.as_of,
            "policy": self.policy,
            "source": self.source,
            "ticker_count": self.ticker_count,
            "tier_counts": dict(self.tier_counts),
            "tier_a_ratio": self.tier_a_ratio,
            "tickers": list(self.tickers),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }
        if self.lookback_days is not None:
            payload["lookback_days"] = self.lookback_days
        if self.resolution_days is not None:
            payload["resolution_days"] = self.resolution_days
        payload["input_coverage_hash"] = stable_hash(payload)
        return payload


@dataclass(frozen=True)
class InputAccessResult:
    data: object
    coverage: dict[str, object]
    provenance: dict[str, object]
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


def normalize_input_access_policy(value: object, default: InputAccessPolicy = "cache_then_remote") -> InputAccessPolicy:
    normalized = str(value or default).strip().lower().replace("-", "_")
    if normalized in {"cache_only", "cache_then_remote", "remote_refresh", "fail_if_missing"}:
        return normalized  # type: ignore[return-value]
    return default


def stable_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def isoformat(value: datetime) -> str:
    return value.isoformat()
