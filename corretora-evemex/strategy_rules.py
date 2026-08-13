"""Regras canônicas das estratégias usadas em execução e treinamento."""

from __future__ import annotations

from typing import Any, Sequence


def _value(candle: Any, field: str) -> float:
    if isinstance(candle, dict):
        return float(candle[field])
    try:
        return float(candle[field])
    except (TypeError, KeyError):
        return float(getattr(candle, field))


def _doji(candle: Any) -> bool:
    return abs(_value(candle, "close") - _value(candle, "open")) < 1e-12


def _green(candle: Any) -> bool:
    return _value(candle, "close") > _value(candle, "open")


def _red(candle: Any) -> bool:
    return _value(candle, "close") < _value(candle, "open")


def detect_s01(candles: Sequence[Any]) -> str | None:
    """S01: V0 oposta/doji seguido por três velas M1 da mesma cor."""
    if len(candles) < 4:
        return None
    v0, v1, v2, v3 = candles[-4:]
    if any(_doji(candle) for candle in (v1, v2, v3)):
        return None
    if all(_green(candle) for candle in (v1, v2, v3)):
        return "DOWN" if _red(v0) or _doji(v0) else None
    if all(_red(candle) for candle in (v1, v2, v3)):
        return "UP" if _green(v0) or _doji(v0) else None
    return None


def detect_s13(candles: Sequence[Any]) -> str | None:
    """S13: rejeição no pavio da primeira de três velas M1 da mesma cor."""
    if len(candles) < 3:
        return None
    v1, v2, v3 = candles[-3:]
    if (
        all(_green(candle) for candle in (v1, v2, v3))
        and _value(v1, "high") > _value(v1, "close")
        and _value(v2, "close") < _value(v1, "high")
        and _value(v3, "close") < _value(v1, "high")
    ):
        return "DOWN"
    if (
        all(_red(candle) for candle in (v1, v2, v3))
        and _value(v1, "low") < _value(v1, "close")
        and _value(v2, "close") > _value(v1, "low")
        and _value(v3, "close") > _value(v1, "low")
    ):
        return "UP"
    return None


def detect_s16(candles: Sequence[Any]) -> str | None:
    """S16: fundo/topo duplo M5 confirmado por três candles fechados."""
    if len(candles) < 3:
        return None
    v1, v2, v3 = candles[-3:]
    level = _value(v1, "close")
    scale = 1e-4 if level < 100 else 1e-2
    tolerance = scale * 0.5
    touches_level = (
        _value(v3, "low") <= level + tolerance
        and _value(v3, "high") >= level - tolerance
    )
    if _red(v1) and _green(v2) and abs(_value(v2, "open") - level) <= tolerance:
        return "UP" if touches_level and _red(v3) else None
    if _green(v1) and _red(v2) and abs(_value(v2, "open") - level) <= tolerance:
        return "DOWN" if touches_level and _green(v3) else None
    return None
