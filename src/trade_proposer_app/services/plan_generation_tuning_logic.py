from __future__ import annotations


def family_adjusted_trade_levels(
    *,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    setup_family: str,
    action: str,
    transmission_context_bias: str | None,
    tuning_config: dict[str, float],
) -> tuple[float, float, float, float]:
    entry = round(float(entry_price), 4)
    stop = round(float(stop_loss), 4)
    take = round(float(take_profit), 4)
    if entry <= 0:
        return entry, entry, stop, take
    risk_distance = abs(entry - stop)
    reward_distance = abs(take - entry)
    if risk_distance <= 0 and reward_distance <= 0:
        return entry, entry, stop, take

    direction = -1.0 if action == "short" else 1.0
    family = str(setup_family or "").strip().lower()
    bias = str(transmission_context_bias or "").strip().lower() or None

    entry_band_fraction = max(0.0, float(tuning_config.get("global.entry_band_risk_fraction", 0.0) or 0.0))
    entry_band_distance = risk_distance * entry_band_fraction
    entry_low = round(entry - entry_band_distance, 4)
    entry_high = round(entry + entry_band_distance, 4)

    stop_multiplier = 1.0
    take_multiplier = 1.0
    if family in {"breakout", "breakdown"}:
        stop_multiplier = float(tuning_config.get("setup_family.breakout.stop_distance_multiplier", 0.85) or 0.85)
        take_multiplier = float(tuning_config.get("setup_family.breakout.take_profit_distance_multiplier", 1.12) or 1.12)
    elif family == "mean_reversion":
        stop_multiplier = float(tuning_config.get("setup_family.mean_reversion.stop_distance_multiplier", 1.1) or 1.1)
        take_multiplier = float(tuning_config.get("setup_family.mean_reversion.take_profit_distance_multiplier", 0.88) or 0.88)
    elif family == "catalyst_follow_through":
        take_multiplier = float(tuning_config.get("setup_family.catalyst_follow_through.take_profit_distance_multiplier", 1.18) or 1.18)
    elif family == "macro_beneficiary_loser":
        take_multiplier = float(tuning_config.get("setup_family.macro_beneficiary_loser.take_profit_distance_multiplier", 1.08) or 1.08)

    adjusted_risk_distance = risk_distance * stop_multiplier
    adjusted_reward_distance = reward_distance * take_multiplier
    stop = round(entry - (direction * adjusted_risk_distance), 4)
    take = round(entry + (direction * adjusted_reward_distance), 4)

    if bias == "headwind" and adjusted_risk_distance > 0:
        headwind_multiplier = float(tuning_config.get("global.headwind_stop_multiplier", 0.92) or 0.92)
        stop = round(entry - (direction * (adjusted_risk_distance * headwind_multiplier)), 4)

    if action == "short":
        entry_low, entry_high = min(entry_low, entry_high), max(entry_low, entry_high)
    else:
        entry_low, entry_high = min(entry_low, entry_high), max(entry_low, entry_high)
    return entry_low, entry_high, stop, take
