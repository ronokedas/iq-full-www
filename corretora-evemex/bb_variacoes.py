"""Comparação profunda de variações de cálculo das Bandas de Bollinger.

Testa 4 formas de calcular as bandas e gerar sinais:
  A) BB no M5 (14/2), fechamento da vela M5 HH:55, close tocando banda  -> atual
  B) BB no M5 (14/2), fechamento HH:55, high/low tocando banda
  C) BB no H1 (14/2), close da vela H1 das 10-13h, close tocando banda
  D) BB no H1 (14/2), close da vela H1 das 10-13h, high/low tocando banda

A vitória de todas é medida na PRIMEIRA VELA M5 seguinte à formação do sinal
(entrada binária M5), mantendo o mesmo horizonte da estratégia original.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "dados" / "m1"
HOURS = (10, 11, 12, 13)
PAYOUT = 0.85


def resample(m1: pd.DataFrame, tf: int) -> pd.DataFrame:
    m1 = m1.copy()
    m1["bucket"] = (m1["from_ts"] // tf) * tf
    agg = (
        m1.groupby("bucket", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
        )
        .reset_index()
    )
    agg.rename(columns={"bucket": "from_ts"}, inplace=True)
    return agg


def bollinger(close: pd.Series, period: int = 14, num_std: float = 2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    return mid + num_std * std, mid - num_std * std


def signals_for(
    m1: pd.DataFrame, tf: int, hours: tuple[int, ...], use_high_low: bool
) -> pd.DataFrame:
    """Gera sinais e resultado na primeira vela M5 seguinte.

    tf=300 -> vela M5 HH:55; tf=3600 -> vela H1 HH:00.
    """
    df = resample(m1, tf)
    bb_up, bb_lo = bollinger(df["close"])
    df["up"] = bb_up
    df["lo"] = bb_lo
    df["dt"] = pd.to_datetime(df["from_ts"], unit="s", utc=True)
    df["hour"] = df["dt"].dt.hour
    df["minute"] = df["dt"].dt.minute

    # Candle avaliado
    if tf == 300:
        is_target = (df["minute"] == 55) & (df["hour"].isin(hours))
    else:
        is_target = (df["minute"] == 0) & (df["hour"].isin(hours))
    df["target"] = is_target & df["up"].notna()

    # Critério de toque
    if use_high_low:
        touch_up = df["high"] >= df["up"]
        touch_lo = df["low"] <= df["lo"]
    else:
        touch_up = df["close"] >= df["up"]
        touch_lo = df["close"] <= df["lo"]

    df["signal"] = np.where(
        df["target"] & touch_up, "DOWN",
        np.where(df["target"] & touch_lo, "UP", None),
    )

    # Próxima vela M5 (sempre M5 para manter horizonte binário)
    m5 = resample(m1, 300)
    # Mapa bucket -> close (sem shift, para evitar pegar a vela duas posições à frente)
    next_map = m5.set_index("from_ts")["close"].to_dict()
    # Mapeia o candle de sinal para o timestamp do próximo candle M5:
    # o sinal no M5 HH:55 ocorre no preço de close; a primeira vela M5 seguinte tem from_ts = HH+1:00

    def next_close_after(ts: int) -> float | None:
        if tf == 300:
            nxt = ts + 300
        else:
            nxt = ts + 3600
        return next_map.get(nxt)

    df["next_close"] = df["from_ts"].map(next_close_after)
    df["win"] = np.where(
        df["signal"] == "DOWN",
        df["next_close"] < df["close"],
        np.where(df["signal"] == "UP", df["next_close"] > df["close"], np.nan),
    )
    out = df[df["signal"].notna() & df["next_close"].notna()].copy()
    out["symbol"] = m1["symbol"].iloc[0]
    return out


def summarize(df: pd.DataFrame, payout: float) -> dict:
    if df.empty:
        return {"trades": 0, "wins": 0, "winrate": 0.0, "profit": 0.0, "pf": 0.0}
    wins = int(df["win"].sum())
    losses = len(df) - wins
    profit = wins * payout - losses
    pf = (wins * payout) / losses if losses else float("inf")
    return {
        "trades": len(df),
        "wins": wins,
        "winrate": round(wins / len(df) * 100, 2),
        "profit": round(profit, 2),
        "pf": round(pf, 2) if losses else float("inf"),
    }


def load_all() -> list[pd.DataFrame]:
    frames = []
    for path in sorted(DATA_DIR.glob("*_otc.parquet")):
        df = pd.read_parquet(path)
        df = df[["from_ts", "open", "high", "low", "close"]].dropna().sort_values("from_ts").drop_duplicates("from_ts")
        df["symbol"] = path.stem
        frames.append(df)
    return frames


def main() -> int:
    frames = load_all()
    print(f"Ativos carregados: {len(frames)}\n")

    variants = [
        ("A) BB M5 + close", 300, False),
        ("B) BB M5 + high/low", 300, True),
        ("C) BB H1 + close", 3600, False),
        ("D) BB H1 + high/low", 3600, True),
    ]

    results = {}
    for name, tf, use_hl in variants:
        all_sig = []
        for m1 in frames:
            try:
                sig = signals_for(m1, tf, HOURS, use_hl)
            except Exception as exc:
                print(f"  [erro] {m1['symbol'].iloc[0]}: {exc}")
                continue
            if not sig.empty:
                all_sig.append(sig)
        merged = pd.concat(all_sig, ignore_index=True) if all_sig else pd.DataFrame()
        s = summarize(merged, PAYOUT)
        results[name] = s
        print(f"{name}:")
        print(f"  Operações: {s['trades']:<5} | Wins: {s['wins']:<4} | "
              f"Acerto: {s['winrate']:.2f}% | Lucro: R$ {s['profit']:.2f} | PF: {s['pf']}")

    print("\n" + "=" * 70)
    print("RESUMO — qual variação gera mais operações e melhor acertividade")
    print("=" * 70)
    for name, s in results.items():
        print(f"  {name:<22} | ops={s['trades']:<5} | acerto={s['winrate']:>6.2f}% | lucro=R${s['profit']:>8.2f} | PF={s['pf']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())