"""Executável do backtest isolado S5-M15."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from core import backtest_asset

BASE = Path(__file__).resolve().parents[2]
DATA_DIR = BASE / "dados" / "m1"
OUTPUT_DIR = Path(__file__).resolve().parent / "results"


def _summary(frame: pd.DataFrame, group: str | None = None) -> pd.DataFrame:
    grouped = frame.groupby(group) if group else [("Geral", frame)]
    rows = []
    for name, values in grouped:
        wins, trades = int(values.target.sum()), len(values)
        rows.append({group or "escopo": name, "operacoes": trades, "vitorias": wins, "derrotas": trades - wins, "taxa_acerto": wins / trades if trades else 0.0})
    return pd.DataFrame(rows).sort_values("taxa_acerto", ascending=False)


def _table(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    rows = ["| " + " | ".join(f"{value:.2%}" if col == "taxa_acerto" else str(value) for col, value in zip(columns, values)) + " |" for values in frame.itertuples(index=False, name=None)]
    return "\n".join(["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"] + rows)


def run() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    all_trades, coverage = [], []
    for path in sorted(DATA_DIR.glob("*.parquet")):
        trades, metrics = backtest_asset(pd.read_parquet(path), path.stem)
        all_trades.extend(trades)
        coverage.append({"symbol": path.stem, **metrics})
    trades = pd.DataFrame(all_trades)
    if trades.empty:
        raise RuntimeError("Nenhuma operação S5-M15 encontrada")
    trades["hour_brasilia"] = pd.to_datetime(trades.entry_from_ts, unit="s", utc=True).dt.tz_convert(ZoneInfo("America/Sao_Paulo")).dt.hour
    trades.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    coverage_frame = pd.DataFrame(coverage)
    coverage_frame.to_csv(OUTPUT_DIR / "coverage.csv", index=False)
    overall, by_asset, by_hour = _summary(trades), _summary(trades, "symbol"), _summary(trades, "hour_brasilia")
    report = OUTPUT_DIR / "REPORT.md"
    report.write_text("\n".join(["# Backtest isolado — S5-M15", "", "Dados: parquets M1 locais. Nenhum componente do robô de produção foi alterado.", "", "## Geral", "", _table(overall), "", "## Por ativo", "", _table(by_asset), "", "## Por hora (Brasília)", "", _table(by_hour), "", "## Cobertura", "", f"Ativos: {len(coverage_frame)} | candles duplicados: {int(coverage_frame.duplicates.sum())} | gaps M1: {int(coverage_frame.gaps.sum())} | M15 completos: {int(coverage_frame.m15_complete.sum())} | comandos: {int(coverage_frame.commands.sum())} | primeiros toques invalidados: {int(coverage_frame.first_touches_invalidated.sum())} | operações sem vela de resultado: {int(coverage_frame.skipped_no_result.sum())}."]) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(f"Relatório salvo em {run()}")
