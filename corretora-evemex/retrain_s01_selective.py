"""Re-treina exclusivamente a S01 com indicadores reais e política de sombra."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import pandas as pd

from feature_builders import S01_FEATURES, s01_feature_frame
from retrain_models import (
    BASE, DATA_DIR, MIN_ACCEPTED_WINRATE, MIN_HOUR_SAMPLES, _archive,
    _fit_calibrated, _target, validate_source_data,
)
from strategy_rules import detect_s01

THRESHOLDS = (0.65, 0.70, 0.75)
MIN_FOLD_SIGNALS = 100
BRASILIA = ZoneInfo("America/Sao_Paulo")


def generate_s01_dataset() -> Path:
    samples: list[dict] = []
    for path in sorted(DATA_DIR.glob("*.parquet")):
        frame = pd.read_parquet(path).sort_values("from_ts").drop_duplicates("from_ts").reset_index(drop=True)
        records = frame.to_dict("records")
        directions = ["UP"] * len(frame)
        computed = s01_feature_frame(frame, directions)
        for index in range(3, len(records) - 1):
            direction = detect_s01(records[index - 3:index + 1])
            if not direction:
                continue
            features = computed.iloc[index].copy()
            features["direction_up"] = 1.0 if direction == "UP" else 0.0
            if features.isna().any():
                continue
            row = {name: float(features[name]) for name in S01_FEATURES}
            row.update(symbol=path.stem, from_ts=int(records[index]["from_ts"]), timeframe="1m", direction=direction,
                       target=_target(records[index + 1], direction))
            samples.append(row)
    if not samples:
        raise RuntimeError("Nenhum sinal S01 encontrado")
    output = BASE / "ml_dataset_s01.csv"
    pd.DataFrame(samples).sort_values(["from_ts", "symbol"]).to_csv(output, index=False)
    return output


def walk_forward(dataset: pd.DataFrame, features: list[str] = S01_FEATURES) -> tuple[pd.DataFrame, list[dict]]:
    records, folds = [], []
    n = len(dataset)
    for fold, (train_part, test_part) in enumerate(((2, 3), (3, 4), (4, 5)), 1):
        train_end, test_end = n * train_part // 5, n * test_part // 5
        train, test = dataset.iloc[:train_end], dataset.iloc[train_end:test_end].copy()
        calibration_start = int(len(train) * .8)
        model = _fit_calibrated(train.iloc[:calibration_start], train.iloc[calibration_start:], features)
        test["probability"] = model.predict_proba(test[features])[:, 1]
        test["fold"] = fold
        records.append(test)
        folds.append({"fold": fold, "test_samples": len(test), "base_winrate": float(test.target.mean())})
    return pd.concat(records, ignore_index=True), folds


def choose_policy(predictions: pd.DataFrame, folds: list[dict]) -> dict:
    candidates: list[dict] = []
    for threshold in THRESHOLDS:
        selected = predictions.loc[predictions.probability >= threshold]
        fold_metrics = []
        for fold in folds:
            subset = selected.loc[selected.fold == fold["fold"], "target"]
            fold_metrics.append({**fold, "signals": len(subset), "winrate": float(subset.mean()) if len(subset) else None})
        overall = float(selected.target.mean()) if len(selected) else 0.0
        qualifies = bool(len(selected)) and overall >= MIN_ACCEPTED_WINRATE and all(
            item["signals"] >= MIN_FOLD_SIGNALS and item["winrate"] is not None and item["winrate"] >= MIN_ACCEPTED_WINRATE
            for item in fold_metrics
        )
        candidates.append({"threshold": threshold, "signals": len(selected), "winrate": overall, "folds": fold_metrics, "qualifies": qualifies})
    approved = [candidate for candidate in candidates if candidate["qualifies"]]
    selected_candidate = max(approved, key=lambda candidate: (candidate["winrate"], candidate["threshold"])) if approved else None
    threshold = selected_candidate["threshold"] if selected_candidate else max(THRESHOLDS)
    selected = predictions.loc[predictions.probability >= threshold].copy()
    selected["hour_brasilia"] = pd.to_datetime(selected.from_ts, unit="s", utc=True).dt.tz_convert(BRASILIA).dt.hour
    hours = selected.groupby("hour_brasilia").target.agg(["count", "mean"])
    allowed_hours = sorted(int(hour) for hour, row in hours.iterrows() if row["count"] >= MIN_HOUR_SAMPLES and row["mean"] >= MIN_ACCEPTED_WINRATE)
    return {
        "strategy": "S01", "active": False, "mode": "shadow" if selected_candidate else "disabled",
        "shadow_campaign": datetime.now().astimezone().strftime("s01-%Y%m%d-%H%M%S"),
        "shadow_required_signals": 100, "shadow_min_winrate": MIN_ACCEPTED_WINRATE,
        "threshold": threshold, "min_accepted_winrate": MIN_ACCEPTED_WINRATE,
        "min_fold_signals": MIN_FOLD_SIGNALS, "allowed_hours_brasilia": allowed_hours,
        "hour_min_samples": MIN_HOUR_SAMPLES, "oos_signals": len(selected),
        "oos_winrate": float(selected.target.mean()) if len(selected) else 0.0,
        "folds": selected_candidate["folds"] if selected_candidate else [], "threshold_candidates": candidates,
    }


def publish(dataset_path: Path) -> dict:
    dataset = pd.read_csv(dataset_path).dropna(subset=S01_FEATURES).sort_values(["from_ts", "symbol"]).reset_index(drop=True)
    predictions, folds = walk_forward(dataset)
    policy = choose_policy(predictions, folds)
    calibration_start = int(len(dataset) * .8)
    model = _fit_calibrated(dataset.iloc[:calibration_start], dataset.iloc[calibration_start:], S01_FEATURES)
    model_path = BASE / "signal_filter_s01.pkl"
    _archive(model_path)
    joblib.dump({"model": model, "features": S01_FEATURES, "threshold": policy["threshold"], "calibrated": True}, model_path)
    policy_path = BASE / "trading_policy.json"
    _archive(policy_path)
    current = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {"strategies": {}}
    current["generated_at"] = datetime.now().astimezone().isoformat()
    current["timezone"] = "America/Sao_Paulo"
    current.setdefault("strategies", {})["s01"] = policy
    policy_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    report = BASE / "S01_SELECTIVE_TRAINING_REPORT.md"
    lines = ["# Treino seletivo S01", "", f"Amostras: {len(dataset)}", f"", f"Modo publicado: {policy['mode']}", f"Limiar selecionado: {policy['threshold']:.0%}", f"Sinais OOS: {policy['oos_signals']}", f"Acerto OOS: {policy['oos_winrate']:.2%}", "", "| Limiar | Sinais | Acerto | Aprovado |", "|---:|---:|---:|---|"]
    lines += [f"| {item['threshold']:.0%} | {item['signals']} | {item['winrate']:.2%} | {'sim' if item['qualifies'] else 'não'} |" for item in policy["threshold_candidates"]]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return policy


def main() -> None:
    checks = validate_source_data()
    dataset = generate_s01_dataset()
    policy = publish(dataset)
    print(f"S01 publicada em modo {policy['mode']}; {len(checks)} fontes verificadas.")


if __name__ == "__main__":
    main()
