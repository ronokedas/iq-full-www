"""Treino experimental isolado da S5-M15; não publica artefatos no robô."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from core import M1_SECONDS, aggregate_complete_m15, backtest_asset

BASE = Path(__file__).resolve().parents[2]
DATA_DIR = BASE / "dados" / "m1"
OUTPUT_DIR = Path(__file__).resolve().parent / "results"
THRESHOLD = 0.65
BRASILIA = ZoneInfo("America/Sao_Paulo")
FEATURES = [
    "atr_14", "std_14", "trend_slope", "hour_sin", "hour_cos", "body_ratio", "avg_body_5",
    "dist_ema9", "dist_ema21", "command_age_m1", "command_body_ratio", "command_range_pct",
    "touch_close_level_ratio", "direction_up",
]


def _m1_features(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.sort_values("from_ts").drop_duplicates("from_ts").reset_index(drop=True).copy()
    close, high, low, open_ = (df[name].astype(float) for name in ("close", "high", "low", "open"))
    ema9, ema21 = close.ewm(span=9, adjust=False).mean(), close.ewm(span=21, adjust=False).mean()
    hour = pd.to_datetime(df.from_ts, unit="s", utc=True).dt.tz_convert(BRASILIA).dt.hour
    result = pd.DataFrame(index=df.index)
    result["atr_14"] = (high - low).rolling(14).mean()
    result["std_14"] = close.rolling(14).std()
    result["trend_slope"] = (ema9 - ema21) / ema21 * 100
    result["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    result["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    result["body_ratio"] = abs(close - open_) / (high - low + 1e-9)
    result["avg_body_5"] = abs(close - open_).rolling(5).mean()
    result["dist_ema9"] = (close - ema9) / ema9 * 100
    result["dist_ema21"] = (close - ema21) / ema21 * 100
    return result


def generate_dataset() -> pd.DataFrame:
    samples: list[dict] = []
    for path in sorted(DATA_DIR.glob("*.parquet")):
        frame = pd.read_parquet(path).sort_values("from_ts").drop_duplicates("from_ts").reset_index(drop=True)
        trades, _ = backtest_asset(frame, path.stem)
        features = _m1_features(frame)
        rows = frame.set_index("from_ts")
        m15 = aggregate_complete_m15(frame).set_index("from_ts")
        index_by_ts = {int(ts): index for index, ts in enumerate(frame.from_ts)}
        for trade in trades:
            index = index_by_ts[trade["touch_from_ts"]]
            row, command = rows.loc[trade["touch_from_ts"]], m15.loc[trade["command_from_ts"]]
            feature = features.iloc[index]
            if feature.isna().any():
                continue
            command_range = float(command.high) - float(command.low)
            touch_range = float(row.high) - float(row.low)
            sample = {name: float(feature[name]) for name in feature.index}
            sample.update({
                "command_age_m1": (trade["touch_from_ts"] - (trade["command_from_ts"] + 15 * M1_SECONDS)) / M1_SECONDS,
                "command_body_ratio": abs(float(command.close) - float(command.open)) / (command_range + 1e-9),
                "command_range_pct": command_range / (abs(float(command.open)) + 1e-9) * 100,
                "touch_close_level_ratio": (float(row.close) - trade["level"]) / (touch_range + 1e-9),
                "direction_up": 1.0 if trade["direction"] == "UP" else 0.0,
                "symbol": path.stem, "from_ts": trade["touch_from_ts"], "target": trade["target"],
            })
            samples.append(sample)
    dataset = pd.DataFrame(samples).sort_values(["from_ts", "symbol"]).reset_index(drop=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(OUTPUT_DIR / "ml_dataset_s5_m15.csv", index=False)
    return dataset


def _model() -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(n_estimators=200, learning_rate=0.03, num_leaves=15, max_depth=5, min_child_samples=8, random_state=42, verbose=-1)


def _fit(train: pd.DataFrame, calibration: pd.DataFrame):
    model = _model().fit(train[FEATURES], train.target)
    raw = model.predict_proba(calibration[FEATURES])[:, 1].reshape(-1, 1)
    if calibration.target.nunique() < 2:
        return model, None
    return model, LogisticRegression(random_state=42).fit(raw, calibration.target)


def _predict(model, calibrator, values: pd.DataFrame) -> np.ndarray:
    raw = model.predict_proba(values[FEATURES])[:, 1]
    return calibrator.predict_proba(raw.reshape(-1, 1))[:, 1] if calibrator is not None else raw


def run() -> Path:
    dataset = generate_dataset()
    folds, predictions = [], []
    n = len(dataset)
    for fold, (train_part, test_part) in enumerate(((2, 3), (3, 4), (4, 5)), 1):
        train_end, test_end = n * train_part // 5, n * test_part // 5
        train, test = dataset.iloc[:train_end], dataset.iloc[train_end:test_end].copy()
        split = int(len(train) * .8)
        model, calibrator = _fit(train.iloc[:split], train.iloc[split:])
        test["probability"] = _predict(model, calibrator, test)
        selected = test.loc[test.probability >= THRESHOLD]
        folds.append({"fold": fold, "total": len(test), "base": float(test.target.mean()), "signals": len(selected), "winrate": float(selected.target.mean()) if len(selected) else None})
        predictions.append(test)
    prediction = pd.concat(predictions, ignore_index=True)
    selected = prediction.loc[prediction.probability >= THRESHOLD]
    overall = float(selected.target.mean()) if len(selected) else 0.0
    active = bool(len(selected) and overall >= .60 and all(fold["winrate"] is not None and fold["winrate"] >= .60 for fold in folds))
    split = int(n * .8)
    model, calibrator = _fit(dataset.iloc[:split], dataset.iloc[split:])
    joblib.dump({"model": model, "calibrator": calibrator, "features": FEATURES, "threshold": THRESHOLD}, OUTPUT_DIR / "signal_filter_s5_m15_lab.pkl")
    lines = ["# Treino experimental — S5-M15", "", f"Amostras: {n}", f"", f"Limiar: {THRESHOLD:.0%}", f"", f"Apta para integração: {'sim' if active else 'não'}", f"", f"Acerto walk-forward ≥65%: {overall:.2%} em {len(selected)} sinais.", ""]
    lines.extend(f"- Fold {fold['fold']}: base {fold['base']:.2%}; ≥65% {fold['signals']} sinais / {fold['winrate'] if fold['winrate'] is not None else 'sem sinais'}." for fold in folds)
    report = OUTPUT_DIR / "TRAINING_REPORT.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    print(f"Relatório salvo em {run()}")
