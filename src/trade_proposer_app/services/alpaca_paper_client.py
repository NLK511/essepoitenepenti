from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class AlpacaOrderSubmissionResult:
    status_code: int
    payload: dict[str, object]

    @property
    def broker_order_id(self) -> str | None:
        value = self.payload.get("id")
        return str(value) if value is not None else None

    @property
    def broker_status(self) -> str | None:
        value = self.payload.get("status")
        return str(value) if value is not None else None


class AlpacaPaperClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, payload: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class AlpacaPaperClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str = "https://paper-api.alpaca.markets", client: httpx.Client | None = None) -> None:
        self.api_key = (api_key or "").strip()
        self.api_secret = (api_secret or "").strip()
        self.base_url = base_url.rstrip("/")
        self._client = client

    def submit_order(self, payload: dict[str, Any]) -> AlpacaOrderSubmissionResult:
        return self._request("post", "/v2/orders", payload=payload)

    def get_order(self, order_id: str) -> AlpacaOrderSubmissionResult:
        return self._request("get", f"/v2/orders/{order_id}?nested=true")

    def cancel_order(self, order_id: str) -> AlpacaOrderSubmissionResult:
        return self._request("delete", f"/v2/orders/{order_id}")

    def amend_order(self, order_id: str, payload: dict[str, Any]) -> AlpacaOrderSubmissionResult:
        return self._request("patch", f"/v2/orders/{order_id}", payload=payload)

    def close_position(self, symbol: str) -> AlpacaOrderSubmissionResult:
        return self._request("delete", f"/v2/positions/{symbol}")

    def get_account(self) -> AlpacaOrderSubmissionResult:
        return self._request("get", "/v2/account")

    def list_open_orders(self) -> AlpacaOrderSubmissionResult:
        return self._request("get", "/v2/orders?status=open&nested=true", allow_list_response=True)

    def list_open_positions(self) -> AlpacaOrderSubmissionResult:
        return self._request("get", "/v2/positions", allow_list_response=True)

    def _request(self, method: str, path: str, *, payload: dict[str, Any] | None = None, allow_list_response: bool = False) -> AlpacaOrderSubmissionResult:
        if not self.api_key or not self.api_secret:
            raise AlpacaPaperClientError("alpaca api credentials are missing")

        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}{path}"
        body = json.dumps(payload) if payload is not None else None
        if self._client is not None:
            response = self._client.request(method.upper(), url, content=body, headers=headers, timeout=30.0)
        else:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(method.upper(), url, content=body, headers=headers)

        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {"raw_body": response.text}

        if response.status_code >= 400:
            raise AlpacaPaperClientError(
                f"alpaca request failed with status {response.status_code}",
                status_code=response.status_code,
                payload=response_payload if isinstance(response_payload, dict) else {"raw_body": response.text},
            )

        if not isinstance(response_payload, dict):
            if allow_list_response and isinstance(response_payload, list):
                return AlpacaOrderSubmissionResult(status_code=response.status_code, payload={"items": response_payload})
            raise AlpacaPaperClientError(
                "alpaca request returned a non-object payload",
                status_code=response.status_code,
                payload={"raw_body": response.text},
            )

        return AlpacaOrderSubmissionResult(status_code=response.status_code, payload=response_payload)
