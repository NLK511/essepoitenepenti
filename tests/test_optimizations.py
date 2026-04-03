from __future__ import annotations

import unittest

from trade_proposer_app.domain.enums import JobType


class LegacyWeightOptimizationRetirementTests(unittest.TestCase):
    def test_weight_optimization_job_type_is_retired(self) -> None:
        self.assertFalse(hasattr(JobType, "WEIGHT_OPTIMIZATION"))

    def test_plan_generation_tuning_job_type_replaces_legacy_optimizer(self) -> None:
        self.assertEqual(JobType.PLAN_GENERATION_TUNING.value, "plan_generation_tuning")


if __name__ == "__main__":
    unittest.main()
