from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "validate_etoro_demo_integration.py"
)
spec = importlib.util.spec_from_file_location("validate_etoro_demo_integration", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
validation = importlib.util.module_from_spec(spec)
sys.modules["validate_etoro_demo_integration"] = validation
spec.loader.exec_module(validation)


class FakeEtoroClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_demo_pnl(self):
        self.calls.append("demo_pnl")
        return {"equity": 1000, "permissions": ["demo_trading"], "x-user-key": "secret"}

    def get_demo_portfolio(self):
        self.calls.append("demo_portfolio")
        return {"positions": [], "orders": []}

    def search_market_data(self, symbol):
        self.calls.append(f"search:{symbol}")
        return {"items": [{"symbol": symbol.upper(), "instrumentId": 123, "tradable": True}]}

    def get_instrument_display_data(self, instrument_id):
        self.calls.append(f"display:{instrument_id}")
        return {
            "instrumentDisplayDatas": [
                {
                    "instrumentID": instrument_id,
                    "symbolFull": "AAPL",
                    "instrumentDisplayName": "Apple",
                    "priceSource": "NASDAQ",
                }
            ]
        }

    def get_market_rates(self, instrument_ids):
        self.calls.append(f"rates:{instrument_ids[0]}")
        return {"rates": [{"instrumentID": instrument_ids[0], "bid": 99, "ask": 101}]}

    def check_demo_eligibility(self, payload):
        self.calls.append("eligibility")
        return {"eligible": True, "payload": payload}

    def get_demo_costs(self, payload):
        self.calls.append("costs")
        return {"costs": [], "payload": payload}

    def submit_demo_order(self, payload):
        self.calls.append("submit")
        return {"orderId": "order-1", "referenceId": "ref-1", "payload": payload}

    def lookup_demo_order(self, order_id=None, reference_id=None):
        self.calls.append("lookup")
        return {
            "orderId": order_id,
            "referenceId": reference_id,
            "positionExecutions": [{"positionId": "position-1"}],
        }

    def close_demo_position(self, position_id, instrument_id=None):
        self.calls.append(f"close:{position_id}:{instrument_id}")
        return {"positionId": position_id, "status": "closing"}


def test_read_only_demo_validation_artifact_redacts_secrets_and_records_openapi() -> None:
    client = FakeEtoroClient()

    report = validation.validate(
        client=client,
        symbol="AAPL",
        amount_usd=25.0,
        submit_demo_order=False,
        close_after_submit=False,
        stop_loss_rate=None,
        take_profit_rate=None,
        openapi_version="v1.311.0",
    )

    assert report["status"] == "passed"
    assert report["openapi"]["version_matches_expected"] is True
    assert report["instrument_resolution"]["status"] == "matched"
    assert "secret" not in repr(report)
    assert "submit" not in client.calls


def test_submit_demo_order_requires_protective_levels() -> None:
    client = FakeEtoroClient()

    report = validation.validate(
        client=client,
        symbol="AAPL",
        amount_usd=25.0,
        submit_demo_order=True,
        close_after_submit=True,
        stop_loss_rate=None,
        take_profit_rate=110.0,
        openapi_version="v1.311.0",
    )

    assert report["status"] == "failed"
    assert report["steps"][-1] == {
        "name": "demo_order_submission",
        "status": "skipped",
        "reason": "stop_loss_and_take_profit_required",
    }
    assert "submit" not in client.calls


def test_controlled_demo_submit_lookup_and_close_are_recorded() -> None:
    client = FakeEtoroClient()

    report = validation.validate(
        client=client,
        symbol="AAPL",
        amount_usd=25.0,
        submit_demo_order=True,
        close_after_submit=True,
        stop_loss_rate=95.0,
        take_profit_rate=110.0,
        openapi_version="v1.311.0",
    )

    step_names = [step["name"] for step in report["steps"]]
    assert report["status"] == "passed"
    assert "demo_order_submission" in step_names
    assert "demo_order_lookup" in step_names
    assert "demo_position_close" in step_names
    assert "close:position-1:123" in client.calls


def test_refuses_ambiguous_instrument_before_submission() -> None:
    class AmbiguousClient(FakeEtoroClient):
        def search_market_data(self, symbol):
            self.calls.append(f"search:{symbol}")
            return {
                "items": [
                    {"symbol": symbol.upper(), "instrumentId": 123},
                    {"symbol": symbol.upper(), "instrumentId": 456},
                ]
            }

    client = AmbiguousClient()

    report = validation.validate(
        client=client,
        symbol="AAPL",
        amount_usd=25.0,
        submit_demo_order=True,
        close_after_submit=False,
        stop_loss_rate=95.0,
        take_profit_rate=110.0,
        openapi_version="v1.311.0",
    )

    assert report["status"] == "failed"
    assert report["instrument_resolution"]["status"] == "ambiguous"
    assert "submit" not in client.calls


def test_enriches_current_etoro_search_shape_before_prechecks() -> None:
    class ThinSearchClient(FakeEtoroClient):
        def search_market_data(self, symbol):
            self.calls.append(f"search:{symbol}")
            return {"items": [{"instrumentId": 1001}, {"instrumentId": 15569}]}

        def get_instrument_display_data(self, instrument_id):
            self.calls.append(f"display:{instrument_id}")
            symbol = "AAPL" if str(instrument_id) == "1001" else "AAPL.24-7"
            return {
                "instrumentDisplayDatas": [
                    {
                        "instrumentID": instrument_id,
                        "symbolFull": symbol,
                        "instrumentDisplayName": "Apple",
                        "priceSource": "NASDAQ",
                    }
                ]
            }

    client = ThinSearchClient()

    report = validation.validate(
        client=client,
        symbol="AAPL",
        amount_usd=25.0,
        submit_demo_order=False,
        close_after_submit=False,
        stop_loss_rate=None,
        take_profit_rate=None,
        openapi_version="v1.311.0",
    )

    assert report["status"] == "passed"
    assert report["instrument_resolution"]["status"] == "matched"
    assert "display:1001" in client.calls
