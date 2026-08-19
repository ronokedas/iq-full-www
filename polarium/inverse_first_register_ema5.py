"""Opção 5: opção 4 invertida com filtro EMA5 contrária para Polarium Broker."""

from __future__ import annotations

from typing import Any, Sequence
from inverse_first_register import detect_latest as detect_base

STRATEGY_ID = "inverse_first_register_ema5_contrary"
STRATEGY_LABEL = "Inverso Primeiro Registro + EMA5 contrária"
RULE_VERSION = "first-register-clean-break-midpoint-v2-inverted-ema5-contrary"


def _v(row: Any, name: str) -> float:
    return float(row[name] if isinstance(row, dict) else getattr(row, name))


def detect_latest(candles: Sequence[Any], symbol: str, entry_from_ts: int) -> list[dict[str, Any]]:
    rows = sorted(candles, key=lambda x: int(x["from_ts"] if isinstance(x, dict) else x.from_ts))
    if len(rows) < 5:
        return []
    closes = [_v(r, "close") for r in rows]
    ema = closes[0]
    alpha = 2.0 / 6.0
    for close in closes[1:]:
        ema = alpha * close + (1 - alpha) * ema
    signals = detect_base(rows, symbol, entry_from_ts)
    if not signals:
        return []
    trigger = rows[-1]
    trigger_close = _v(trigger, "close")
    out = []
    for signal in signals:
        pattern = signal.get("pattern_direction", "")
        if (pattern == "UP" and trigger_close < ema) or (pattern == "DOWN" and trigger_close > ema):
            signal = dict(signal)
            signal.update(strategy=STRATEGY_LABEL, strategy_id=STRATEGY_ID,
                          rule_version=RULE_VERSION, ema5=ema,
                          ema_filter="contrary", base_rule_version=signal.get("rule_version"))
            out.append(signal)
    return out
