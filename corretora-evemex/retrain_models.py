"""Treino walk-forward com calibração sigmoid e política operacional."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from calibrated_model import SigmoidCalibratedModel
from feature_builders import M1_FEATURES, M5_FEATURES, S5_M5_FEATURES, m1_feature_frame, m5_feature_frame, s5_m5_feature_row
from s5_m5_rules import M1_SECONDS, iter_s5_m5_events
from strategy_rules import detect_s01, detect_s13, detect_s16

BASE = Path(__file__).parent
DATA_DIR = BASE / "dados" / "m1"
ENTRY_THRESHOLD = 0.65
MIN_ACCEPTED_WINRATE = 0.60
MIN_HOUR_SAMPLES = 100
BRASILIA = ZoneInfo("America/Sao_Paulo")


def _target(next_candle: dict, direction: str) -> int:
    return int(float(next_candle["close"]) > float(next_candle["open"])) if direction == "UP" else int(float(next_candle["close"]) < float(next_candle["open"]))


def _aggregate_m5(m1: pd.DataFrame) -> pd.DataFrame:
    frame = m1.sort_values("from_ts").copy()
    frame["bucket"] = (frame["from_ts"] // 300) * 300
    m5 = frame.groupby("bucket", sort=True).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), candles=("from_ts", "count")).reset_index()
    return m5.loc[m5.candles == 5].drop(columns="candles").rename(columns={"bucket": "from_ts"}).reset_index(drop=True)


def validate_source_data() -> dict[str, dict[str, int]]:
    """Mede duplicatas e intervalos faltantes sem alterar os arquivos locais."""
    report: dict[str, dict[str, int]] = {}
    for path in sorted(DATA_DIR.glob("*.parquet")):
        frame = pd.read_parquet(path, columns=["from_ts"]).sort_values("from_ts")
        report[path.stem] = {"rows": len(frame), "duplicates": int(frame.from_ts.duplicated().sum()), "gaps": int((frame.from_ts.diff().dropna() != 60).sum())}
    if not report:
        raise RuntimeError("Nenhum parquet M1 foi encontrado")
    return report


def _append_sample(samples: list[dict], features: pd.Series, symbol: str, ts: int, timeframe: str, direction: str, target: int) -> None:
    if features.isna().any():
        return
    row = {name: float(features[name]) for name in features.index}
    row.update(symbol=symbol, from_ts=int(ts), timeframe=timeframe, direction=direction, target=target)
    samples.append(row)


def _m1_samples(frame: pd.DataFrame, symbol: str, strategy: str) -> list[dict]:
    computed, records, samples = m1_feature_frame(frame), frame.to_dict("records"), []
    detector, first = (detect_s01, 3) if strategy == "s01" else (detect_s13, 2)
    for index in range(first, len(records) - 1):
        window = records[index - 3:index + 1] if strategy == "s01" else records[index - 2:index + 1]
        direction = detector(window)
        if direction:
            _append_sample(samples, computed.iloc[index], symbol, records[index]["from_ts"], "1m", direction, _target(records[index + 1], direction))
    return samples


def _s16_samples(frame: pd.DataFrame, symbol: str) -> list[dict]:
    m5, samples, levels = _aggregate_m5(frame), [], []
    computed, records = m5_feature_frame(m5), m5.to_dict("records")
    for index in range(2, len(records) - 1):
        window, direction = records[index - 2:index + 1], detect_s16(records[index - 2:index + 1])
        level, region = float(window[0]["close"]), (1e-4 if float(window[0]["close"]) < 100 else 1e-2) * 2
        if not direction or any(abs(level - used) <= region for used in levels):
            continue
        levels.append(level)
        _append_sample(samples, computed.iloc[index], symbol, records[index]["from_ts"], "5m", direction, _target(records[index + 1], direction))
    return samples


def _s5_m5_samples(frame: pd.DataFrame, symbol: str) -> list[dict]:
    """Rotula a vela M1 imediatamente posterior ao toque confirmado."""
    frame = frame.sort_values("from_ts").drop_duplicates("from_ts").reset_index(drop=True)
    m1_features, records, samples = m1_feature_frame(frame), frame.to_dict("records"), []
    index_by_ts = {int(row["from_ts"]): index for index, row in enumerate(records)}
    for command, touch, direction in iter_s5_m5_events(frame):
        index = index_by_ts[int(touch["from_ts"])]
        if index + 1 >= len(records) or int(records[index + 1]["from_ts"]) != int(touch["from_ts"]) + M1_SECONDS:
            continue
        features = s5_m5_feature_row(m1_features.iloc[index], command, touch, direction)
        if features is None:
            continue
        row = dict(features)
        row.update(symbol=symbol, from_ts=int(touch["from_ts"]), timeframe="1m", direction=direction,
                   target=_target(records[index + 1], direction))
        samples.append(row)
    return samples


def generate_dataset(strategy: str) -> Path:
    if strategy not in {"s01", "s13", "s16", "s5_m5"}:
        raise ValueError(strategy)
    samples: list[dict] = []
    for path in sorted(DATA_DIR.glob("*.parquet")):
        frame = pd.read_parquet(path).sort_values("from_ts").drop_duplicates("from_ts").reset_index(drop=True)
        if strategy == "s16":
            samples.extend(_s16_samples(frame, path.stem))
        elif strategy == "s5_m5":
            samples.extend(_s5_m5_samples(frame, path.stem))
        else:
            samples.extend(_m1_samples(frame, path.stem, strategy))
    if not samples:
        raise RuntimeError(f"Nenhum sinal {strategy.upper()} encontrado")
    output = BASE / f"ml_dataset_{strategy}.csv"
    pd.DataFrame(samples).sort_values(["from_ts", "symbol"]).to_csv(output, index=False)
    return output


def _new_model() -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(n_estimators=300, learning_rate=0.02, num_leaves=31, max_depth=6, min_child_samples=15, subsample=0.8, colsample_bytree=0.8, random_state=42, verbose=-1)


def _fit_calibrated(base_train: pd.DataFrame, calibration: pd.DataFrame, features: list[str]) -> SigmoidCalibratedModel:
    model = _new_model()
    model.fit(base_train[features], base_train.target)
    raw = model.predict_proba(calibration[features])[:, 1].reshape(-1, 1)
    calibrator = LogisticRegression(random_state=42).fit(raw, calibration.target)
    return SigmoidCalibratedModel(model, calibrator)


def walk_forward_predictions(dataset: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Três testes futuros; cada teste tem treino e calibração inteiramente anteriores."""
    n, records, summaries = len(dataset), [], []
    for fold, (train_end, test_end) in enumerate(((2, 3), (3, 4), (4, 5)), start=1):
        train_end, test_end = n * train_end // 5, n * test_end // 5
        train_block, test = dataset.iloc[:train_end], dataset.iloc[train_end:test_end].copy()
        calibration_start = int(len(train_block) * 0.8)
        model = _fit_calibrated(train_block.iloc[:calibration_start], train_block.iloc[calibration_start:], features)
        test["probability"] = model.predict_proba(test[features])[:, 1]
        test["fold"] = fold
        records.append(test)
        at_65 = test.loc[test.probability >= ENTRY_THRESHOLD, "target"]
        at_60 = test.loc[test.probability >= MIN_ACCEPTED_WINRATE, "target"]
        summaries.append({"fold": fold, "test_samples": len(test), "base_winrate": float(test.target.mean()), "signals_60": len(at_60), "winrate_60": float(at_60.mean()) if len(at_60) else None, "signals_65": len(at_65), "winrate_65": float(at_65.mean()) if len(at_65) else None})
    return pd.concat(records, ignore_index=True), summaries


