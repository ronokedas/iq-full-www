"""Primeiro Registro com reteste ao vivo: CALL e PUT espelhados para Polarium Broker."""

from __future__ import annotations

from typing import Any, Sequence

RULE_VERSION = "first-register-retest-v1"
STRATEGY_ID = "first_register_retest"
STRATEGY_LABEL = "Primeiro Registro com Reteste"
MAX_HISTORY = 500
TOUCH_TIMEOUT_SECONDS = 55


def _v(row: Any, name: str) -> float | int:
    return row[name] if isinstance(row, dict) else getattr(row, name)


def _color(row: Any) -> str:
    return "GREEN" if float(_v(row, "close")) > float(_v(row, "open")) else "RED" if float(_v(row, "close")) < float(_v(row, "open")) else "DOJI"


def _rows(candles: Sequence[Any]) -> list[Any]:
    unique = {int(_v(row, "from_ts")): row for row in candles}
    return [unique[key] for key in sorted(unique)][-MAX_HISTORY:]


def detect_latest(candles: Sequence[Any], symbol: str, entry_from_ts: int) -> list[dict[str, Any]]:
    rows = _rows(candles)
    if len(rows) < 3 or int(_v(rows[-1], "from_ts")) + 60 != int(entry_from_ts):
        return []
    first, record, violation = rows[-3:]
    output: list[dict[str, Any]] = []
    if (_color(first), _color(record), _color(violation)) == ("RED", "GREEN", "RED"):
        level = float(_v(record, "low"))
        if (float(_v(violation, "low")) < level and float(_v(violation, "close")) > level
                and float(_v(violation, "high")) <= float(_v(record, "high"))):
            output.append(_signal(symbol, "UP", "LOW", level, first, record, violation, entry_from_ts))
    if (_color(first), _color(record), _color(violation)) == ("GREEN", "RED", "GREEN"):
        level = float(_v(record, "high"))
        if (float(_v(violation, "high")) > level and float(_v(violation, "close")) < level
                and float(_v(violation, "low")) >= float(_v(record, "low"))):
            output.append(_signal(symbol, "DOWN", "HIGH", level, first, record, violation, entry_from_ts))
    return output


def _signal(symbol: str, direction: str, touch_side: str, level: float, first: Any, record: Any,
            violation: Any, entry_from_ts: int) -> dict[str, Any]:
    return {"symbol": symbol, "strategy": STRATEGY_LABEL, "strategy_id": STRATEGY_ID,
            "rule_version": RULE_VERSION, "direction": direction, "approved": True, "decision": "approved",
            "first_from_ts": int(_v(first, "from_ts")), "record_from_ts": int(_v(record, "from_ts")),
            "violation_from_ts": int(_v(violation, "from_ts")), "entry_from_ts": int(entry_from_ts),
            "entry_level": level, "touch_side": touch_side, "requires_live_touch": True,
            "touch_deadline": int(entry_from_ts) + TOUCH_TIMEOUT_SECONDS,
            "signal_timing": "first_register_touch_before_close",
            "violation_high": float(_v(violation, "high")),
            "violation_low": float(_v(violation, "low")),
            "record_high": float(_v(record, "high")),
            "record_low": float(_v(record, "low"))}
