"""Testa filtros de cor da vela atual e da próxima vela para a Estratégia 17.

Variação base: BB 14/2 no M5, candle HH:55, close >= banda sup -> DOWN,
close < banda inf -> UP, vitória na primeira vela M5 seguinte.

Combinações testadas:
  - Sem filtro de cor (baseline)
  - Vela atual VERMELHA p/ DOWN (reversão) e VERDE p/ UP
  - Próxima vela VERMELHA p/ DOWN (apostar na vela vermelha) e VERDE p/ UP
  - Combinação das duas
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "dados" / "m1"
HOURS = (10, 11, 12, 13)
PAYOUT = 0.85


def resample(m1: pd.DataFrame, tf: int) -> pd.DataFrame:
    m1 = m1.copy()
    m1["bucket"] = (m1["from_ts"] // tf) * tf
    agg = (
        m1.groupby("bucket", sort=True)
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
        .reset_index()
    )
    agg.rename(columns={"bucket": "from_ts"}, inplace=True)
    return agg


def load_all() -> list[pd.DataFrame]:
    frames = []
    for path in sorted(DATA_DIR.glob("*_otc.parquet")):
        df = pd.read_parquet(path)
        df = df[["from_ts", "open", "high", "low", "close"]].dropna().sort_values("from_ts").drop_duplicates("from_ts")
        df["symbol"] = path.stem
        frames.append(df)
    return frames


def base_signals(m1: pd.DataFrame) -> pd.DataFrame:
    m5 = resample(m1, 300)
    mid = m5["close"].rolling(14).mean()
    std = m5["close"].rolling(14).std(ddof=0)
    m5["up"] = mid + 2 * std
    m5["lo"] = mid - 2 * std
    m5["dt"] = pd.to_datetime(m5["from_ts"], unit="s", utc=True)
    m5["hour"] = m5["dt"].dt.hour
    m5["minute"] = m5["dt"].dt.minute
    is_target = (m5["minute"] == 55) & (m5["hour"].isin(HOURS)) & m5["up"].notna()
    m5["signal"] = np.where(
        is_target & (m5["close"] >= m5["up"]), "DOWN",
        np.where(is_target & (m5["close"] < m5["lo"]), "UP", None),
    )
    # vela atual / próxima
    m5["cur_green"] = m5["close"] > m5["open"]
    m5["cur_red"] = m5["close"] < m5["open"]
    m5["next_open"] = m5["open"].shift(-1)
    m5["next_close"] = m5["close"].shift(-1)
    m5["next_green"] = m5["next_close"] > m5["next_open"]
    m5["next_red"] = m5["next_close"] < m5["next_open"]
    m5["win"] = np.where(
        m5["signal"] == "DOWN",
        m5["next_close"] < m5["close"],
        np.where(m5["signal"] == "UP", m5["next_close"] > m5["close"], np.nan),
    )
    out = m5[m5["signal"].notna() & m5["next_close"].notna()].copy()
    return out


def summarize(df: pd.DataFrame, payout: float) -> dict:
    if df.empty:
        return {"trades": 0, "wins": 0, "winrate": 0.0, "profit": 0.0}
    wins = int(df["win"].sum())
    losses = len(df) - wins
    return {
        "trades": len(df),
        "wins": wins,
        "winrate": round(wins / len(df) * 100, 2),
        "profit": round(wins * payout - losses, 2),
    }


def main():
    frames = load_all()
    all_sig = []
    for m1 in frames:
        sig = base_signals(m1)
        if not sig.empty:
            all_sig.append(sig)
    merged = pd.concat(all_sig, ignore_index=True)
    print(f"Sinais base: {len(merged)}")

    filtros = {
        "Baseline (sem filtro de cor)": np.ones(len(merged), dtype=bool),
        "DOWN: vela atual VERMELHA | UP: vela atual VERDE": (
            ((merged["signal"] == "DOWN") & merged["cur_red"])
            | ((merged["signal"] == "UP") & merged["cur_green"])
        ),
        "DOWN: vela atual VERDE | UP: vela atual VERMELHA": (
            ((merged["signal"] == "DOWN") & merged["cur_green"])
            | ((merged["signal"] == "UP") & merged["cur_red"])
        ),
        "DOWN: próxima vela VERMELHA | UP: próxima VERDE": (
            ((merged["signal"] == "DOWN") & merged["next_red"])
            | ((merged["signal"] == "UP") & merged["next_green"])
        ),
        "DOWN: próxima vela VERDE | UP: próxima VERMELHA": (
            ((merged["signal"] == "DOWN") & merged["next_green"])
            | ((merged["signal"] == "UP") & merged["next_red"])
        ),
        "DOWN: atual VERMELHA e próx VERMELHA | UP: atual VERDE e próx VERDE": (
            ((merged["signal"] == "DOWN") & merged["cur_red"] & merged["next_red"])
            | ((merged["signal"] == "UP") & merged["cur_green"] & merged["next_green"])
        ),
        "DOWN: atual VERDE e próx VERDE | UP: atual VERMELHA e próx VERMELHA": (
            ((merged["signal"] == "DOWN") & merged["cur_green"] & merged["next_green"])
            | ((merged["signal"] == "UP") & merged["cur_red"] & merged["next_red"])
        ),
    }

    print(f"\n{'Filtro':<58} | {'Ops':>4} | {'WIN':>4} | {'Acerto':>7} | {'Lucro':>9}")
    print("-" * 96)
    for name, mask in filtros.items():
        sub = merged[mask]
        s = summarize(sub, PAYOUT)
        print(f"{name:<58} | {s['trades']:>4} | {s['wins']:>4} | {s['winrate']:>6.2f}% | R$ {s['profit']:>7.2f}")

    # Detalhamento do melhor filtro por direção
    print("\nDetalhe por direção (baseline):")
    for direcao in ["DOWN", "UP"]:
        sub = merged[merged["signal"] == direcao]
        s = summarize(sub, PAYOUT)
        print(f"  {direcao}: ops={s['trades']} wins={s['wins']} acerto={s['winrate']}% lucro=R${s['profit']}")

    # Separar acerto da cor da vela atual dentro de cada direção
    print("\nAcerto por cor da vela ATUAL dentro de cada direção:")
    for direcao in ["DOWN", "UP"]:
        sub = merged[merged["signal"] == direcao]
        red = sub[sub["cur_red"]]
        green = sub[sub["cur_green"]]
        sr = summarize(red, PAYOUT)
        sg = summarize(green, PAYOUT)
        print(f"  {direcao} | vela atual VERMELHA: ops={sr['trades']} acerto={sr['winrate']}% | "
              f"VERDE: ops={sg['trades']} acerto={sg['winrate']}%")

    print("\nAcerto por cor da PRÓXIMA vela dentro de cada direção:")
    for direcao in ["DOWN", "UP"]:
        sub = merged[merged["signal"] == direcao]
        red = sub[sub["next_red"]]
        green = sub[sub["next_green"]]
        sr = summarize(red, PAYOUT)
        sg = summarize(green, PAYOUT)
        print(f"  {direcao} | próxima VERMELHA: ops={sr['trades']} acerto={sr['winrate']}% | "
              f"VERDE: ops={sg['trades']} acerto={sg['winrate']}%")


if __name__ == "__main__":
    main()