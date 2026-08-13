# Relatório de treino calibrado

Três testes walk-forward; cada probabilidade foi calibrada por sigmoid em dados temporais anteriores.

| Estratégia | Amostras | Sinais ≥65% | Acerto ≥65% | Ativa | Horas Brasília liberadas |
|---|---:|---:|---:|---|---|
| S01 | 94020 | 46977 | 77.47% | sim | 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23 |
  - Fold 1: base 72.82%; ≥60% 16972 / 0.7479377798727316; ≥65% 15729 / 0.7615233009091487.
  - Fold 2: base 76.60%; ≥60% 17341 / 0.7778098148895681; ≥65% 15486 / 0.790843342373757.
  - Fold 3: base 75.63%; ≥60% 16911 / 0.7667198864644315; ≥65% 15762 / 0.7719832508564903.
| S13 | 5812 | 2320 | 71.55% | sim | 0, 2, 3, 8, 9, 10, 11, 13, 16, 18 |
  - Fold 1: base 69.91%; ≥60% 767 / 0.7431551499348109; ≥65% 434 / 0.8087557603686636.
  - Fold 2: base 69.88%; ≥60% 1143 / 0.7016622922134733; ≥65% 1084 / 0.705719557195572.
  - Fold 3: base 66.98%; ≥60% 977 / 0.6693961105424769; ≥65% 802 / 0.6783042394014963.
| S16 | 24971 | 25 | 64.00% | não | nenhuma |
  - Fold 1: base 51.98%; ≥60% 0 / sem sinais; ≥65% 0 / sem sinais.
  - Fold 2: base 52.90%; ≥60% 0 / sem sinais; ≥65% 0 / sem sinais.
  - Fold 3: base 69.09%; ≥60% 153 / 0.738562091503268; ≥65% 25 / 0.64.

Integridade da fonte: 43 ativos, 0 duplicatas e 282 gaps M1 identificados antes da geração.
