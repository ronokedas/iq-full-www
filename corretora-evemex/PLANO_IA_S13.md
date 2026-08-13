# Plano de Integração IA - Estratégia S13 (Evemex)

Este documento detalha a implementação da filtragem por Inteligência Artificial na corretora Evemex, focando na estratégia **S13 - Pavios de Rejeição**.

## 1. Estratégia S13: Pavios de Rejeição (M1)

### Lógica de Detecção
A estratégia busca identificar exaustão de movimento através de pavios longos em 3 velas consecutivas da mesma cor.

- **Configuração CALL**:
  1. Três velas consecutivas **Vermelhas** (Baixa).
  2. Cada uma das 3 velas deve ter um **pavio inferior** >= 40% do tamanho total da vela (high - low).
  3. Entrada para a próxima vela (M1) como **CALL**.

- **Configuração PUT**:
  1. Três velas consecutivas **Verdes** (Alta).
  2. Cada uma das 3 velas deve ter um **pavio superior** >= 40% do tamanho total da vela.
  3. Entrada para a próxima vela (M1) como **PUT**.

## 2. Pipeline Implementado

### Coleta de Dados
- Script: `download_history.py`
- Dados de 43 pares OTC em `corretora-evemex/dados/m1/*.parquet` (M1, últimos 15 dias).
- Schema: `from_ts`, `open`, `high`, `low`, `close`, `volume`.

### Feature Engineering (25 Features)
- Script: `ml_dataset_generator_s13.py`
- Para cada sinal S13, são extraídas 25 características:
  - **Pavio/Tendência**: Sinal da vela, corpo/pavio das 3 velas do padrão, body_size, upper/lower wick.
  - **Volatilidade**: ATR(14), ATR/ATR21, Desvio Padrão (20), Volatilidade (20).
  - **Momentum/Tendência**: Inclinação EMA9/EMA21, retornos, RSI(14), MACD, histograma MACD.
  - **Média Móvel**: Posição do preço em relação à EMA9 e EMA21 (distância percentual).
  - **Sazonalidade**: Hora (seno/cosseno), minuto (seno/cosseno).
  - **Suporte/Resistência**: Distância (pips) até res/sup de H1 e M15.
  - **Contexto de Tendência S13**: `s13_p1`, `s13_p2`, `s13_p3` (pavios normalizados das 3 velas).

### Rotulagem (Target)
- `Target = 1`: Vela seguinte fechou a favor da direção (WIN).
- `Target = 0`: Vela seguinte fechou contra ou DOJI (LOSS).

### Treinamento do Modelo
- Script: `ml_train_model_s13.py`
- Algoritmo: **LightGBM Classifier** (300 árvores, learning_rate 0.02, validação temporal).
- Dataset: **51.576 amostras** (50,7% WIN / 49,3% LOSS).
- Divisão: 80% treino / 20% teste **sem shuffle** (validação temporal — evita data leakage).
- Modelo salvo: `signal_filter_s13.pkl` (dict com `model` e `features`).

### Backtest com IA
- Script: `ml_backtest_s13.py`
- **Confirmação crítica de Data Leakage corrigido**: o treinamento agora usa `shuffle=False`.

## 3. Resultados do Backtest (Out-of-Sample, últimos 20% do dataset)

| Métrica | SEM IA (Base) | COM IA (Filtrado ≥ 55%) |
|---|---|---|
| Total de Operações | 10.315 | 1.595 |
| Vitórias (WIN) | 5.309 | 882 |
| Derrotas (LOSS) | 5.006 | 713 |
| **Taxa de Acerto** | **51,47%** | **55,30%** |
| **Resultado Financeiro** (R$10/entrada, 85%) | **-R$ 4.933,50** | **+R$ 367,00** |
| **Profit Factor** | **0,90** | **1,05** |
| Max Drawdown | N/A | R$ 296,00 |

### Conclusões
1. ✅ **Sem IA a estratégia S13 é perdedora** (PF 0,90 e prejuízo de R$ 4.933 no período).
2. ✅ **Com o filtro de IA o resultado fica positivo** (PF 1,05 e lucro de R$ 367, apenas no out-of-sample de ~3 dias).
3. ✅ O filtro reduz as operações de 10.315 para 1.595, focando nos sinais de maior confiança.
4. ⚠️ O win rate de 55,30% está no limiar de lucratividade com payout 85%. **Meta de melhoria**: elevar para 60%+ via feature engineering adicional ou tuning de hiperparâmetros (ex: `n_estimators=500`, `learning_rate=0.01`, `num_leaves=63`).

## 4. Bot Operacional em Tempo Real

- Script: `s13_ai_bot.py`
- Fluxo:
  1. Monitora candles M1 de velas fechadas (segundo 58.5–59.5).
  2. Detecta padrão S13 (3 velas com pavios de rejeição >= 40%).
  3. Constrói as 25 features em tempo real via `feature_builder`.
  4. Consulta o modelo treinado: `prob = model.predict_proba(features)[:, 1]`.
  5. Se `prob >= 0.55` (Regra de Ouro), envia ordem CALL/PUT pelo valor definido.
  6. Registra cada operação em `.jsonl` na pasta `logs/`.
- Opções de execução:
  ```bash
  # Modo demo (sem enviar ordens reais)
  python corretora-evemex/s13_ai_bot.py --amount 10 --dry-run

  # Modo real
  python corretora-evemex/s13_ai_bot.py --amount 10 --confidence 0.55
  ```

## 5. Status Atual

- [x] Estrutura da API mapeada (`evemexapi`).
- [x] Script de download de histórico (`download_history.py`).
- [x] Dados baixados (43 pares OTC, M1).
- [x] Gerador de dataset S13 (`ml_dataset_generator_s13.py`) — 51.576 amostras.
- [x] Treinamento do modelo LightGBM (`ml_train_model_s13.py`) — Win Rate filtrado 55,30%.
- [x] Backtest com IA (`ml_backtest_s13.py`) — Lucrativo com filtro (PF 1,05).
- [x] Bot operacional (`s13_ai_bot.py`) — Estrutura completa com dry-run.

## 6. Próximas Etapas Recomendadas

1. **Melhorar Win Rate do Modelo**: Testar XGBoost, aumento de `n_estimators`, `feature_importance` e remoção de features ruidosas.
2. **Validação Temporal Estrita (TimeSeriesSplit)**: Garantir robustez em múltiplas janelas temporais.
3. **Execução Dry-Run ao Vivo**: Validar latência (features + inferência < 100ms) e sincronização do segundo de entrada.
4. **Gestão de Banca**: Implementar Kelly Criterion/posição dinâmica baseada na confiança da IA.
5. **Expandir para outras estratégias (S01-S15)** conforme `ESTRATEGIAS_DETALHADAS.md`.