"""Estratégia M1 de reversão após três velas da mesma cor."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .models import Candle, CandleColor, PatternStats, Signal


def candle_color(candle: Candle) -> CandleColor:
    """Classifica a vela sem tolerância: igualdade exata é doji."""
    if candle.close > candle.open:
        return "GREEN"
    if candle.close < candle.open:
        return "RED"
    return "DOJI"


def calculate_pattern_stats(
    candles: Iterable[Candle],
    *,
    symbol: str | None = None,
    sample_size: int = 20,
) -> dict[CandleColor, PatternStats]:
    """Calcula os últimos resultados sem contar sequências sobrepostas.

    Uma ocorrência é registrada quando a sequência alcança exatamente três
    velas iguais. A estratégia fica bloqueada enquanto a sequência continuar
    na mesma cor. A quarta vela é vitória quando tem a cor oposta; doji é
    derrota para fins do filtro estatístico.
    """
    ordered = sorted(candles, key=lambda candle: candle.from_ts)
    outcomes: dict[CandleColor, list[bool]] = {"GREEN": [], "RED": [], "DOJI": []}
    streak_color: CandleColor | None = None
    streak_count = 0
    locked_color: CandleColor | None = None

    for index, candle in enumerate(ordered):
        color = candle_color(candle)

        if locked_color is not None:
            if color == "DOJI" or color != locked_color:
                locked_color = None
                streak_color = None if color == "DOJI" else color
                streak_count = 0 if color == "DOJI" else 1
            continue

        if color == "DOJI":
            streak_color = None
            streak_count = 0
            continue

        if color == streak_color:
            streak_count += 1
        else:
            streak_color = color
            streak_count = 1

        if streak_count == 3 and index + 1 < len(ordered):
            next_color = candle_color(ordered[index + 1])
            expected = "RED" if color == "GREEN" else "GREEN"
            outcomes[color].append(next_color == expected)
            locked_color = color

    resolved_symbol = symbol or (ordered[-1].symbol if ordered else "")
    result: dict[CandleColor, PatternStats] = {}
    for pattern_color in ("GREEN", "RED"):
        recent = outcomes[pattern_color][-sample_size:]
        wins = sum(recent)
        total = len(recent)
        result[pattern_color] = PatternStats(
            symbol=resolved_symbol,
            pattern_color=pattern_color,
            sample_size=total,
            wins=wins,
            accuracy=(wins / total) if total else 0.0,
        )
    return result


class LivePatternDetector:
    """Controla bloqueios e evita entradas sobrepostas por ativo."""

    def __init__(self) -> None:
        self._blocked: dict[str, CandleColor] = {}
        self._last_closed_seen: dict[str, int] = {}

    def seed(self, symbol: str, closed_candles: Iterable[Candle]) -> None:
        ordered = sorted(closed_candles, key=lambda candle: candle.from_ts)
        streak_color: CandleColor | None = None
        streak_count = 0
        for candle in ordered:
            color = candle_color(candle)
            if color == "DOJI":
                streak_color = None
                streak_count = 0
            elif color == streak_color:
                streak_count += 1
            else:
                streak_color = color
                streak_count = 1
        if ordered:
            self._last_closed_seen[symbol] = ordered[-1].from_ts
        if streak_color in {"GREEN", "RED"} and streak_count >= 3:
            self._blocked[symbol] = streak_color

    def observe_closed(self, symbol: str, candle: Candle) -> None:
        previous_ts = self._last_closed_seen.get(symbol)
        if previous_ts is not None and candle.from_ts <= previous_ts:
            return
        self._last_closed_seen[symbol] = candle.from_ts
        blocked_color = self._blocked.get(symbol)
        if blocked_color is None:
            return
        color = candle_color(candle)
        if color == "DOJI" or color != blocked_color:
            self._blocked.pop(symbol, None)

    def evaluate(
        self,
        symbol: str,
        candles: Iterable[Candle],
        stats: Mapping[CandleColor, PatternStats],
    ) -> Signal | None:
        if symbol in self._blocked:
            return None
        ordered = sorted(candles, key=lambda candle: candle.from_ts)
        if len(ordered) < 3:
            return None
        recent = ordered[-3:]
        colors = [candle_color(candle) for candle in recent]
        if colors[0] not in {"GREEN", "RED"} or len(set(colors)) != 1:
            return None
        pattern_color = colors[0]
        pattern_stats = stats.get(pattern_color)
        if pattern_stats is None or not pattern_stats.qualifies:
            return None
        self._blocked[symbol] = pattern_color
        return Signal(
            symbol=symbol,
            pattern_color=pattern_color,
            direction="DOWN" if pattern_color == "GREEN" else "UP",
            accuracy=pattern_stats.accuracy,
            wins=pattern_stats.wins,
            sample_size=pattern_stats.sample_size,
            candle_from=recent[-1].from_ts,
        )

    def unblock(self, symbol: str) -> None:
        self._blocked.pop(symbol, None)

    def is_blocked(self, symbol: str) -> bool:
        return symbol in self._blocked

