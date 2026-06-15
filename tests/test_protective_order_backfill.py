from scripts.backfill_broker_position_protective_orders import extract_protective_order_evidence


def test_extract_protective_order_evidence_from_broker_neutral_legs() -> None:
    evidence = extract_protective_order_evidence(
        {
            "legs": [
                {"id": "tp-1", "type": "limit", "status": "new", "limit_price": "110.00"},
                {"id": "sl-1", "type": "stop", "status": "new", "stop_price": "95.00"},
            ]
        }
    )

    assert evidence["take_profit_order_id"] == "tp-1"
    assert evidence["take_profit_order_status"] == "new"
    assert evidence["take_profit_order_price"] == 110.0
    assert evidence["stop_loss_order_id"] == "sl-1"
    assert evidence["stop_loss_order_status"] == "new"
    assert evidence["stop_loss_order_price"] == 95.0
    assert evidence["protective_orders_source"] == "broker_order_legs_backfill"


def test_extract_protective_order_evidence_returns_empty_for_missing_legs() -> None:
    assert extract_protective_order_evidence({"id": "parent"}) == {}
