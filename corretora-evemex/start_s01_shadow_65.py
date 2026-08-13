"""Inicia uma nova campanha sombra S01 com limiar calibrado de 65%."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import joblib

from retrain_models import BASE, _archive

THRESHOLD = 0.65


def start_campaign() -> str:
    policy_path = BASE / "trading_policy.json"
    model_path = BASE / "signal_filter_s01.pkl"
    if not policy_path.exists() or not model_path.exists():
        raise RuntimeError("Artefatos S01 ausentes; execute retrain_s01_selective.py primeiro")

    _archive(policy_path)
    _archive(model_path)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    campaign = datetime.now().astimezone().strftime("s01-65-%Y%m%d-%H%M%S")
    config = policy.setdefault("strategies", {}).setdefault("s01", {})
    config.update({
        "active": False,
        "mode": "shadow",
        "threshold": THRESHOLD,
        "shadow_campaign": campaign,
        "shadow_required_signals": 100,
        "shadow_min_winrate": 0.60,
        "shadow_signals": 0,
        "shadow_winrate": None,
    })
    policy["generated_at"] = datetime.now().astimezone().isoformat()
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")

    artifact = joblib.load(model_path)
    artifact["threshold"] = THRESHOLD
    joblib.dump(artifact, model_path)
    return campaign


if __name__ == "__main__":
    print(f"Nova campanha S01 a 65%: {start_campaign()}")
