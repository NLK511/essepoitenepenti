from __future__ import annotations

import unittest
from unittest.mock import patch

from trade_proposer_app.domain.enums import JobType
from trade_proposer_app.services.taxonomy import TickerTaxonomyService


class LegacyWeightOptimizationRetirementTests(unittest.TestCase):
    def setUp(self) -> None:
        TickerTaxonomyService._shared_payload_cache.clear()

    def tearDown(self) -> None:
        TickerTaxonomyService._shared_payload_cache.clear()

    def test_weight_optimization_job_type_is_retired(self) -> None:
        self.assertFalse(hasattr(JobType, "WEIGHT_OPTIMIZATION"))

    def test_plan_generation_tuning_job_type_replaces_legacy_optimizer(self) -> None:
        self.assertEqual(JobType.PLAN_GENERATION_TUNING.value, "plan_generation_tuning")

    def test_taxonomy_payload_is_shared_across_instances(self) -> None:
        original_load_payload = TickerTaxonomyService._load_payload
        calls = 0

        def tracking_load_payload(self):
            nonlocal calls
            calls += 1
            return original_load_payload(self)

        with patch.object(TickerTaxonomyService, "_load_payload", new=tracking_load_payload):
            first = TickerTaxonomyService()
            second = TickerTaxonomyService()

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
