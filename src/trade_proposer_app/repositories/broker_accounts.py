from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from trade_proposer_app.domain.models import BrokerAccount
from trade_proposer_app.persistence.models import BrokerAccountCredentialRecord, BrokerAccountRecord
from trade_proposer_app.security import credential_cipher

DEFAULT_ETORO_DEMO_ACCOUNT_ID = "etoro-demo-main"


class BrokerAccountRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def ensure_default_etoro_demo_account(self) -> BrokerAccount:
        existing = self.session.get(BrokerAccountRecord, DEFAULT_ETORO_DEMO_ACCOUNT_ID)
        if existing is None:
            existing = BrokerAccountRecord(
                broker_account_id=DEFAULT_ETORO_DEMO_ACCOUNT_ID,
                broker="etoro",
                account_mode="demo",
                account_label="eToro Demo",
                enabled=False,
                autonomous_execution_enabled=False,
                manual_actions_enabled=True,
                credential_reference=f"broker_account:{DEFAULT_ETORO_DEMO_ACCOUNT_ID}",
                symbol_allowlist_json=self._dump([]),
                supported_actions_json=self._dump(["long"]),
                supported_instruments_json=self._dump(["resolved_equity"]),
                supported_order_types_json=self._dump(["market"]),
                notional_cap_usd=25.0,
                max_open_positions=1,
                max_open_notional_usd=25.0,
                max_position_notional_usd=25.0,
                max_same_ticker_open_positions=1,
                risk_settings_json=self._dump(
                    {
                        "demo_only": True,
                        "require_demo_validation": True,
                        "require_demo_lifecycle_validation": True,
                        "side_by_side_trial_required": True,
                    }
                ),
            )
            self.session.add(existing)
            self.session.commit()
            self.session.refresh(existing)
        return self._to_model(existing)

    def create(self, account: BrokerAccount) -> BrokerAccount:
        record = BrokerAccountRecord(
            broker_account_id=account.broker_account_id,
            broker=account.broker,
            account_mode=account.account_mode,
            account_label=account.account_label,
            enabled=account.enabled,
            autonomous_execution_enabled=account.autonomous_execution_enabled,
            manual_actions_enabled=account.manual_actions_enabled,
            credential_reference=account.credential_reference
            or f"broker_account:{account.broker_account_id}",
            symbol_allowlist_json=self._dump(account.symbol_allowlist),
            symbol_denylist_json=self._dump(account.symbol_denylist),
            supported_actions_json=self._dump(account.supported_actions),
            supported_instruments_json=self._dump(account.supported_instruments),
            supported_order_types_json=self._dump(account.supported_order_types),
            notional_cap_usd=account.notional_cap_usd,
            max_open_positions=account.max_open_positions,
            max_open_notional_usd=account.max_open_notional_usd,
            max_position_notional_usd=account.max_position_notional_usd,
            max_same_ticker_open_positions=account.max_same_ticker_open_positions,
            halt_enabled=account.halt_enabled,
            halt_reason=account.halt_reason,
            validation_status=account.validation_status,
            validation_evidence_json=self._dump(account.validation_evidence),
            risk_settings_json=self._dump(account.risk_settings),
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def get(self, broker_account_id: str) -> BrokerAccount:
        record = self.session.get(BrokerAccountRecord, broker_account_id)
        if record is None:
            raise ValueError(f"Broker account {broker_account_id} not found")
        return self._to_model(record)

    def list_all(self) -> list[BrokerAccount]:
        rows = self.session.scalars(
            select(BrokerAccountRecord).order_by(BrokerAccountRecord.created_at.asc())
        ).all()
        return [self._to_model(row) for row in rows]

    def list_enabled(self) -> list[BrokerAccount]:
        rows = self.session.scalars(
            select(BrokerAccountRecord)
            .where(BrokerAccountRecord.enabled.is_(True))
            .order_by(BrokerAccountRecord.created_at.asc())
        ).all()
        return [self._to_model(row) for row in rows]

    def list_accounts_redacted(self) -> list[BrokerAccount]:
        return [
            account.model_copy(
                update={
                    "credential_reference": account.credential_reference
                    or f"broker_account:{account.broker_account_id}"
                }
            )
            for account in self.list_all()
        ]

    def update_label(self, broker_account_id: str, account_label: str) -> BrokerAccount:
        record = self.session.get(BrokerAccountRecord, broker_account_id)
        if record is None:
            raise ValueError(f"Broker account {broker_account_id} not found")
        record.account_label = account_label
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def update_controls(self, broker_account_id: str, updates: dict[str, object]) -> BrokerAccount:
        record = self.session.get(BrokerAccountRecord, broker_account_id)
        if record is None:
            raise ValueError(f"Broker account {broker_account_id} not found")
        for key in (
            "enabled",
            "autonomous_execution_enabled",
            "manual_actions_enabled",
            "halt_enabled",
        ):
            if key in updates and updates[key] is not None:
                setattr(record, key, bool(updates[key]))
        for key in ("account_label", "halt_reason"):
            if key in updates and updates[key] is not None:
                setattr(record, key, str(updates[key]))
        for key in ("notional_cap_usd", "max_open_notional_usd", "max_position_notional_usd"):
            if key in updates:
                setattr(record, key, self._optional_float(updates[key]))
        for key in ("max_open_positions", "max_same_ticker_open_positions"):
            if key in updates:
                setattr(record, key, self._optional_int(updates[key]))
        if "symbol_allowlist" in updates and updates["symbol_allowlist"] is not None:
            record.symbol_allowlist_json = self._dump(
                [str(item).upper() for item in updates["symbol_allowlist"]]
            )
        if "symbol_denylist" in updates and updates["symbol_denylist"] is not None:
            record.symbol_denylist_json = self._dump(
                [str(item).upper() for item in updates["symbol_denylist"]]
            )
        if "risk_settings" in updates and isinstance(updates["risk_settings"], dict):
            current = self._load_dict(record.risk_settings_json)
            current.update(updates["risk_settings"])
            record.risk_settings_json = self._dump(current)
        self.session.commit()
        self.session.refresh(record)
        return self._to_model(record)

    def upsert_credentials(self, broker_account_id: str, credentials: dict[str, str]) -> None:
        if self.session.get(BrokerAccountRecord, broker_account_id) is None:
            raise ValueError(f"Broker account {broker_account_id} not found")
        encrypted = credential_cipher.encrypt(self._dump(credentials))
        record = self.session.get(BrokerAccountCredentialRecord, broker_account_id)
        if record is None:
            record = BrokerAccountCredentialRecord(
                broker_account_id=broker_account_id,
                encrypted_credentials_json=encrypted,
            )
            self.session.add(record)
        else:
            record.encrypted_credentials_json = encrypted
        account = self.session.get(BrokerAccountRecord, broker_account_id)
        if account is not None:
            account.credential_reference = f"broker_account:{broker_account_id}"
        self.session.commit()

    def get_credentials(self, broker_account_id: str) -> dict[str, str]:
        record = self.session.get(BrokerAccountCredentialRecord, broker_account_id)
        if record is None:
            return {}
        decrypted = credential_cipher.decrypt(record.encrypted_credentials_json)
        loaded = self._load(decrypted, {})
        return loaded if isinstance(loaded, dict) else {}

    def _to_model(self, record: BrokerAccountRecord) -> BrokerAccount:
        return BrokerAccount(
            broker_account_id=record.broker_account_id,
            broker=record.broker,
            account_mode=record.account_mode,
            account_label=record.account_label,
            enabled=record.enabled,
            autonomous_execution_enabled=record.autonomous_execution_enabled,
            manual_actions_enabled=record.manual_actions_enabled,
            credential_reference=record.credential_reference,
            symbol_allowlist=self._load_list(record.symbol_allowlist_json),
            symbol_denylist=self._load_list(record.symbol_denylist_json),
            supported_actions=self._load_list(record.supported_actions_json),
            supported_instruments=self._load_list(record.supported_instruments_json),
            supported_order_types=self._load_list(record.supported_order_types_json),
            notional_cap_usd=record.notional_cap_usd,
            max_open_positions=record.max_open_positions,
            max_open_notional_usd=record.max_open_notional_usd,
            max_position_notional_usd=record.max_position_notional_usd,
            max_same_ticker_open_positions=record.max_same_ticker_open_positions,
            halt_enabled=record.halt_enabled,
            halt_reason=record.halt_reason,
            validation_status=record.validation_status,
            validation_evidence=self._load_dict(record.validation_evidence_json),
            risk_settings=self._load_dict(record.risk_settings_json),
            created_at=self._normalize_datetime(record.created_at),
            updated_at=self._normalize_datetime(record.updated_at),
        )

    @staticmethod
    def _dump(value: object) -> str:
        return json.dumps(value, default=str)

    @staticmethod
    def _load(value: str | None, default: object) -> object:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    def _load_list(self, value: str | None) -> list[str]:
        loaded = self._load(value, [])
        return [str(item) for item in loaded] if isinstance(loaded, list) else []

    def _load_dict(self, value: str | None) -> dict[str, object]:
        loaded = self._load(value, {})
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _optional_float(value: object) -> float | None:
        if value in {None, ""}:
            return None
        return float(value)

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value in {None, ""}:
            return None
        return int(value)

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
