"""Detector causal do Padrão Start para Polarium Broker."""

from __future__ import annotations

from typing import Any, Sequence

RULE_VERSION = "start-pattern-retest-v1"
STRATEGY_ID = "start_pattern"
STRATEGY_LABEL = "Padrão Start"
MAX_HISTORY = 500
TOUCH_TIMEOUT_SECONDS = 25


def _v(row: Any, name: str) -> float | int:
    return row[name] if isinstance(row, dict) else getattr(row, name)


def _color(row: Any) -> str:
    open_, close = float(_v(row, "open")), float(_v(row, "close"))
    return "GREEN" if close > open_ else "RED" if close < open_ else "DOJI"


def _normalize(rows: Sequence[Any]) -> list[Any]:
    unique = {int(_v(row, "from_ts")): row for row in rows}
    return [unique[key] for key in sorted(unique)][-MAX_HISTORY:]


def detect_latest(candles: Sequence[Any], symbol: str, entry_from_ts: int) -> list[dict[str, Any]]:
    rows = _normalize(candles)
    if len(rows) < 5 or int(_v(rows[-1], "from_ts")) + 60 != int(entry_from_ts):
        return []
    start, v3 = len(rows) - 1, len(rows) - 2
    output: list[dict[str, Any]] = []
    if (_color(rows[v3]), _color(rows[start])) not in {("GREEN", "GREEN"), ("RED", "RED")}:
        return []
    for v2 in range(v3 - 1, max(1, v3 - 31), -1):
        v1, first = v2 - 1, v2 - 2
        if first < 0:
            continue
        reference = float(_v(rows[v2], "open"))
        if (_color(rows[first]), _color(rows[v1]), _color(rows[v2]), _color(rows[v3]), _color(rows[start])) == ("GREEN", "RED", "RED", "GREEN", "GREEN"):
            if (float(_v(rows[v1], "close")) < float(_v(rows[first], "low"))
                    and float(_v(rows[v2], "close")) < float(_v(rows[v1], "low"))
                    and float(_v(rows[v3], "high")) >= reference and float(_v(rows[v3], "close")) < reference
                    and float(_v(rows[start], "close")) > float(_v(rows[v2], "high"))):
                output.append(_signal(rows, symbol, "UP", "LOW", first, v1, v2, v3, start, entry_from_ts, reference))
                break
        if (_color(rows[first]), _color(rows[v1]), _color(rows[v2]), _color(rows[v3]), _color(rows[start])) == ("RED", "GREEN", "GREEN", "RED", "RED"):
            if (float(_v(rows[v1], "close")) > float(_v(rows[first], "high"))
                    and float(_v(rows[v2], "close")) > float(_v(rows[v1], "high"))
                    and float(_v(rows[v3], "low")) <= reference and float(_v(rows[v3], "close")) > reference
                    and float(_v(rows[start], "close")) < float(_v(rows[v2], "low"))):
                output.append(_signal(rows, symbol, "DOWN", "HIGH", first, v1, v2, v3, start, entry_from_ts, reference))
                break
    return output


def _signal(rows: Sequence[Any], symbol: str, direction: str, touch_side: str, first: int, v1: int, v2: int, v3: int,
            start: int, entry_from_ts: int, reference: float) -> dict[str, Any]:
    level = float(_v(rows[start], "open"))
    return {
        "symbol": symbol, "strategy": STRATEGY_LABEL, "strategy_id": STRATEGY_ID,
        "rule_version": RULE_VERSION, "direction": direction, "approved": True, "decision": "approved",
        "v1_from_ts": int(_v(rows[v1], "from_ts")), "v2_from_ts": int(_v(rows[v2], "from_ts")),
        "v3_from_ts": int(_v(rows[v3], "from_ts")), "start_from_ts": int(_v(rows[start], "from_ts")),
        "entry_from_ts": int(entry_from_ts), "reference_open_v2": reference,
        "v2_extreme": float(_v(rows[v2], "high")) if direction == "UP" else float(_v(rows[v2], "low")),
        "entry_level": level, "start_low": float(_v(rows[start], "low")),
        "start_high": float(_v(rows[start], "high")),
        "touch_side": touch_side, "requires_live_touch": True,
        "touch_allows_equality": True,
        "touch_deadline": int(entry_from_ts) + TOUCH_TIMEOUT_SECONDS,
        "signal_timing": "start_touch_within_25_seconds",
    }
