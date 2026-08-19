"""Modelos normalizados usados pelo cliente Polarium Broker e pelas estratégias."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

AccountMode = Literal["DEMO", "REAL"]
CandleColor = Literal["GREEN", "RED", "DOJI"]
Direction = Literal["UP", "DOWN"]


@dataclass(frozen=True, slots=True)
class Account:
    account_id: str
    trade_id: int | None
    mode: AccountMode
    balance: float
    bonus: float = 0.0

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> "Account":
        raw_mode = str(payload.get("type", "")).upper()
        if raw_mode not in {"DEMO", "REAL"}:
            raise ValueError(f"Tipo de conta desconhecido: {raw_mode!r}")
        trade_id = payload.get("tradeId")
        return cls(
            account_id=str(payload.get("accountId", payload.get("id", ""))),
            trade_id=int(trade_id) if trade_id is not None else None,
            mode=raw_mode,  # type: ignore[arg-type]
            balance=float(payload.get("balance") or 0.0),
            bonus=float(payload.get("bonus") or 0.0),
        )


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    timeframe: str
    from_ts: int
    to_ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    tick_count: int = 0

    @classmethod
    def from_api(
        cls,
        payload: dict[str, Any],
        *,
        symbol: str = "",
        timeframe: str = "",
    ) -> "Candle":
        return cls(
            symbol=str(payload.get("symbol") or symbol),
            timeframe=str(payload.get("timeframe") or timeframe),
            from_ts=int(payload.get("from") or payload.get("time") or 0),
            to_ts=int(payload.get("to") or 0),
            open=float(payload["open"]),
            high=float(payload["high"]),
            low=float(payload["low"]),
            close=float(payload["close"]),
            volume=float(payload.get("volume") or 0.0),
            tick_count=int(payload.get("tickCount") or 0),
        )


@dataclass(frozen=True, slots=True)
class PatternStats:
    symbol: str
    pattern_color: CandleColor
    sample_size: int
    wins: int
    accuracy: float

    @property
    def qualifies(self) -> bool:
        return self.sample_size == 20 and self.wins >= 13


@dataclass(frozen=True, slots=True)
class Signal:
    symbol: str
    pattern_color: CandleColor
    direction: Direction
    accuracy: float
    wins: int
    sample_size: int
    candle_from: int


@dataclass(frozen=True, slots=True)
class OperationResult:
    operation_id: str
    status: str
    result: str | None
    profit: float | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