def _archive(path: Path) -> None:
    if not path.exists():
        return
    archive = BASE / "models_archive"
    archive.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(path, archive / f"{path.stem}-{stamp}{path.suffix}")


def build_policy(strategy: str, predictions: pd.DataFrame, folds: list[dict[str, object]]) -> dict[str, object]:
    selected = predictions.loc[predictions.probability >= ENTRY_THRESHOLD].copy()
    selected["hour_brasilia"] = pd.to_datetime(selected.from_ts, unit="s", utc=True).dt.tz_convert(BRASILIA).dt.hour
    by_hour = selected.groupby("hour_brasilia").target.agg(["count", "mean"])
    allowed = sorted(int(hour) for hour, row in by_hour.iterrows() if row["count"] >= MIN_HOUR_SAMPLES and row["mean"] >= MIN_ACCEPTED_WINRATE)
    overall = float(selected.target.mean()) if len(selected) else 0.0
    fold_approved = all(fold["winrate_65"] is not None and fold["winrate_65"] >= MIN_ACCEPTED_WINRATE for fold in folds)
    return {"active": bool(len(selected) and overall >= MIN_ACCEPTED_WINRATE and fold_approved), "threshold": ENTRY_THRESHOLD, "min_accepted_winrate": MIN_ACCEPTED_WINRATE, "allowed_hours_brasilia": allowed, "hour_min_samples": MIN_HOUR_SAMPLES, "oos_signals_65": len(selected), "oos_winrate_65": overall, "folds": folds}


