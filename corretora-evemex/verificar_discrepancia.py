"""Verifica linha a linha a discrepância de acerto entre as duas implementações."""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "dados" / "m1"
HOURS = (10, 11, 12, 13)

path = DATA_DIR / "GOLD_otc.parquet"
m1 = pd.read_parquet(path)
m1 = m1[["from_ts", "open", "high", "low", "close"]].dropna().sort_values("from_ts").drop_duplicates("from_ts")

# --- Método do bb_pavil (shift -1 no M5) ---
m1 = m1.copy()
m1["bucket"] = (m1["from_ts"] // 300) * 300
m5 = m1.groupby("bucket").agg(
    open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")
).reset_index()
m5.rename(columns={"bucket": "from_ts"}, inplace=True)
m5 = m5.sort_values("from_ts").reset_index(drop=True)

mid = m5["close"].rolling(14).mean()
std = m5["close"].rolling(14).std(ddof=0)
m5["up"] = mid + 2 * std
m5["lo"] = mid - 2 * std

m5["dt"] = pd.to_datetime(m5["from_ts"], unit="s", utc=True)
m5["hour"] = m5["dt"].dt.hour
m5["minute"] = m5["dt"].dt.minute
m5["next_close_shift"] = m5["close"].shift(-1)
m5["next_open_shift"] = m5["open"].shift(-1)

cand = (m5["minute"] == 55) & (m5["hour"].isin(HOURS))
m5["signal"] = np.where(
    cand & (m5["close"] >= m5["up"]), "DOWN",
    np.where(cand & (m5["close"] < m5["lo"]), "UP", None),
)

sig_rows = m5[m5["signal"].notna()].copy()
print(f"Sinais GOLD: {len(sig_rows)}")

# win com shift
sig_rows["win_shift"] = np.where(
    sig_rows["signal"] == "DOWN",
    sig_rows["next_close_shift"] < sig_rows["close"],
    np.where(sig_rows["signal"] == "UP", sig_rows["next_close_shift"] > sig_rows["close"], np.nan),
)

# --- Método do bb_variacoes (mapa ts+300) ---
next_map = m5.set_index("from_ts")["close"].shift(-1).to_dict()

def get_next(ts):
    return next_map.get(ts + 300)

sig_rows["next_close_map"] = sig_rows["from_ts"].map(get_next)
sig_rows["win_map"] = np.where(
    sig_rows["signal"] == "DOWN",
    sig_rows["next_close_map"] < sig_rows["close"],
    np.where(sig_rows["signal"] == "UP", sig_rows["next_close_map"] > sig_rows["close"], np.nan),
)

# Comparação
sig_rows["diferente"] = sig_rows["win_shift"] != sig_rows["win_map"]
print("\nLinhas com win diferente:")
for _, r in sig_rows[sig_rows["diferente"]].iterrows():
    print(
        f"  {pd.to_datetime(r['from_ts'], unit='s', utc=True)} | {r['signal']} | "
        f"close={r['close']:.2f} | next_shift={r['next_close_shift']:.2f} (win={r['win_shift']}) | "
        f"next_map={r['next_close_map']:.2f} (win={r['win_map']})"
    )

print(f"\nwin_shift: {int(sig_rows['win_shift'].sum())}/{len(sig_rows)} = {sig_rows['win_shift'].mean()*100:.2f}%")
print(f"win_map:   {int(sig_rows['win_map'].sum())}/{len(sig_rows)} = {sig_rows['win_map'].mean()*100:.2f}%")