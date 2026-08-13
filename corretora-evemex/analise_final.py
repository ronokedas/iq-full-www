"""Análise final da Estratégia 17 — busca a melhor configuração de acertividade.

Testa:
  1. Baseline (BB 14/2 M5, HH:55, close vs banda)
  2. Filtro de cor da vela atual (DOWN: verde, UP: vermelha)
  3. Por tipo de ativo (FX vs outros)
  4. Por hora individual
  5. Margem de toque (quão além da banda o close fechou)
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "dados" / "m1"
HOURS = (10, 11, 12, 13)
PAYOUT = 0.85

# Pares de moedas (FX) — o resto é índice/cripto/commodity
FX_PREFIXES = ("EUR", "GBP", "USD", "AUD", "NZD", "CAD", "CHF", "JPY")


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
    m5["cur_green"] = m5["close"] > m5["open"]
    m5["cur_red"] = m5["close"] < m5["open"]
    m5["next_close"] = m5["close"].shift(-1)
    m5["win"] = np.where(
        m5["signal"] == "DOWN",
        m5["next_close"] < m5["close"],
        np.where(m5["signal"] == "UP", m5["next_close"] > m5["close"], np.nan),
    )
    # Margem de toque: distância relativa do close à banda
    m5["margem_up"] = (m5["close"] - m5["up"]) / m5["up"] * 100
    m5["margem_lo"] = (m5["lo"] - m5["close"]) / m5["lo"] * 100
    out = m5[m5["signal"].notna() & m5["next_close"].notna()].copy()
    out["symbol"] = m1["symbol"].iloc[0]
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
    merged["is_fx"] = merged["symbol"].str.startswith(FX_PREFIXES)

    print(f"Sinais base: {len(merged)} | Acerto: {summarize(merged, PAYOUT)['winrate']}%")

    # 1. Filtro de cor da vela atual
    cor_filtro = ((merged["signal"] == "DOWN") & merged["cur_green"]) | (
        (merged["signal"] == "UP") & merged["cur_red"]
    )
    s = summarize(merged[cor_filtro], PAYOUT)
    print(f"\nFiltro cor vela atual (DOWN: verde, UP: vermelha): ops={s['trades']} "
          f"acerto={s['winrate']}% lucro=R${s['profit']}")

    # 2. Por tipo de ativo
    print("\nPor tipo de ativo:")
    for nome, mask in [("FX (pares de moedas)", merged["is_fx"]), ("Não-FX", ~merged["is_fx"])]:
        s = summarize(merged[mask], PAYOUT)
        print(f"  {nome}: ops={s['trades']} acerto={s['winrate']}% lucro=R${s['profit']}")

    # 3. Por hora
    print("\nPor hora (UTC):")
    for hora in sorted(merged["hour"].unique()):
        s = summarize(merged[merged["hour"] == hora], PAYOUT)
        print(f"  {hora}:55 -> ops={s['trades']} acerto={s['winrate']}% lucro=R${s['profit']}")

    # 4. Margem de toque
    print("\nMargem de toque (quão além da banda):")
    merged["margem"] = np.where(
        merged["signal"] == "DOWN", merged["margem_up"], merged["margem_lo"]
    )
    for limiar in [0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5]:
        sub = merged[merged["margem"] >= limiar]
        s = summarize(sub, PAYOUT)
        print(f"  margem >= {limiar}%: ops={s['trades']} acerto={s['winrate']}% lucro=R${s['profit']}")

    # 5. Top ativos por acerto (com >= 5 ops)
    print("\nTop ativos por acerto (>= 5 operações):")
    rows = []
    for symbol, group in merged.groupby("symbol"):
        s = summarize(group, PAYOUT)
        if s["trades"] >= 5:
            rows.append((symbol, s))
    rows.sort(key=lambda x: x[1]["winrate"], reverse=True)
    for symbol, s in rows[:10]:
        print(f"  {symbol:<20} ops={s['trades']:<4} acerto={s['winrate']:>6.2f}% lucro=R${s['profit']:>7.2f}")

    # 6. Melhor combinação: FX + cor da vela atual
    combo = cor_filtro & merged["is_fx"]
    s = summarize(merged[combo], PAYOUT)
    print(f"\nCombinação FX + cor vela atual: ops={s['trades']} acerto={s['winrate']}% lucro=R${s['profit']}")


if __name__ == "__main__":
    main()