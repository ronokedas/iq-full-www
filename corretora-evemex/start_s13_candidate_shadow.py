"""Inicia a comparação ao vivo da candidata S13 sem interromper a S13 atual."""

from __future__ import annotations

import json
from datetime import datetime

from retrain_models import BASE, _archive

THRESHOLD = 0.65


def start_campaign() -> str:
    policy_path = BASE / "trading_policy.json"
    candidate_path = BASE / "signal_filter_s13_candidate.pkl"
    if not candidate_path.exists():
        raise RuntimeError("Modelo candidato ausente; execute retrain_s13_candidate.py")
    _archive(policy_path)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    current = policy.get("strategies", {}).get("s13", {})
    campaign = datetime.now().astimezone().strftime("s13-candidate-%Y%m%d-%H%M%S")
    policy.setdefault("candidates", {})["s13"] = {
        "mode": "shadow", "active": False, "shadow_campaign": campaign,
        "shadow_required_signals": 100, "threshold": THRESHOLD,
        "baseline_winrate": float(current.get("oos_winrate_65", 0.7091761946643214)),
        "baseline_threshold": float(current.get("threshold", .65)),
        "shadow_signals": 0, "shadow_winrate": None,
    }
    policy["generated_at"] = datetime.now().astimezone().isoformat()
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
    # O modelo candidato já é calibrado; alteramos apenas o corte operacional
    # desta campanha, sem retreinar nem tocar no modelo S13 em produção.
    import joblib
    _archive(candidate_path)
    artifact = joblib.load(candidate_path)
    artifact["threshold"] = THRESHOLD
    joblib.dump(artifact, candidate_path)
    return campaign


if __name__ == "__main__":
    print(f"Campanha candidata S13 iniciada: {start_campaign()}")
