import json
import unittest

from trade_proposer_app.domain.enums import RecommendationDirection, StrategyHorizon
from trade_proposer_app.domain.models import Recommendation, RunDiagnostics, RunOutput
from trade_proposer_app.services.ticker_deep_analysis import TickerDeepAnalysisService


class StubProposalService:
    def generate(self, ticker: str) -> RunOutput:
        return RunOutput(
            recommendation=Recommendation(
                ticker=ticker,
                direction=RecommendationDirection.LONG,
                confidence=77.0,
                entry_price=100.0,
                stop_loss=96.0,
                take_profit=109.0,
                indicator_summary="deep analysis stub",
            ),
            diagnostics=RunDiagnostics(
                analysis_json=json.dumps({"summary": {"text": "stub analysis"}}),
                raw_output=json.dumps({"summary": {"text": "stub analysis"}}),
            ),
        )


class TickerDeepAnalysisServiceTests(unittest.TestCase):
    def test_analyze_annotates_output_with_model_and_horizon(self) -> None:
        service = TickerDeepAnalysisService(StubProposalService())

        output = service.analyze("AAPL", horizon=StrategyHorizon.ONE_WEEK)
        payload = json.loads(output.diagnostics.analysis_json or "{}")

        self.assertEqual(payload["ticker_deep_analysis"]["model"], "ticker_deep_analysis_v1")
        self.assertEqual(payload["ticker_deep_analysis"]["delegated_to"], "proposal_service")
        self.assertEqual(payload["ticker_deep_analysis"]["horizon"], "1w")
        self.assertEqual(output.diagnostics.analysis_json, output.diagnostics.raw_output)


if __name__ == "__main__":
    unittest.main()
