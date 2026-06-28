from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class JsonEnvelopeValidationResult:
    payload: dict[str, object]
    missing_fields: list[str]
    degraded: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "degraded": self.degraded,
            "missing_fields": list(self.missing_fields),
        }


class JsonArtifactValidationService:
    REPLAY_INPUT_REQUIRED = ("replay_batch_id", "replay_slice_id", "as_of", "replay_coverage_report")
    REPLAY_OUTPUT_REQUIRED = ("batch_id", "slice_id", "pipeline_stage")
    RUN_ARTIFACT_REQUIRED = ("historical_replay",)
    REPLAY_DIAGNOSTICS_REQUIRED = ("status",)
    TUNING_SUMMARY_REQUIRED = ("status",)

    @classmethod
    def validate_replay_input_summary(cls, payload: Mapping[str, object]) -> JsonEnvelopeValidationResult:
        return cls.validate("replay_input_summary", payload, cls.REPLAY_INPUT_REQUIRED)

    @classmethod
    def validate_replay_output_summary(cls, payload: Mapping[str, object]) -> JsonEnvelopeValidationResult:
        return cls.validate("replay_output_summary", payload, cls.REPLAY_OUTPUT_REQUIRED)

    @classmethod
    def validate_run_artifact(cls, payload: Mapping[str, object]) -> JsonEnvelopeValidationResult:
        return cls.validate("run_artifact", payload, cls.RUN_ARTIFACT_REQUIRED)

    @classmethod
    def validate_replay_diagnostics(cls, payload: Mapping[str, object]) -> JsonEnvelopeValidationResult:
        return cls.validate("replay_diagnostics", payload, cls.REPLAY_DIAGNOSTICS_REQUIRED)

    @classmethod
    def validate_tuning_summary(cls, payload: Mapping[str, object]) -> JsonEnvelopeValidationResult:
        return cls.validate("tuning_summary", payload, cls.TUNING_SUMMARY_REQUIRED)

    @staticmethod
    def validate(envelope: str, payload: Mapping[str, object], required_fields: tuple[str, ...]) -> JsonEnvelopeValidationResult:
        result = deepcopy(dict(payload))
        missing = [field for field in required_fields if not result.get(field)]
        if missing:
            result["degraded"] = True
            blockers = result.setdefault("validation_blockers", [])
            if not isinstance(blockers, list):
                blockers = [str(blockers)]
            blockers.extend(f"missing_{envelope}:{field}" for field in missing)
            result["validation_blockers"] = blockers
            result["validation"] = {
                "envelope": envelope,
                "degraded": True,
                "missing_fields": missing,
            }
        else:
            result.setdefault("validation", {"envelope": envelope, "degraded": False, "missing_fields": []})
        return JsonEnvelopeValidationResult(payload=result, missing_fields=missing, degraded=bool(missing))
