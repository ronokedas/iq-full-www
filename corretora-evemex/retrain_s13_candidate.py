"""Treina uma candidata S13 com indicadores reais, sem publicar sobre a S13 ativa."""

from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd

from feature_builders import S13_FEATURES, s13_feature_frame
from retrain_models import BASE, DATA_DIR, _archive, _fit_calibrated, _target
from retrain_s01_selective import choose_policy, walk_forward
from strategy_rules import detect_s13


def generate_dataset() -> Path:
    samples: list[dict] = []
    for path in sorted(DATA_DIR.glob("*.parquet")):
        frame = pd.read_parquet(path).sort_values("from_ts").drop_duplicates("from_ts").reset_index(drop=True)
        records = frame.to_dict("records")
        computed = s13_feature_frame(frame, ["UP"] * len(frame))
        for index in range(2, len(records) - 1):
            direction = detect_s13(records[index - 2:index + 1])
            if not direction:
                continue
            features = computed.iloc[index].copy()
            features["direction_up"] = 1.0 if direction == "UP" else 0.0
            if features.isna().any():
                continue
            row = {name: float(features[name]) for name in S13_FEATURES}
            row.update(symbol=path.stem, from_ts=int(records[index]["from_ts"]), timeframe="1m", direction=direction,
                       target=_target(records[index + 1], direction))
            samples.append(row)
    output = BASE / "ml_dataset_s13_candidate.csv"
    pd.DataFrame(samples).sort_values(["from_ts", "symbol"]).to_csv(output, index=False)
    return output


def publish_candidate(dataset_path: Path) -> dict:
    dataset = pd.read_csv(dataset_path).dropna(subset=S13_FEATURES).sort_values(["from_ts", "symbol"]).reset_index(drop=True)
    predictions, folds = walk_forward(dataset, S13_FEATURES)
    policy = choose_policy(predictions, folds)
    calibration_start = int(len(dataset) * .8)
    model = _fit_calibrated(dataset.iloc[:calibration_start], dataset.iloc[calibration_start:], S13_FEATURES)
    path = BASE / "signal_filter_s13_candidate.pkl"
    _archive(path)
    joblib.dump({"model": model, "features": S13_FEATURES, "threshold": policy["threshold"], "calibrated": True}, path)
    report = BASE / "S13_CANDIDATE_TRAINING_REPORT.md"
    lines = ["# Candidata seletiva S13", "", f"Amostras: {len(dataset)}", f"Limiar: {policy['threshold']:.0%}", f"Sinais OOS: {policy['oos_signals']}", f"Acerto OOS: {policy['oos_winrate']:.2%}", f"Elegível para sombra: {'sim' if policy['mode'] == 'shadow' else 'não'}", "", "| Limiar | Sinais | Acerto | Aprovado |", "|---:|---:|---:|---|"]
    lines += [f"| {row['threshold']:.0%} | {row['signals']} | {row['winrate']:.2%} | {'sim' if row['qualifies'] else 'não'} |" for row in policy["threshold_candidates"]]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return policy


if __name__ == "__main__":
    result = publish_candidate(generate_dataset())
    print(f"Candidata S13 pronta: limiar {result['threshold']:.0%}; modo {result['mode']}.")
