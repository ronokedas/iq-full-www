"""Opção 4: reteste 50% após rompimento limpo do Primeiro Registro para Polarium Broker."""

from __future__ import annotations

from typing import Any, Sequence

STRATEGY_ID = "inverse_first_register"
STRATEGY_LABEL = "Inverso Primeiro Registro"
RULE_VERSION = "first-register-clean-break-midpoint-v2"
MAX_HISTORY = 500
TOUCH_TIMEOUT_SECONDS = 25
INVERT_ENTRIES = True


def _v(row: Any, name: str) -> float | int:
    return row[name] if isinstance(row, dict) else getattr(row, name)


def _color(row: Any) -> str:
    opening, close = float(_v(row, "open")), float(_v(row, "close"))
    return "GREEN" if close > opening else "RED" if close < opening else "DOJI"


def _rows(candles: Sequence[Any]) -> list[Any]:
    unique = {int(_v(row, "from_ts")): row for row in candles}
    return [unique[key] for key in sorted(unique)][-MAX_HISTORY:]


def _signal(symbol: str, direction: str, reference: Any, trigger: Any, entry_from_ts: int) -> dict[str, Any]:
    trigger_high, trigger_low = float(_v(trigger, "high")), float(_v(trigger, "low"))
    level = (trigger_high + trigger_low) / 2.0
    trade_direction = ("DOWN" if direction == "UP" else "UP") if INVERT_ENTRIES else direction
    return {
        "symbol": symbol, "strategy": STRATEGY_LABEL, "strategy_id": STRATEGY_ID,
        "rule_version": RULE_VERSION + ("-inverted" if INVERT_ENTRIES else ""),
        "direction": trade_direction, "pattern_direction": direction,
        "approved": True, "decision": "approved",
        "reference_from_ts": int(_v(reference, "from_ts")), "trigger_from_ts": int(_v(trigger, "from_ts")),
        "entry_from_ts": int(entry_from_ts), "entry_level": level,
        "reference_high": float(_v(reference, "high")), "reference_low": float(_v(reference, "low")),
        "trigger_high": trigger_high, "trigger_low": trigger_low,
        "touch_side": "LOW" if direction == "UP" else "HIGH",
        "requires_open_side": "ABOVE" if direction == "UP" else "BELOW",
        "touch_allows_equality": True, "requires_live_touch": True,
        "touch_deadline": int(entry_from_ts) + TOUCH_TIMEOUT_SECONDS,
        "entry_timing": "trigger_candle_midpoint_return",
        "signal_timing": "clean_break_midpoint_touch_within_25_seconds",
    }


def detect_latest(candles: Sequence[Any], symbol: str, entry_from_ts: int) -> list[dict[str, Any]]:
    rows = _rows(candles)
    if len(rows) < 3 or int(_v(rows[-1], "from_ts")) + 60 != int(entry_from_ts):
        return []
    prior, reference, trigger = rows[-3:]
    colors = (_color(prior), _color(reference), _color(trigger))
    ref_open, ref_high, ref_low = (float(_v(reference, key)) for key in ("open", "high", "low"))
    trig_high, trig_low = float(_v(trigger, "high")), float(_v(trigger, "low"))
    signals: list[dict[str, Any]] = []
    if colors == ("GREEN", "RED", "GREEN"):
        if ref_high > ref_open and trig_high > ref_high and trig_low > ref_low:
            signals.append(_signal(symbol, "UP", reference, trigger, entry_from_ts))
    if colors == ("RED", "GREEN", "RED"):
        if ref_low < ref_open and trig_low < ref_low and trig_high < ref_high:
            signals.append(_signal(symbol, "DOWN", reference, trigger, entry_from_ts))
    return signals
