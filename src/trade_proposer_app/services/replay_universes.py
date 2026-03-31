from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReplayUniversePreset:
    key: str
    label: str
    region: str
    description: str
    tickers: tuple[str, ...]


US_LARGE_CAP_TOP20_V1 = ReplayUniversePreset(
    key="us_large_cap_top20_v1",
    label="US large cap top 20 v1",
    region="US",
    description="Curated static US large-cap replay basket for MVP research runs.",
    tickers=(
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "META",
        "BRK-B",
        "TSLA",
        "JPM",
        "V",
        "WMT",
        "XOM",
        "UNH",
        "MA",
        "COST",
        "NFLX",
        "ORCL",
        "HD",
        "PG",
        "JNJ",
    ),
)

EU_LARGE_CAP_TOP20_V1 = ReplayUniversePreset(
    key="eu_large_cap_top20_v1",
    label="EU large cap top 20 v1",
    region="EU",
    description="Curated static major European large-cap replay basket for MVP research runs.",
    tickers=(
        "ASML.AS",
        "NOVO-B.CO",
        "MC.PA",
        "SAP.DE",
        "NESN.SW",
        "ROG.SW",
        "NOVN.SW",
        "OR.PA",
        "SAN.PA",
        "SU.PA",
        "AIR.PA",
        "AI.PA",
        "TTE.PA",
        "SIE.DE",
        "ALV.DE",
        "RMS.PA",
        "RHM.DE",
        "BNP.PA",
        "DTE.DE",
        "UCG.MI",
    ),
)

REPLAY_UNIVERSE_PRESETS: dict[str, ReplayUniversePreset] = {
    US_LARGE_CAP_TOP20_V1.key: US_LARGE_CAP_TOP20_V1,
    EU_LARGE_CAP_TOP20_V1.key: EU_LARGE_CAP_TOP20_V1,
}


def list_replay_universe_presets() -> list[ReplayUniversePreset]:
    return list(REPLAY_UNIVERSE_PRESETS.values())


def resolve_replay_universe(*, universe_preset: str | None = None, tickers: list[str] | None = None) -> tuple[str, str | None, list[str]]:
    normalized_tickers = [ticker.strip().upper() for ticker in (tickers or []) if ticker and ticker.strip()]
    if universe_preset:
        preset = REPLAY_UNIVERSE_PRESETS.get(universe_preset)
        if preset is None:
            raise ValueError(f"Unknown replay universe preset: {universe_preset}")
        if normalized_tickers:
            raise ValueError("Provide either universe_preset or explicit tickers, not both")
        return "explicit", preset.key, list(preset.tickers)
    if not normalized_tickers:
        raise ValueError("Historical replay requires either universe_preset or explicit tickers")
    deduped = list(dict.fromkeys(normalized_tickers))
    return "explicit", None, deduped
