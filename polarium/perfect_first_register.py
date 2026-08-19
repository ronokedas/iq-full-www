"""Detector causal do Cenário Perfeito com Recusado Primeiro Registro para Polarium Broker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

RULE_VERSION = "perfect-entry-first-register-last5-clear-v3"
STRATEGY_LABEL = "Cenário Perfeito + Recusado Primeiro Registro"
ZIGZAG_THRESHOLD = 0.005
BREAK_MAX_AGE = 10
RETURN_MAX_AGE = 30
RETEST_MAX_AGE = 120
FIRST_REGISTER_WINDOW = 5
MAX_HISTORY = 500


@dataclass(frozen=True)
class Pivot:
    kind: str
    pivot_index: int
    confirmed_index: int
    level: float


@dataclass(frozen=True)
class Level:
    kind: str
    pivot_index: int
    confirmed_index: int
    break_index: int
    validated_index: int
    level: float


def _value(candle: Any, name: str) -> float | int:
    return candle[name] if isinstance(candle, dict) else getattr(candle, name)


def _candle_dict(candle: Any) -> dict[str, float | int]:
    return {name: _value(candle, name) for name in ("from_ts", "open", "high", "low", "close")}


def normalize(candles: Sequence[Any]) -> list[Any]:
    unique = {int(_value(item, "from_ts")): item for item in candles}
    return [unique[key] for key in sorted(unique)][-MAX_HISTORY:]


def color(candle: Any) -> str:
    open_ = float(_value(candle, "open"))
    close = float(_value(candle, "close"))
    if close > open_:
        return "GREEN"
    if close < open_:
        return "RED"
    return "DOJI"


def causal_zigzag(candles: Sequence[Any], threshold: float = ZIGZAG_THRESHOLD) -> list[Pivot]:
    if threshold <= 0:
        raise ValueError("o limiar do ZigZag deve ser positivo")
    rows = normalize(candles)
    if not rows:
        return []
    pivots: list[Pivot] = []
    low_index = high_index = 0
    direction = 0
    for index in range(1, len(rows)):
        low = float(_value(rows[index], "low"))
        high = float(_value(rows[index], "high"))
        if direction == 0:
            if low < float(_value(rows[low_index], "low")):
                low_index = index
            if high > float(_value(rows[high_index], "high")):
                high_index = index
            if index > low_index and high >= float(_value(rows[low_index], "low")) * (1 + threshold):
                pivots.append(Pivot("LOW", low_index, index, float(_value(rows[low_index], "low"))))
                direction, high_index = 1, index
            elif index > high_index and low <= float(_value(rows[high_index], "high")) * (1 - threshold):
                pivots.append(Pivot("HIGH", high_index, index, float(_value(rows[high_index], "high"))))
                direction, low_index = -1, index
        elif direction > 0:
            if high >= float(_value(rows[high_index], "high")):
                high_index = index
            if index > high_index and low <= float(_value(rows[high_index], "high")) * (1 - threshold):
                pivots.append(Pivot("HIGH", high_index, index, float(_value(rows[high_index], "high"))))
                direction, low_index = -1, index
        else:
            if low <= float(_value(rows[low_index], "low")):
                low_index = index
            if index > low_index and high >= float(_value(rows[low_index], "low")) * (1 + threshold):
                pivots.append(Pivot("LOW", low_index, index, float(_value(rows[low_index], "low"))))
                direction, high_index = 1, index
    return pivots


def validated_levels(candles: Sequence[Any]) -> list[Level]:
    rows = normalize(candles)
    output: list[Level] = []
    for pivot in causal_zigzag(rows):
        break_index = next((index for index in range(
            pivot.confirmed_index + 1,
            min(len(rows), pivot.confirmed_index + BREAK_MAX_AGE + 1),
        ) if (
            float(_value(rows[index], "close")) > pivot.level
            if pivot.kind == "HIGH" else float(_value(rows[index], "close")) < pivot.level
        )), None)
        if break_index is None:
            continue
        validated_index = next((index for index in range(
            break_index + 1, min(len(rows), break_index + RETURN_MAX_AGE + 1),
        ) if (
            float(_value(rows[index], "close")) < pivot.level
            if pivot.kind == "HIGH" else float(_value(rows[index], "close")) > pivot.level
        )), None)
        if validated_index is not None:
            output.append(Level(
                pivot.kind, pivot.pivot_index, pivot.confirmed_index,
                break_index, validated_index, pivot.level,
            ))
    return output


def refused_first_register(rows: Sequence[Any], touch_index: int, direction: str) -> dict[str, Any] | None:
    start = max(0, touch_index - FIRST_REGISTER_WINDOW)
    wanted = ("RED", "GREEN") if direction == "UP" else ("GREEN", "RED")
    matches: list[dict[str, Any]] = []
    for reversal_index in range(1, touch_index):
        first_index = reversal_index - 1
        if (color(rows[first_index]), color(rows[reversal_index])) != wanted:
            continue
        reversal = rows[reversal_index]
        boundary = float(_value(reversal, "high")) if direction == "UP" else float(_value(reversal, "low"))
        first_violation_index = None
        first_violation_extreme = None
        for violation_index in range(reversal_index + 1, touch_index):
            extreme = float(_value(rows[violation_index], "high" if direction == "UP" else "low"))
            violated = extreme > boundary if direction == "UP" else extreme < boundary
            if violated:
                first_violation_index = violation_index
                first_violation_extreme = extreme
                break
        if first_violation_index is None or first_violation_index < start:
            continue
        matches.append({
            "first_register_type": "RED_TO_GREEN" if direction == "UP" else "GREEN_TO_RED",
            "first_register_from_ts": int(_value(rows[first_index], "from_ts")),
            "first_register_reversal_from_ts": int(_value(reversal, "from_ts")),
            "first_register_boundary": boundary,
            "first_register_violation_from_ts": int(_value(rows[first_violation_index], "from_ts")),
            "first_register_violation_extreme": first_violation_extreme,
            "first_register_violation_age": touch_index - first_violation_index,
        })
    if not matches:
        return None
    return max(matches, key=lambda item: (
        int(item["first_register_violation_from_ts"]),
        int(item["first_register_reversal_from_ts"]),
    ))


def detect_latest(candles: Sequence[Any], symbol: str, entry_from_ts: int) -> list[dict[str, Any]]:
    rows = normalize(candles)
    if len(rows) < 3 or int(_value(rows[-1], "from_ts")) + 60 != int(entry_from_ts):
        return []
    touch_index = len(rows) - 1
    touch = rows[touch_index]
    candidates: list[dict[str, Any]] = []
    for level in validated_levels(rows):
        first_touch = next((index for index in range(
            level.validated_index + 1,
            min(len(rows), level.validated_index + RETEST_MAX_AGE + 1),
        ) if (
            float(_value(rows[index], "high")) > level.level
            if level.kind == "HIGH" else float(_value(rows[index], "low")) < level.level
        )), None)
        if first_touch != touch_index:
            continue
        open_ = float(_value(touch, "open")); high = float(_value(touch, "high"))
        low = float(_value(touch, "low")); close = float(_value(touch, "close"))
        direction = "DOWN" if level.kind == "HIGH" else "UP"
        respected = close < level.level if direction == "DOWN" else close > level.level
        refusal = refused_first_register(rows, touch_index, direction) if respected else None
        perfect = (
            close > open_ and high > level.level and close < level.level
            if direction == "DOWN" else
            close < open_ and low < level.level and close > level.level
        )
        if refusal is None and not perfect:
            continue
        candle_range = max(high - low, 1e-12)
        rejection = level.level - close if direction == "DOWN" else close - level.level
        rank_score = max(0.0, min(1.0, rejection / candle_range))
        candidates.append({
            "rule_version": RULE_VERSION,
            "strategy": STRATEGY_LABEL,
            "strategy_id": "perfect_first_register",
            "symbol": symbol,
            "direction": direction,
            "approved": refusal is None,
            "decision": "refused_first_register" if refusal is not None else "approved",
            "last_five_first_register_clear": refusal is None,
            "first_register_window": FIRST_REGISTER_WINDOW,
            "pivot_kind": level.kind,
            "level": level.level,
            "pivot_from_ts": int(_value(rows[level.pivot_index], "from_ts")),
            "pivot_confirmed_from_ts": int(_value(rows[level.confirmed_index], "from_ts")),
            "break_from_ts": int(_value(rows[level.break_index], "from_ts")),
            "validated_from_ts": int(_value(rows[level.validated_index], "from_ts")),
            "retest_from_ts": int(_value(touch, "from_ts")),
            "entry_from_ts": int(entry_from_ts),
            "rank_score": rank_score,
            "retest_candle_snapshot": _candle_dict(touch),
            **(refusal or {}),
        })
    return candidates
