import unittest
from unittest.mock import patch

from trade_proposer_app.services.preflight import AppPreflightService


class AppPreflightServiceTests(unittest.TestCase):
    def test_run_reports_missing_module_as_failed(self) -> None:
        def fake_find_spec(name: str):
            return None if name == "pandas" else object()

        with patch(
            "trade_proposer_app.services.preflight.importlib.util.find_spec",
            side_effect=fake_find_spec,
        ), patch("trade_proposer_app.services.preflight.Path.exists", return_value=True):
            report = AppPreflightService().run()

        self.assertEqual(report.status, "failed")
        module_check = next(check for check in report.checks if check.name == "module:pandas")
        self.assertEqual(module_check.status, "failed")
        self.assertIn("pandas", module_check.message)

    def test_run_reports_missing_weights_file_as_failed(self) -> None:
        with patch(
            "trade_proposer_app.services.preflight.importlib.util.find_spec",
            return_value=object(),
        ), patch("trade_proposer_app.services.preflight.Path.exists", return_value=False):
            report = AppPreflightService().run()

        self.assertEqual(report.status, "failed")
        weights_check = next(check for check in report.checks if check.name == "weights_file")
        self.assertEqual(weights_check.status, "failed")
        self.assertIn("weights.json", weights_check.message)


if __name__ == "__main__":
    unittest.main()
