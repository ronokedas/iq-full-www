"""Diagnóstico: verificar cálculo das Bandas de Bollinger e volume de operações."""
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "dados" / "m1"
files = sorted(DATA_DIR.glob("*_otc.parquet"))

total_cand = 0
total_hh55 = 0
total_touch = 0
total_high_low = 0
total_hh55_hours = 0
total_touch_hours = 0

for path in files:
    df = pd.read_parquet(path)
    df = df[["from_ts", "open", "high", "low", "close"]].dropna().sort_values("from_ts").drop_duplicates("from_ts")
    # M5
    df["bucket"] = (df["from_ts"] // 300) * 300
    m5 = df.groupby("bucket").agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")
    ).reset_index()
    m5["dt"] = pd.to_datetime(m5["bucket"], unit="s", utc=True)
    m5["hour"] = m5["dt"].dt.hour
    m5["minute"] = m5["dt"].dt.minute
    # BB 14/2
    mid = m5["close"].rolling(14).mean()
    std = m5["close"].rolling(14).std(ddof=0)
    m5["up"] = mid + 2 * std
    m5["lo"] = mid - 2 * std

    total_cand += len(m5)

    # Todas as horas HH:55
    hh55 = m5[m5["minute"] == 55]
    total_hh55 += len(hh55)
    valid = hh55.dropna(subset=["up", "lo"])
    touch = valid[(valid["close"] >= valid["up"]) | (valid["close"] <= valid["lo"])]
    total_touch += len(touch)
    touch_hl = valid[(valid["high"] >= valid["up"]) | (valid["low"] <= valid["lo"])]
    total_high_low += len(touch_hl)

    # Apenas horas 10-13
    hh55_h = m5[(m5["minute"] == 55) & (m5["hour"].isin([10, 11, 12, 13]))]
    total_hh55_hours += len(hh55_h)
    valid_h = hh55_h.dropna(subset=["up", "lo"])
    touch_h = valid_h[(valid_h["close"] >= valid_h["up"]) | (valid_h["close"] <= valid_h["lo"])]
    total_touch_hours += len(touch_h)

print(f"Ativos: {len(files)}")
print(f"Total candles M5: {total_cand}")
print(f"Total candles HH:55 (todas as horas): {total_hh55}  -> por ativo: {total_hh55/len(files):.1f}")
print(f"  close tocando bandas: {total_touch} ({total_touch/total_hh55*100:.1f}%)")
print(f"  high/low tocando bandas: {total_high_low} ({total_high_low/total_hh55*100:.1f}%)")
print(f"Total candles HH:55 (horas 10-13): {total_hh55_hours}  -> por ativo: {total_hh55_hours/len(files):.1f}")
print(f"  close tocando bandas: {total_touch_hours} ({total_touch_hours/total_hh55_hours*100:.1f}%)")