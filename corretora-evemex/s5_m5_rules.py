"""Regras canônicas da estratégia S5-M5, usadas no laboratório, treino e robô."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

import pandas as pd

COMMAND_VALIDITY_SECONDS = 20 * 60
M1_SECONDS = 60
M5_SECONDS = 5 * 60


@dataclass(frozen=True)
class Command:
    formed_at: int
    available_at: int
    expires_at: int
    level: float
    color: str  # GREEN ou RED
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0


def aggregate_complete_m5(m1: pd.DataFrame) -> pd.DataFrame:
    """Agrupa somente blocos M5 alinhados, completos e sem gaps internos."""
    frame = m1.sort_values("from_ts").drop_duplicates("from_ts").copy()
    frame["bucket"] = (frame["from_ts"] // M5_SECONDS) * M5_SECONDS
    m5 = frame.groupby("bucket", sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        candles=("from_ts", "count"), first_ts=("from_ts", "first"), last_ts=("from_ts", "last"),
    ).reset_index().rename(columns={"bucket": "from_ts"})
    complete = (m5.candles == 5) & (m5.first_ts == m5.from_ts) & (m5.last_ts == m5.from_ts + 4 * M1_SECONDS)
    return m5.loc[complete, ["from_ts", "open", "high", "low", "close"]].reset_index(drop=True)


def commands_from_m5(m5: pd.DataFrame) -> list[Command]:
    commands: list[Command] = []
    for row in m5.itertuples(index=False):
        if row.close > row.open and row.low == row.open:
            color = "GREEN"
        elif row.close < row.open and row.high == row.open:
            color = "RED"
        else:
            continue
        available_at = int(row.from_ts) + M5_SECONDS
        commands.append(Command(int(row.from_ts), available_at, available_at + COMMAND_VALIDITY_SECONDS, float(row.open), color,
                                float(row.open), float(row.high), float(row.low), float(row.close)))
    return commands


def candle_touches(candle: pd.Series | dict, level: float) -> bool:
    return float(candle["low"]) <= level <= float(candle["high"])


def select_most_recent_touch(commands: Iterable[Command], candle: pd.Series | dict) -> tuple[Command | None, list[Command]]:
    """Retorna o comando mais recente e todos os comandos consumidos pelo toque."""
    touched = [command for command in commands if command.available_at <= int(candle["from_ts"]) < command.expires_at and candle_touches(candle, command.level)]
    return (max(touched, key=lambda command: command.formed_at) if touched else None), touched


def confirmed_direction(command: Command, candle: pd.Series | dict) -> str | None:
    open_, close = float(candle["open"]), float(candle["close"])
    if command.color == "GREEN" and close < open_ and close > command.level:
        return "UP"
    if command.color == "RED" and close > open_ and close < command.level:
        return "DOWN"
    return None


def iter_s5_m5_events(m1: pd.DataFrame) -> Iterator[tuple[Command, dict, str]]:
    """Emite apenas os primeiros toques confirmados, em ordem cronológica."""
    frame = m1.sort_values("from_ts").drop_duplicates("from_ts").reset_index(drop=True)
    active = commands_from_m5(aggregate_complete_m5(frame))
    for candle in frame.to_dict("records"):
        selected, consumed = select_most_recent_touch(active, candle)
        if not consumed:
            continue
        consumed_ids = set(consumed)
        active = [command for command in active if command not in consumed_ids]
        direction = confirmed_direction(selected, candle) if selected else None
        if direction:
            yield selected, candle, direction
