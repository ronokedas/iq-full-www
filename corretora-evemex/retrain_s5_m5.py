"""Gera e publica somente o dataset, modelo e política da S5-M5."""

from __future__ import annotations

import json
from datetime import datetime

from retrain_models import BASE, _archive, generate_dataset, train_model


def main() -> None:
    dataset = generate_dataset("s5_m5")
    result = train_model("s5_m5", dataset)
    policy_path = BASE / "trading_policy.json"
    _archive(policy_path)
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {"strategies": {}}
    policy["generated_at"] = datetime.now().astimezone().isoformat()
    policy.setdefault("strategies", {})["s5_m5"] = result
    policy_path.write_text(json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8")

    report = BASE / "S5_M5_TRAINING_REPORT.md"
    folds = "\n".join(
        f"- Fold {fold['fold']}: base {fold['base_winrate']:.2%}; ≥65% {fold['signals_65']} sinais / "
        f"{fold['winrate_65'] if fold['winrate_65'] is not None else 'sem sinais'}."
        for fold in result["folds"]
    )
    report.write_text(
        f"# Re-treino isolado S5-M5\n\nAmostras: {result['samples']}\n\n"
        f"Ativa: {'sim' if result['active'] else 'não'}\n\n"
        f"Acerto walk-forward ≥65%: {result['oos_winrate_65']:.2%} em {result['oos_signals_65']} sinais.\n\n{folds}\n",
        encoding="utf-8",
    )
    print(f"S5-M5 publicada. Relatório: {report}")


if __name__ == "__main__":
    main()
