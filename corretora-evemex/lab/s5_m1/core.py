"""Detector e backtest puro da S5-M1; não importa o robô de produção."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

M1_SECONDS = 60
COMMAND_VALIDITY_CANDLES = 20


@dataclass(frozen=True)
class Command:
    formed_at: int
    available_at: int
    expires_at: int
    level: float
    color: str  # GREEN ou RED


def commands_from_m1(m1: pd.DataFrame) -> list[Command]:
    """Identifica comandos M1 com igualdade estrita no preço de abertura."""
    commands: list[Command] = []
    for row in m1.sort_values("from_ts").drop_duplicates("from_ts").itertuples(index=False):
        if row.close > row.open and row.low == row.open:
            color = "GREEN"
        elif row.close < row.open and row.high == row.open:
            color = "RED"
        else:
            continue
        available_at = int(row.from_ts) + M1_SECONDS
        commands.append(Command(int(row.from_ts), available_at, available_at + COMMAND_VALIDITY_CANDLES * M1_SECONDS, float(row.open), color))
    return commands


def candle_touches(candle: pd.Series | dict, level: float) -> bool:
    return float(candle["low"]) <= level <= float(candle["high"])


def select_most_recent_touch(commands: Iterable[Command], candle: pd.Series | dict) -> tuple[Command | None, list[Command]]:
    """Retorna o comando recente e todos os níveis que o primeiro toque consumiu."""
    touched = [command for command in commands if command.available_at <= int(candle["from_ts"]) < command.expires_at and candle_touches(candle, command.level)]
    return (max(touched, key=lambda command: command.formed_at) if touched else None), touched


def confirmed_direction(command: Command, candle: pd.Series | dict) -> str | None:
    open_, close = float(candle["open"]), float(candle["close"])
    if command.color == "GREEN" and close < open_ and close > command.level:
        return "UP"
    if command.color == "RED" and close > open_ and close < command.level:
        return "DOWN"
    return None


def backtest_asset(m1: pd.DataFrame, symbol: str) -> tuple[list[dict], dict[str, int]]:
    frame = m1.sort_values("from_ts").drop_duplicates("from_ts").reset_index(drop=True)
    duplicates = int(m1.from_ts.duplicated().sum())
    commands = commands_from_m1(frame)
    active, next_command, trades, skipped_no_result, invalidated = [], 0, [], 0, 0
    records = frame.to_dict("records")
    for index, candle in enumerate(records):
        timestamp = int(candle["from_ts"])
        while next_command < len(commands) and commands[next_command].available_at <= timestamp:
            active.append(commands[next_command])
            next_command += 1
        # Comandos já expirados nunca poderão participar de um toque futuro.
        active = [command for command in active if command.expires_at > timestamp]
        selected, consumed = select_most_recent_touch(active, candle)
        if not consumed:
            continue
        consumed_ids = set(consumed)
        active = [command for command in active if command not in consumed_ids]
        direction = confirmed_direction(selected, candle) if selected else None
        if not direction:
            invalidated += 1
            continue
        if index + 1 >= len(records) or int(records[index + 1]["from_ts"]) != int(candle["from_ts"]) + M1_SECONDS:
            skipped_no_result += 1
            continue
        result = records[index + 1]
        win = ((direction == "UP" and float(result["close"]) > float(result["open"]))
               or (direction == "DOWN" and float(result["close"]) < float(result["open"])))
        trades.append({
            "symbol": symbol, "command_from_ts": selected.formed_at, "touch_from_ts": int(candle["from_ts"]),
            "entry_from_ts": int(result["from_ts"]), "direction": direction, "command_color": selected.color,
            "level": selected.level, "target": int(win),
        })
    return trades, {
        "m1_rows": len(frame), "duplicates": duplicates, "commands": len(commands),
        "first_touches_invalidated": invalidated, "trades": len(trades), "skipped_no_result": skipped_no_result,
        "gaps": int((frame.from_ts.diff().dropna() != M1_SECONDS).sum()),
    }
