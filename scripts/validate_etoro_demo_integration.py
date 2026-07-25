#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from trade_proposer_app.services.brokers import redacted_payload  # noqa: E402
from trade_proposer_app.services.brokers.etoro import EtoroClient, EtoroClientError  # noqa: E402

EXPECTED_OPENAPI_VERSION = "v1.311.0"
OPENAPI_URL = "https://api-portal.etoro.com/api-reference/openapi.json"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate eToro Demo credentials, read paths, "
            "and optional demo order lifecycle."
        )
    )
    parser.add_argument("--symbol", default="AAPL", help="Symbol to resolve in eToro market data.")
    parser.add_argument("--amount-usd", type=float, default=25.0, help="Demo order amount.")
    parser.add_argument("--stop-loss-rate", type=float, help="Required for --submit-demo-order.")
    parser.add_argument("--take-profit-rate", type=float, help="Required for --submit-demo-order.")
    parser.add_argument(
        "--submit-demo-order",
        action="store_true",
        help="Submit a real eToro Demo order after read/precheck validation.",
    )
    parser.add_argument(
        "--close-after-submit",
        action="store_true",
        help="Try to close the demo position if submission/lookup returns a position id.",
    )
    parser.add_argument("--output", required=True, help="Write redacted validation artifact JSON.")
    parser.add_argument(
        "--openapi-version",
        default="",
        help="Observed OpenAPI version. If omitted, the script fetches the official schema.",
    )
    return parser.parse_args(argv)


def credentials_from_env(env: dict[str, str]) -> tuple[str, str]:
    api_key = env.get("ETORO_DEMO_API_KEY") or env.get("ETORO_API_KEY") or ""
    user_key = env.get("ETORO_DEMO_USER_KEY") or env.get("ETORO_USER_KEY") or ""
    return api_key.strip(), user_key.strip()


