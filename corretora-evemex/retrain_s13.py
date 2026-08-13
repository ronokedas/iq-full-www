"""Regera e publica somente S13, preservando S01/S16 e seus artefatos."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from retrain_models import BASE, _archive, generate_dataset, train_model


def main() -> None:
    dataset = generate_dataset("s13")
    result = train_model("s13", dataset)
    policy_path = BASE / "trading_policy.json"
    _archive(policy_path)
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {"strategies": {}}
    policy["generated_at"] = datetime.now().astimezone().isoformat()
    policy["strategies"]["s13"] = result
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")
    report = BASE / "S13_TRAINING_REPORT.md"
    folds = "\n".join(
        f"- Fold {fold['fold']}: base {fold['base_winrate']:.2%}; ≥65% {fold['signals_65']} sinais / {fold['winrate_65'] if fold['winrate_65'] is not None else 'sem sinais'}."
        for fold in result["folds"]
    )
    report.write_text(
        f"# Re-treino isolado S13\n\nAmostras: {result['samples']}\n\nAtiva: {'sim' if result['active'] else 'não'}\n\nAcerto walk-forward ≥65%: {result['oos_winrate_65']:.2%} em {result['oos_signals_65']} sinais.\n\n{folds}\n",
        encoding="utf-8",
    )
    print(f"S13 publicado. Relatório: {report}")


if __name__ == "__main__":
    main()
