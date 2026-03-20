from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from trade_proposer_app.config import AppSettings

_DEFAULT_ALLOWLIST_PATHS = (
    "/api/health",
    "/api/health/preflight",
    "/api/health/prototype",
)

_UNSET = object()


def _parse_allowlist_entries(value: Iterable[str]) -> list[str]:
    entries: list[str] = []
    for entry in value:
        candidate = entry.strip()
        if candidate:
            entries.append(candidate)
    return entries


@dataclass(frozen=True)
class _AllowlistPattern:
    value: str
    prefix: bool

    def matches(self, path: str) -> bool:
        if self.prefix:
            return path.startswith(self.value)
        return path == self.value


class SingleUserAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, settings: AppSettings) -> None:
        super().__init__(app)
        self._settings = settings
        self._enabled = False
        self._token = ""
        self._allowlist_raw: str | None | object = _UNSET
        self._allowlist_patterns: tuple[_AllowlistPattern, ...] = ()
        self._sync_configuration()

    async def dispatch(self, request: Request, call_next):
        self._sync_configuration()
        if not self._enabled or not request.url.path.startswith("/api"):
            return await call_next(request)
        if self._is_allowlisted(request.url.path):
            return await call_next(request)
        if not self._has_valid_token(request):
            return JSONResponse(
                {"detail": "Authentication required"},
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    def _sync_configuration(self) -> None:
        enabled = bool(self._settings.single_user_auth_enabled)
        token = (self._settings.single_user_auth_token or "").strip()
        allowlist_raw = self._settings.single_user_auth_allowlist_paths
        if (
            enabled != self._enabled
            or token != self._token
            or allowlist_raw != self._allowlist_raw
        ):
            self._enabled = enabled
            self._token = token
            self._allowlist_raw = allowlist_raw
            self._allowlist_patterns = self._build_allowlist_patterns(allowlist_raw)
            if self._enabled and not self._token:
                raise ValueError("single-user auth enabled but SINGLE_USER_AUTH_TOKEN is not set")

    def _build_allowlist_patterns(self, raw: str | None) -> tuple[_AllowlistPattern, ...]:
        entries = list(_DEFAULT_ALLOWLIST_PATHS)
        if raw:
            entries.extend(_parse_allowlist_entries(raw.split(",")))
        patterns: list[_AllowlistPattern] = []
        for entry in entries:
            normalized = entry.strip()
            if not normalized:
                continue
            wildcard = normalized.endswith("*")
            value = normalized[:-1] if wildcard else normalized
            patterns.append(_AllowlistPattern(value=value, prefix=wildcard))
        return tuple(patterns)

    def _is_allowlisted(self, path: str) -> bool:
        if not self._allowlist_patterns:
            return False
        return any(pattern.matches(path) for pattern in self._allowlist_patterns)

    def _has_valid_token(self, request: Request) -> bool:
        header = request.headers.get("Authorization", "")
        if not header:
            return False
        parts = header.split(" ", 1)
        if len(parts) != 2:
            return False
        scheme, token = parts
        return scheme.lower() == "bearer" and token.strip() == self._token