def train_model(strategy: str, dataset_path: Path) -> dict[str, object]:
    features = M5_FEATURES if strategy == "s16" else (S5_M5_FEATURES if strategy == "s5_m5" else M1_FEATURES)
    dataset = pd.read_csv(dataset_path).dropna(subset=features).sort_values(["from_ts", "symbol"]).reset_index(drop=True)
    predictions, folds = walk_forward_predictions(dataset, features)
    policy = build_policy(strategy, predictions, folds)
    calibration_start = int(len(dataset) * 0.8)
    deployed = _fit_calibrated(dataset.iloc[:calibration_start], dataset.iloc[calibration_start:], features)
    model_path = BASE / f"signal_filter_{strategy}.pkl"
    _archive(model_path)
    joblib.dump({"model": deployed, "features": features, "threshold": ENTRY_THRESHOLD, "calibrated": True}, model_path)
    return {"strategy": strategy.upper(), "samples": len(dataset), **policy}


def write_report(results: list[dict[str, object]], source_checks: dict[str, dict[str, int]]) -> Path:
    report = BASE / "TRAINING_REPORT.md"
    lines = ["# Relatório de treino calibrado", "", "Três testes walk-forward; cada probabilidade foi calibrada por sigmoid em dados temporais anteriores.", "", "| Estratégia | Amostras | Sinais ≥65% | Acerto ≥65% | Ativa | Horas Brasília liberadas |", "|---|---:|---:|---:|---|---|"]
    for result in results:
        hours = ", ".join(map(str, result["allowed_hours_brasilia"])) or "nenhuma"
        lines.append(f"| {result['strategy']} | {result['samples']} | {result['oos_signals_65']} | {result['oos_winrate_65']:.2%} | {'sim' if result['active'] else 'não'} | {hours} |")
        for fold in result["folds"]:
            lines.append(f"  - Fold {fold['fold']}: base {fold['base_winrate']:.2%}; ≥60% {fold['signals_60']} / {fold['winrate_60'] if fold['winrate_60'] is not None else 'sem sinais'}; ≥65% {fold['signals_65']} / {fold['winrate_65'] if fold['winrate_65'] is not None else 'sem sinais'}.")
    total_gaps, total_duplicates = sum(item["gaps"] for item in source_checks.values()), sum(item["duplicates"] for item in source_checks.values())
    lines.extend(["", f"Integridade da fonte: {len(source_checks)} ativos, {total_duplicates} duplicatas e {total_gaps} gaps M1 identificados antes da geração."])
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    source_checks = validate_source_data()
    datasets = {name: generate_dataset(name) for name in ("s01", "s13", "s16")}
    results = [train_model(name, datasets[name]) for name in ("s01", "s13", "s16")]
    policy_path = BASE / "trading_policy.json"
    _archive(policy_path)
    policy_path.write_text(json.dumps({"generated_at": datetime.now().astimezone().isoformat(), "timezone": "America/Sao_Paulo", "strategies": {result["strategy"].lower(): result for result in results}}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório salvo em {write_report(results, source_checks)}")


if __name__ == "__main__":
    main()