def fetch_openapi_version() -> str:
    request = urllib.request.Request(OPENAPI_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return str(payload.get("info", {}).get("version") or "")


def instrument_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    for key in ("instruments", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def display_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    value = payload.get("instrumentDisplayDatas")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def choose_instrument(
    symbol: str, payload: dict[str, object]
) -> tuple[dict[str, object] | None, str]:
    normalized = symbol.strip().upper()
    rows = instrument_rows(payload)
    matches = [
        row
        for row in rows
        if str(row.get("symbolFull") or row.get("symbol") or "").upper() == normalized
    ]
    if len(matches) == 1:
        return matches[0], "matched"
    if len(matches) > 1:
        return None, "ambiguous"
    return None, "not_found"


def enrich_instrument_candidates(
    client: EtoroClient, payload: dict[str, object]
) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for row in instrument_rows(payload):
        instrument_id = row.get("instrumentId") or row.get("instrumentID")
        if not instrument_id:
            continue
        display_payload = client.get_instrument_display_data(str(instrument_id))
        enriched.extend(display_rows(display_payload))
    return enriched


def extract_position_id(payload: dict[str, object]) -> object | None:
    position_id = (
        payload.get("positionId")
        or payload.get("positionID")
        or payload.get("position_id")
        or payload.get("brokerPositionId")
    )
    if position_id:
        return position_id
    executions = payload.get("positionExecutions")
    if isinstance(executions, list):
        for execution in executions:
            if not isinstance(execution, dict):
                continue
            position_id = (
                execution.get("positionId")
                or execution.get("positionID")
                or execution.get("position_id")
            )
            if position_id:
                return position_id
    return None


def call_step(report: dict[str, Any], name: str, func) -> dict[str, object] | None:
    try:
        payload = func()
    except EtoroClientError as exc:
        report["steps"].append(
            {
                "name": name,
                "status": "failed",
                "error_type": exc.error_type,
                "status_code": exc.status_code,
                "retry_after_seconds": exc.retry_after_seconds,
                "payload": exc.payload,
            }
        )
        return None
    report["steps"].append({"name": name, "status": "passed", "payload": redacted_payload(payload)})
    return payload


def build_demo_order_payload(
    *,
    instrument_id: str,
    amount_usd: float,
    stop_loss_rate: float,
    take_profit_rate: float,
) -> dict[str, object]:
    return {
        "action": "open",
        "transaction": "buy",
        "instrumentId": instrument_id,
        "settlementType": "real",
        "orderType": "mkt",
        "leverage": 1,
        "amount": amount_usd,
        "orderCurrency": "usd",
        "stopLossRate": stop_loss_rate,
        "takeProfitRate": take_profit_rate,
        "stopLossType": "fixed",
    }


def validate(
    *,
    client: EtoroClient,
    symbol: str,
    amount_usd: float,
    submit_demo_order: bool,
    close_after_submit: bool,
    stop_loss_rate: float | None,
    take_profit_rate: float | None,
    openapi_version: str,
) -> dict[str, object]:
    report: dict[str, Any] = {
        "status": "failed",
        "generated_at": datetime.now(UTC).isoformat(),
        "environment": "demo",
        "openapi": {
            "expected_version": EXPECTED_OPENAPI_VERSION,
            "observed_version": openapi_version,
            "version_matches_expected": openapi_version == EXPECTED_OPENAPI_VERSION,
        },
        "symbol": symbol.strip().upper(),
        "amount_usd": amount_usd,
        "submit_demo_order": submit_demo_order,
        "close_after_submit": close_after_submit,
        "steps": [],
    }

    pnl = call_step(report, "demo_pnl", client.get_demo_pnl)
    portfolio = call_step(report, "demo_portfolio", client.get_demo_portfolio)
    search = call_step(report, "instrument_search", lambda: client.search_market_data(symbol))
    if pnl is None or portfolio is None or search is None:
        return redacted_payload(report)  # type: ignore[return-value]

    instrument, instrument_status = choose_instrument(symbol, search)
    if instrument is None:
        try:
            enriched_search = {"items": enrich_instrument_candidates(client, search)}
        except EtoroClientError as exc:
            report["steps"].append(
                {
                    "name": "instrument_display_data",
                    "status": "failed",
                    "error_type": exc.error_type,
                    "status_code": exc.status_code,
                    "retry_after_seconds": exc.retry_after_seconds,
                    "payload": exc.payload,
                }
            )
            return redacted_payload(report)  # type: ignore[return-value]
        if enriched_search["items"]:
            report["steps"].append(
                {
                    "name": "instrument_display_data",
                    "status": "passed",
                    "candidate_count": len(enriched_search["items"]),
                }
            )
            instrument, instrument_status = choose_instrument(symbol, enriched_search)
    report["instrument_resolution"] = {
        "status": instrument_status,
        "instrument": redacted_payload(instrument or {}),
    }
    if instrument is None:
        return redacted_payload(report)  # type: ignore[return-value]
    instrument_id = str(
        instrument.get("instrumentId")
        or instrument.get("instrumentID")
        or instrument.get("instrument_id")
        or ""
    )
    if not instrument_id:
        report["instrument_resolution"]["status"] = "missing_instrument_id"
        return redacted_payload(report)  # type: ignore[return-value]

    call_step(report, "market_rates", lambda: client.get_market_rates([instrument_id]))
    call_step(
        report,
        "demo_eligibility",
        lambda: client.check_demo_eligibility({"instrumentIds": [instrument_id]}),
    )
    call_step(
        report,
        "demo_costs",
        lambda: client.get_demo_costs(
            {
                "action": "open",
                "transaction": "buy",
                "instrumentId": instrument_id,
                "settlementType": "real",
                "orderType": "mkt",
                "leverage": 1,
                "amount": amount_usd,
                "orderCurrency": "usd",
            }
        ),
    )

    if submit_demo_order:
        if stop_loss_rate is None or take_profit_rate is None:
            report["steps"].append(
                {
                    "name": "demo_order_submission",
                    "status": "skipped",
                    "reason": "stop_loss_and_take_profit_required",
                }
            )
            return redacted_payload(report)  # type: ignore[return-value]
        order_payload = build_demo_order_payload(
            instrument_id=instrument_id,
            amount_usd=amount_usd,
            stop_loss_rate=stop_loss_rate,
            take_profit_rate=take_profit_rate,
        )
        submitted = call_step(
            report, "demo_order_submission", lambda: client.submit_demo_order(order_payload)
        )
        if submitted is not None:
            order_id = submitted.get("orderId") or submitted.get("order_id") or submitted.get("id")
            reference_id = submitted.get("referenceId") or submitted.get("reference_id")
            lookup = call_step(
                report,
                "demo_order_lookup",
                lambda: client.lookup_demo_order(
                    order_id=str(order_id) if order_id else None,
                    reference_id=str(reference_id) if reference_id else None,
                ),
            )
            if close_after_submit:
                position_id = None
                for payload in (submitted, lookup or {}):
                    position_id = extract_position_id(payload)
                    if position_id:
                        break
                if position_id:
                    call_step(
                        report,
                        "demo_position_close",
                        lambda: client.close_demo_position(
                            str(position_id), instrument_id=instrument_id
                        ),
                    )
                else:
                    report["steps"].append(
                        {
                            "name": "demo_position_close",
                            "status": "skipped",
                            "reason": "position_id_unavailable",
                        }
                    )

    failed_steps = [step for step in report["steps"] if step.get("status") == "failed"]
    report["status"] = "failed" if failed_steps else "passed"
    return redacted_payload(report)  # type: ignore[return-value]


def write_report(path: str, report: dict[str, object]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    env = os.environ.copy()
    configured_env = env.get("ETORO_ENV", "demo").strip().lower()
    if configured_env != "demo":
        print("ETORO_ENV must be demo for this validation script.", file=sys.stderr)
        return 2
    api_key, user_key = credentials_from_env(env)
    if not api_key or not user_key:
        print("Missing ETORO_DEMO_API_KEY/ETORO_DEMO_USER_KEY credentials.", file=sys.stderr)
        return 2
    openapi_version = args.openapi_version or fetch_openapi_version()
    report = validate(
        client=EtoroClient(api_key=api_key, user_key=user_key),
        symbol=args.symbol,
        amount_usd=args.amount_usd,
        submit_demo_order=args.submit_demo_order,
        close_after_submit=args.close_after_submit,
        stop_loss_rate=args.stop_loss_rate,
        take_profit_rate=args.take_profit_rate,
        openapi_version=openapi_version,
    )
    write_report(args.output, report)
    print(f"Wrote eToro demo validation artifact to {args.output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
