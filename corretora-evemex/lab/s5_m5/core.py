"""Detector e backtest puro da S5-M5; reutiliza a regra canônica."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Permite executar ``python lab/s5_m5/backtest.py`` sem instalar o projeto.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from s5_m5_rules import (
    COMMAND_VALIDITY_SECONDS, M1_SECONDS, M5_SECONDS, Command, aggregate_complete_m5,
    candle_touches, commands_from_m5, confirmed_direction, select_most_recent_touch,
)


def backtest_asset(m1: pd.DataFrame, symbol: str) -> tuple[list[dict], dict[str, int]]:
    """Executa S5-M5 em um ativo e retorna operações e métricas de cobertura."""
    frame = m1.sort_values("from_ts").drop_duplicates("from_ts").reset_index(drop=True)
    m5 = aggregate_complete_m5(frame)
    commands = commands_from_m5(m5)
    active, trades, skipped_no_result = list(commands), [], 0
    records = frame.to_dict("records")
    for index, candle in enumerate(records):
        selected, consumed = select_most_recent_touch(active, candle)
        if not consumed:
            continue
        consumed_ids = set(consumed)
        active = [command for command in active if command not in consumed_ids]
        direction = confirmed_direction(selected, candle) if selected else None
        if not direction:
            continue
        if index + 1 >= len(records) or int(records[index + 1]["from_ts"]) != int(candle["from_ts"]) + M1_SECONDS:
            skipped_no_result += 1
            continue
        result = records[index + 1]
        win = (direction == "UP" and float(result["close"]) > float(result["open"])) or (direction == "DOWN" and float(result["close"]) < float(result["open"]))
        trades.append({
            "symbol": symbol, "command_from_ts": selected.formed_at, "touch_from_ts": int(candle["from_ts"]),
            "entry_from_ts": int(result["from_ts"]), "direction": direction, "command_color": selected.color,
            "level": selected.level, "target": int(win),
        })
    metrics = {
        "m1_rows": len(frame), "m5_complete": len(m5), "commands": len(commands), "trades": len(trades),
        "skipped_no_result": skipped_no_result, "gaps": int((frame.from_ts.diff().dropna() != M1_SECONDS).sum()),
    }
    return trades, metrics
