import json

from trade_proposer_app.domain.models import EvaluationRunResult, Run
from trade_proposer_app.services.evaluations import RecommendationEvaluationService


class EvaluationExecutionService:
    def __init__(self, evaluations: RecommendationEvaluationService) -> None:
        self.evaluations = evaluations

    def execute(self, run: Run) -> EvaluationRunResult:
        recommendation_ids = self._extract_recommendation_ids(run)
        return self.evaluations.run_evaluation(recommendation_ids=recommendation_ids)

    @staticmethod
    def _extract_recommendation_ids(run: Run) -> list[int] | None:
        if not run.artifact_json:
            return None
        try:
            artifact = json.loads(run.artifact_json)
        except json.JSONDecodeError:
            return None
        if not isinstance(artifact, dict):
            return None
        scope = artifact.get("scope")
        if not isinstance(scope, dict):
            return None
        recommendation_ids = scope.get("recommendation_ids")
        if not isinstance(recommendation_ids, list):
            return None
        normalized = [int(item) for item in recommendation_ids if isinstance(item, int) or (isinstance(item, str) and item.isdigit())]
        return normalized or None
