import json
import subprocess
import unittest
from unittest.mock import patch

from trade_proposer_app.services.preflight import PrototypePreflightService


class PrototypePreflightServiceTests(unittest.TestCase):
    def test_run_reports_missing_required_imports_as_failed(self) -> None:
        results = [
            subprocess.CompletedProcess(args=["python3"], returncode=0, stdout=json.dumps(["yfinance"]), stderr=""),
            subprocess.CompletedProcess(args=["python3"], returncode=0, stdout=json.dumps([]), stderr=""),
        ]

        with patch("trade_proposer_app.services.preflight.Path.exists", return_value=True), patch(
            "trade_proposer_app.services.preflight.shutil.which", return_value="/usr/bin/python3"
        ), patch("trade_proposer_app.services.preflight.subprocess.run", side_effect=results):
            report = PrototypePreflightService().run()

        self.assertEqual(report.status, "failed")
        required = next(check for check in report.checks if check.name == "python_imports:required")
        self.assertEqual(required.status, "failed")
        self.assertIn("yfinance", required.message)

    def test_run_reports_missing_optional_imports_as_warning(self) -> None:
        results = [
            subprocess.CompletedProcess(args=["python3"], returncode=0, stdout=json.dumps([]), stderr=""),
            subprocess.CompletedProcess(args=["python3"], returncode=0, stdout=json.dumps(["openai"]), stderr=""),
        ]

        with patch("trade_proposer_app.services.preflight.Path.exists", return_value=True), patch(
            "trade_proposer_app.services.preflight.shutil.which", return_value="/usr/bin/python3"
        ), patch("trade_proposer_app.services.preflight.subprocess.run", side_effect=results):
            report = PrototypePreflightService().run()

        self.assertEqual(report.status, "warning")
        optional = next(check for check in report.checks if check.name == "python_imports:optional")
        self.assertEqual(optional.status, "warning")
        self.assertIn("openai", optional.message)


if __name__ == "__main__":
    unittest.main()
