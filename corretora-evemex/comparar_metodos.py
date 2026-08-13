"""Compara trade a trade os métodos do bb_pavil e do bb_variacoes em todos os ativos.

Identifica:
  1. Sinais que existem em um método mas não no outro
  2. Sinais em comum com win diferente
"""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "dados" / "m1"
HOURS = (10, 11, 12, 13)


def resample_m5(m1: pd.DataFrame) -> pd.DataFrame:
    m1 = m1.copy()
    m1["bucket"] = (m1["from_ts"] // 300) * 300
    agg = (
        m1.groupby("bucket", sort=True)
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
        .reset_index()
    )
    agg.rename(columns={"bucket": "from_ts"}, inplace=True)
    return agg


def metodo_pavil(m5: pd.DataFrame) -> pd.DataFrame:
    """Reproduz generate_signals do bb_pavil (modo hh55)."""
    df = m5.copy()
    df["dt"] = pd.to_datetime(df["from_ts"], unit="s", utc=True)
    df["hour_utc"] = df["dt"].dt.hour
    df["minute_utc"] = df["dt"].dt.minute
    mid = df["close"].rolling(14).mean()
    std = df["close"].rolling(14).std(ddof=0)
    df["bb_upper"] = mid + 2 * std
    df["bb_lower"] = mid - 2 * std
    df["next_close"] = df["close"].shift(-1)
    is_target = (df["minute_utc"] == 55) & (df["hour_utc"].isin(HOURS))
    df["signal"] = np.where(
        is_target & (df["close"] >= df["bb_upper"]), "DOWN",
        np.where(is_target & (df["close"] < df["bb_lower"]), "UP", None),
    )
    df["win"] = np.where(
        df["signal"] == "DOWN",
        df["next_close"] < df["close"],
        np.where(df["signal"] == "UP", df["next_close"] > df["close"], np.nan),
    )
    out = df[df["signal"].notna() & df["next_close"].notna()].copy()
    return out


def metodo_variacoes(m1: pd.DataFrame) -> pd.DataFrame:
    """Reproduz signals_for do bb_variacoes (tf=300, close)."""
    df = resample_m5(m1)
    mid = df["close"].rolling(14).mean()
    std = df["close"].rolling(14).std(ddof=0)
    df["up"] = mid + 2 * std
    df["lo"] = mid - 2 * std
    df["dt"] = pd.to_datetime(df["from_ts"], unit="s", utc=True)
    df["hour"] = df["dt"].dt.hour
    df["minute"] = df["dt"].dt.minute
    is_target = (df["minute"] == 55) & (df["hour"].isin(HOURS))
    df["target"] = is_target & df["up"].notna()

    touch_up = df["close"] >= df["up"]
    touch_lo = df["close"] <= df["lo"]
    df["signal"] = np.where(
        df["target"] & touch_up, "DOWN",
        np.where(df["target"] & touch_lo, "UP", None),
    )

    m5 = resample_m5(m1)
    m5["next_close"] = m5["close"].shift(-1)
    next_map = m5.set_index("from_ts")["next_close"].to_dict()
    df["next_close"] = df["from_ts"].map(lambda ts: next_map.get(ts + 300))
    df["win"] = np.where(
        df["signal"] == "DOWN",
        df["next_close"] < df["close"],
        np.where(df["signal"] == "UP", df["next_close"] > df["close"], np.nan),
    )
    out = df[df["signal"].notna() & df["next_close"].notna()].copy()
    return out


total_only_pavil = 0
total_only_variacoes = 0
total_win_diff = 0
sample_diff = []

for path in sorted(DATA_DIR.glob("*_otc.parquet")):
    symbol = path.stem
    m1 = pd.read_parquet(path)
    m1 = m1[["from_ts", "open", "high", "low", "close"]].dropna().sort_values("from_ts").drop_duplicates("from_ts")
    if len(m1) < 30 * 5:
        continue
    m5 = resample_m5(m1)

    p = metodo_pavil(m5)
    v = metodo_variacoes(m1)

    p_key = set(zip(p["from_ts"], p["signal"]))
    v_key = set(zip(v["from_ts"], v["signal"]))

    only_p = p_key - v_key
    only_v = v_key - p_key
    common = p_key & v_key

    total_only_pavil += len(only_p)
    total_only_variacoes += len(only_v)

    # Comparar wins nos comuns
    p_idx = p.set_index(["from_ts", "signal"])["win"]
    v_idx = v.set_index(["from_ts", "signal"])["win"]
    for k in common:
        wp = p_idx.get(k)
        wv = v_idx.get(k)
        if wp != wv and not (pd.isna(wp) and pd.isna(wv)):
            total_win_diff += 1
            if len(sample_diff) < 8:
                t = pd.to_datetime(k[0], unit="s", utc=True)
                sample_diff.append(
                    f"  {symbol} {t} {k[1]}: pavil_win={wp} var_win={wv} "
                    f"close={p.loc[(p['from_ts']==k[0])&(p['signal']==k[1]),'close'].iloc[0]:.5f} "
                    f"next_pavil={p.loc[(p['from_ts']==k[0])&(p['signal']==k[1]),'next_close'].iloc[0]:.5f} "
                    f"next_var={v.loc[(v['from_ts']==k[0])&(v['signal']==k[1]),'next_close'].iloc[0]:.5f}"
                )

print(f"Sinais só no pavil:       {total_only_pavil}")
print(f"Sinais só no variações:   {total_only_variacoes}")
print(f"Sinais em comum p/ win diferente: {total_win_diff}")
print("\nAmostras de divergência (win diferente):")
for s in sample_diff:
    print(s)