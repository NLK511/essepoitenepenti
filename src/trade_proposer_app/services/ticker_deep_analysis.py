from __future__ import annotations

import json
from typing import Any

from trade_proposer_app.domain.enums import StrategyHorizon
from trade_proposer_app.domain.models import RunDiagnostics, RunOutput
from trade_proposer_app.services.proposals import ProposalService


class TickerDeepAnalysisError(Exception):
    pass


class TickerDeepAnalysisService:
    def __init__(
        self,
        proposal_service: ProposalService,
        *,
        model_name: str = "ticker_deep_analysis_v1",
    ) -> None:
        self.proposal_service = proposal_service
        self.model_name = model_name

    def analyze(self, ticker: str, *, horizon: StrategyHorizon | None = None) -> RunOutput:
        try:
            output = self.proposal_service.generate(ticker)
        except Exception as exc:  # noqa: BLE001
            raise TickerDeepAnalysisError(str(exc)) from exc
        return self._annotate_output(output, horizon=horizon)

    def _annotate_output(self, output: RunOutput, *, horizon: StrategyHorizon | None) -> RunOutput:
        diagnostics = output.diagnostics
        analysis_payload = self._load_json(diagnostics.analysis_json)
        if isinstance(analysis_payload, dict):
            analysis_payload["ticker_deep_analysis"] = {
                "model": self.model_name,
                "delegated_to": "proposal_service",
                "horizon": horizon.value if horizon is not None else None,
            }
            serialized = json.dumps(analysis_payload, indent=2, sort_keys=True)
            diagnostics = diagnostics.model_copy(update={"analysis_json": serialized, "raw_output": serialized})
        else:
            diagnostics = diagnostics.model_copy(
                update={
                    "warnings": list(dict.fromkeys([*diagnostics.warnings, "ticker deep analysis completed without structured analysis payload"])),
                }
            )
        return output.model_copy(update={"diagnostics": diagnostics})

    @staticmethod
    def _load_json(raw: str | None) -> dict[str, Any] | None:
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
