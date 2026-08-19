"""Detector V1/V2/V3 Retest Invertido para Polarium Broker."""

from __future__ import annotations

from typing import Any, Sequence

STRATEGY_ID = "v1_v2_v3_first_retest_inverted"
STRATEGY_LABEL = "V1/V2/V3 Primeiro Reteste Invertido"
RULE_VERSION = "v1-v2-v3-first-retest-inverted-v1"


def _v(r: Any, n: str) -> float:
    return float(r[n] if isinstance(r, dict) else getattr(r, n))


def color(r: Any) -> str:
    return "G" if _v(r, "close") > _v(r, "open") else "R" if _v(r, "close") < _v(r, "open") else "D"


def detect_latest(candles: Sequence[Any], symbol: str, entry_from_ts: int) -> list[dict[str, Any]]:
    rows = sorted(candles, key=lambda r: int(r["from_ts"] if isinstance(r, dict) else r.from_ts))
    if len(rows) < 4 or int(rows[-1]["from_ts"] if isinstance(rows[-1], dict) else rows[-1].from_ts) + 60 != int(entry_from_ts):
        return []
    v1, v2, v3, retest = rows[-4:]
    cs = [color(x) for x in (v1, v2, v3, retest)]
    if cs == ["R", "G", "G", "G"] and _v(v2, "close") > _v(v1, "high") and _v(v3, "close") > _v(v2, "high") and _v(retest, "high") >= _v(v1, "high") and _v(retest, "close") > _v(v3, "low"):
        direction, pattern, level = "DOWN", "CALL", _v(v1, "high")
    elif cs == ["G", "R", "R", "R"] and _v(v2, "close") < _v(v1, "low") and _v(v3, "close") < _v(v2, "low") and _v(retest, "low") <= _v(v1, "low") and _v(retest, "close") < _v(v3, "high"):
        direction, pattern, level = "UP", "PUT", _v(v1, "low")
    else:
        return []
    return [{
        "symbol": symbol, "strategy": STRATEGY_LABEL, "strategy_id": STRATEGY_ID,
        "rule_version": RULE_VERSION, "direction": direction, "pattern_direction": pattern,
        "approved": True, "decision": "approved", "entry_from_ts": int(entry_from_ts),
        "entry_level": level, "entry_timing": "next_candle_open", "signal_timing": "first_retest_after_v3"
    }]
