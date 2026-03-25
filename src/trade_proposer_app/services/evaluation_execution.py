import json

from trade_proposer_app.domain.models import EvaluationRunResult, Run


class EvaluationExecutionService:
    def __init__(self, recommendation_evaluations=None, recommendation_plan_evaluations=None) -> None:
        self.recommendation_evaluations = recommendation_evaluations
        self.recommendation_plan_evaluations = recommendation_plan_evaluations

    def execute(self, run: Run) -> EvaluationRunResult:
        scope_type = self._extract_scope_type(run)
        recommendation_ids = self._extract_ids(run, key="recommendation_ids")
        recommendation_plan_ids = self._extract_ids(run, key="recommendation_plan_ids")

        recommendation_result = EvaluationRunResult()
        if self.recommendation_evaluations is not None and scope_type not in {"recommendation_plan_ids", "all_recommendation_plans"}:
            recommendation_result = self.recommendation_evaluations.run_evaluation(recommendation_ids=recommendation_ids)

        recommendation_plan_result = EvaluationRunResult()
        if self.recommendation_plan_evaluations is not None and scope_type not in {"recommendation_ids"}:
            recommendation_plan_result = self.recommendation_plan_evaluations.run_evaluation(
                recommendation_plan_ids=recommendation_plan_ids,
                run_id=run.id,
            )

        return EvaluationRunResult(
            evaluated_trade_log_entries=recommendation_result.evaluated_trade_log_entries,
            synced_recommendations=recommendation_result.synced_recommendations,
            pending_recommendations=recommendation_result.pending_recommendations,
            win_recommendations=recommendation_result.win_recommendations,
            loss_recommendations=recommendation_result.loss_recommendations,
            evaluated_recommendation_plans=recommendation_plan_result.evaluated_recommendation_plans,
            synced_recommendation_plan_outcomes=recommendation_plan_result.synced_recommendation_plan_outcomes,
            pending_recommendation_plan_outcomes=recommendation_plan_result.pending_recommendation_plan_outcomes,
            win_recommendation_plan_outcomes=recommendation_plan_result.win_recommendation_plan_outcomes,
            loss_recommendation_plan_outcomes=recommendation_plan_result.loss_recommendation_plan_outcomes,
            no_action_recommendation_plan_outcomes=recommendation_plan_result.no_action_recommendation_plan_outcomes,
            watchlist_recommendation_plan_outcomes=recommendation_plan_result.watchlist_recommendation_plan_outcomes,
            output=self._merge_output(recommendation_result.output, recommendation_plan_result.output),
        )

    @staticmethod
    def _extract_scope_type(run: Run) -> str | None:
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
        value = scope.get("type")
        return value if isinstance(value, str) else None

    @staticmethod
    def _extract_ids(run: Run, *, key: str) -> list[int] | None:
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
        values = scope.get(key)
        if not isinstance(values, list):
            return None
        normalized = [int(item) for item in values if isinstance(item, int) or (isinstance(item, str) and item.isdigit())]
        return normalized or None

    @staticmethod
    def _merge_output(*parts: str) -> str:
        normalized = [part.strip() for part in parts if isinstance(part, str) and part.strip()]
        return "\n\n".join(normalized)
