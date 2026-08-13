"""Features canônicas: as mesmas colunas no dataset e no robô."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Sequence

import numpy as np
import pandas as pd


M1_FEATURES = [
    "atr_14", "std_14", "trend_slope", "hour_sin", "hour_cos", "rsi_14",
    "atr_pct", "dist_ema9", "dist_ema21", "body_ratio", "avg_body_5",
    "dist_res_h1", "dist_sup_h1",
]
M5_FEATURES = [
    "atr_14", "std_14", "trend_slope", "hour_sin", "hour_cos",
    "dist_res_m15", "dist_sup_m15", "dist_res_h1", "dist_sup_h1",
]
S5_M5_FEATURES = M1_FEATURES + [
    "command_age_m1", "command_body_ratio", "command_range_pct",
    "touch_close_level_ratio", "touch_body_ratio", "direction_up",
]

# S01 possui um modelo próprio. Estas features não substituem M1_FEATURES para
# não alterar a distribuição do modelo S13 já publicado.
S01_FEATURES = [
    "atr_14", "atr_pct", "rsi_14", "adx_14", "plus_di_14", "minus_di_14",
    "bb_position", "bb_width_pct", "trend_slope", "ema9_slope", "ema21_slope",
    "ema_gap_pct", "dist_ema9", "dist_ema21", "body_ratio", "upper_wick_ratio",
    "lower_wick_ratio", "sequence_move_atr", "v1_body_atr", "v2_body_atr",
    "v3_body_atr", "direction_up", "hour_sin", "hour_cos",
]
S13_FEATURES = [
    "atr_14", "atr_pct", "rsi_14", "adx_14", "plus_di_14", "minus_di_14",
    "bb_position", "bb_width_pct", "trend_slope", "dist_ema9", "dist_ema21",
    "body_ratio", "upper_wick_ratio", "lower_wick_ratio", "v1_wick_ratio",
    "v1_body_atr", "v2_body_atr", "v3_body_atr", "level_distance_atr",
    "direction_up", "hour_sin", "hour_cos",
]


def candles_to_frame(candles: Sequence[Any]) -> pd.DataFrame:
    rows = [asdict(candle) if hasattr(candle, "__dataclass_fields__") else dict(candle) for candle in candles]
    return pd.DataFrame(rows).sort_values("from_ts").drop_duplicates("from_ts").reset_index(drop=True)


def m1_feature_frame(candles: pd.DataFrame) -> pd.DataFrame:
    df = candles.sort_values("from_ts").copy()
    close, high, low, open_ = (df[name].astype(float) for name in ("close", "high", "low", "open"))
    ema9, ema21 = close.ewm(span=9, adjust=False).mean(), close.ewm(span=21, adjust=False).mean()
    dt = pd.to_datetime(df["from_ts"], unit="s")
    scale = np.where(close < 100, 1e-4, 1e-2)
    result = pd.DataFrame(index=df.index)
    result["atr_14"] = (high - low).rolling(14).mean()
    result["std_14"] = close.rolling(14).std()
    result["trend_slope"] = (ema9 - ema21) / ema21 * 100
    result["hour_sin"] = np.sin(2 * np.pi * dt.dt.hour / 24)
    result["hour_cos"] = np.cos(2 * np.pi * dt.dt.hour / 24)
    result["rsi_14"] = 50.0
    result["atr_pct"] = 0.1
    result["dist_ema9"] = (close - ema9) / ema9 * 100
    result["dist_ema21"] = (close - ema21) / ema21 * 100
    result["body_ratio"] = abs(close - open_) / (high - low + 1e-9)
    result["avg_body_5"] = abs(close - open_).rolling(5).mean()
    result["dist_res_h1"] = (high.rolling(60).max() - close) / scale
    result["dist_sup_h1"] = (close - low.rolling(60).min()) / scale
    return result[M1_FEATURES]


def s01_feature_frame(candles: pd.DataFrame, directions: Sequence[str] | None = None) -> pd.DataFrame:
    """Features de reversão S01 calculadas somente até o fechamento atual."""
    df = candles.sort_values("from_ts").copy()
    close, high, low, open_ = (df[name].astype(float) for name in ("close", "high", "low", "open"))
    previous_close = close.shift(1)
    true_range = pd.concat([high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    delta = close.diff()
    gain, loss = delta.clip(lower=0), (-delta.clip(upper=0))
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rsi = 100 - 100 / (1 + avg_gain / avg_loss.replace(0, np.nan))
    rsi = rsi.where(avg_loss != 0, 100.0).where(avg_gain != 0, 0.0)

    up_move, down_move = high.diff(), -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    ema9, ema21 = close.ewm(span=9, adjust=False).mean(), close.ewm(span=21, adjust=False).mean()
    bb_mid, bb_std = close.rolling(20).mean(), close.rolling(20).std()
    candle_range = (high - low).replace(0, np.nan)
    dt = pd.to_datetime(df["from_ts"], unit="s", utc=True)
    result = pd.DataFrame(index=df.index)
    result["atr_14"] = atr
    result["atr_pct"] = atr / close.abs() * 100
    result["rsi_14"] = rsi
    result["adx_14"], result["plus_di_14"], result["minus_di_14"] = adx, plus_di, minus_di
    result["bb_position"] = (close - bb_mid) / (2 * bb_std.replace(0, np.nan))
    result["bb_width_pct"] = (4 * bb_std / bb_mid.abs()) * 100
    result["trend_slope"] = (ema9 - ema21) / ema21.abs() * 100
    result["ema9_slope"] = ema9.pct_change() * 100
    result["ema21_slope"] = ema21.pct_change() * 100
    result["ema_gap_pct"] = (ema9 - ema21) / ema21.abs() * 100
    result["dist_ema9"] = (close - ema9) / ema9.abs() * 100
    result["dist_ema21"] = (close - ema21) / ema21.abs() * 100
    result["body_ratio"] = (close - open_).abs() / candle_range
    result["upper_wick_ratio"] = (high - pd.concat([open_, close], axis=1).max(axis=1)) / candle_range
    result["lower_wick_ratio"] = (pd.concat([open_, close], axis=1).min(axis=1) - low) / candle_range
    result["sequence_move_atr"] = (close - close.shift(3)) / atr
    result["v1_body_atr"] = (close.shift(2) - open_.shift(2)).abs() / atr
    result["v2_body_atr"] = (close.shift(1) - open_.shift(1)).abs() / atr
    result["v3_body_atr"] = (close - open_).abs() / atr
    result["direction_up"] = [1.0 if value == "UP" else 0.0 for value in directions] if directions is not None else np.nan
    result["hour_sin"] = np.sin(2 * np.pi * dt.dt.hour / 24)
    result["hour_cos"] = np.cos(2 * np.pi * dt.dt.hour / 24)
    # Valores neutros para indicadores matematicamente indefinidos em mercado
    # totalmente plano; o mesmo cálculo é usado no dataset e em produção.
    return result[S01_FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0.0)


def s13_feature_frame(candles: pd.DataFrame, directions: Sequence[str] | None = None) -> pd.DataFrame:
    """Features da S13; candle atual representa V3 no snapshot de confirmação."""
    base = s01_feature_frame(candles, directions)
    df = candles.sort_values("from_ts").copy()
    close, high, low, open_ = (df[name].astype(float) for name in ("close", "high", "low", "open"))
    previous_close = close.shift(1)
    tr = pd.concat([high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    v1_open, v1_close, v1_high, v1_low = open_.shift(2), close.shift(2), high.shift(2), low.shift(2)
    v1_range = (v1_high - v1_low).replace(0, np.nan)
    direction_up = base["direction_up"]
    level = pd.Series(np.where(direction_up == 1.0, v1_low, v1_high), index=df.index)
    wick = pd.Series(np.where(direction_up == 1.0, v1_close - v1_low, v1_high - v1_close), index=df.index)
    result = pd.DataFrame(index=df.index)
    for name in ("atr_14", "atr_pct", "rsi_14", "adx_14", "plus_di_14", "minus_di_14", "bb_position", "bb_width_pct", "trend_slope", "dist_ema9", "dist_ema21", "body_ratio", "upper_wick_ratio", "lower_wick_ratio", "direction_up", "hour_sin", "hour_cos"):
        result[name] = base[name]
    result["v1_wick_ratio"] = wick / v1_range
    result["v1_body_atr"] = (v1_close - v1_open).abs() / atr
    result["v2_body_atr"] = (close.shift(1) - open_.shift(1)).abs() / atr
    result["v3_body_atr"] = (close - open_).abs() / atr
    result["level_distance_atr"] = (close - level).abs() / atr
    return result[S13_FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0.0)


def m5_feature_frame(candles: pd.DataFrame) -> pd.DataFrame:
    df = candles.sort_values("from_ts").copy()
    close, high, low = (df[name].astype(float) for name in ("close", "high", "low"))
    ema9, ema21 = close.ewm(span=9, adjust=False).mean(), close.ewm(span=21, adjust=False).mean()
    dt = pd.to_datetime(df["from_ts"], unit="s")
    scale = np.where(close < 100, 1e-4, 1e-2)
    result = pd.DataFrame(index=df.index)
    result["atr_14"] = (high - low).rolling(14).mean()
    result["std_14"] = close.rolling(14).std()
    result["trend_slope"] = (ema9 - ema21) / ema21 * 100
    result["hour_sin"] = np.sin(2 * np.pi * dt.dt.hour / 24)
    result["hour_cos"] = np.cos(2 * np.pi * dt.dt.hour / 24)
    result["dist_res_m15"] = (high.rolling(3).max() - close) / scale
    result["dist_sup_m15"] = (close - low.rolling(3).min()) / scale
    result["dist_res_h1"] = (high.rolling(12).max() - close) / scale
    result["dist_sup_h1"] = (close - low.rolling(12).min()) / scale
    return result[M5_FEATURES]


def latest_m1_features(candles: Sequence[Any]) -> dict[str, float] | None:
    if len(candles) < 60:
        return None
    row = m1_feature_frame(candles_to_frame(candles)).iloc[-1]
    return {name: float(row[name]) for name in M1_FEATURES if pd.notna(row[name])}


def latest_s01_features(candles: Sequence[Any], direction: str) -> dict[str, float] | None:
    if len(candles) < 60:
        return None
    frame = candles_to_frame(candles)
    directions = [direction] * len(frame)
    row = s01_feature_frame(frame, directions).iloc[-1]
    return {name: float(row[name]) for name in S01_FEATURES if pd.notna(row[name])}


def latest_s13_features(candles: Sequence[Any], direction: str) -> dict[str, float] | None:
    if len(candles) < 60:
        return None
    frame = candles_to_frame(candles)
    row = s13_feature_frame(frame, [direction] * len(frame)).iloc[-1]
    return {name: float(row[name]) for name in S13_FEATURES if pd.notna(row[name])}


def latest_m5_features(candles: Sequence[Any]) -> dict[str, float] | None:
    if len(candles) < 15:
        return None
    row = m5_feature_frame(candles_to_frame(candles)).iloc[-1]
    return {name: float(row[name]) for name in M5_FEATURES if pd.notna(row[name])}


def s5_m5_feature_row(m1_features: pd.Series, command: Any, touch: Any, direction: str) -> dict[str, float] | None:
    """Combina contexto M1 com o comando M5 e o candle que fez o toque."""
    if m1_features.isna().any():
        return None
    value = lambda name: float(touch[name]) if isinstance(touch, dict) else float(getattr(touch, name))
    command_range = float(command.high) - float(command.low)
    touch_range = value("high") - value("low")
    result = {name: float(m1_features[name]) for name in M1_FEATURES}
    result.update({
        "command_age_m1": (int(value("from_ts")) - int(command.available_at)) / 60.0,
        "command_body_ratio": abs(float(command.close) - float(command.open)) / (command_range + 1e-9),
        "command_range_pct": command_range / (abs(float(command.open)) + 1e-9) * 100.0,
        "touch_close_level_ratio": (value("close") - float(command.level)) / (touch_range + 1e-9),
        "touch_body_ratio": abs(value("close") - value("open")) / (touch_range + 1e-9),
        "direction_up": 1.0 if direction == "UP" else 0.0,
    })
    return result


def latest_s5_m5_features(candles: Sequence[Any], command: Any, touch: Any, direction: str) -> dict[str, float] | None:
    if len(candles) < 60:
        return None
    frame = candles_to_frame(candles)
    features = m1_feature_frame(frame)
    return s5_m5_feature_row(features.iloc[-1], command, touch, direction)
