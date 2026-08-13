"""Treina o filtro de IA (LightGBM) para a Estratégia S16.

Regra de Ouro: o bot só fará a entrada real se Probabilidade_Modelo(WIN) >= 0.55
(55% de confiança mínima, garantindo a meta acima de 50%).

Validação temporal: treina nos primeiros 80% do tempo e testa nos últimos 20%
(sem embaralhamento), para medir o winrate real em dados que o modelo nunca viu.
"""
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.metrics import accuracy_score
import joblib
import os
from pathlib import Path
from retrain_models import train_model as train_aligned_model


def train_model_s16(dataset_path):
    if not os.path.exists(dataset_path):
        print(f"❌ Erro: Dataset {dataset_path} não encontrado.")
        return

    print(f"📂 Carregando dataset de {dataset_path}...")
    df = pd.read_csv(dataset_path)

    if len(df) < 50:
        print("⚠️ Dataset muito pequeno para treinamento confiável.")
        return

    # Seleção de features (exclui colunas não-numéricas e de identificação)
    exclude_cols = [
        'target', 'symbol', 'direction', 'from_ts', 'to_ts', 'dt',
        'open', 'high', 'low', 'close', 'volume',
    ]
    features = [c for c in df.columns if c not in exclude_cols]

    X = df[features]
    y = df['target']

    # Validação temporal (sem embaralhamento) para evitar data leakage.
    # Treina nos primeiros 80% e testa nos últimos 20% (dados que o modelo nunca viu).
    split = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]

    print(f"🚀 Treinando LightGBM para S16 com {len(X_train)} amostras e {len(features)} features...")
    print(f"📊 Divisão temporal: treino {len(X_train)} | teste {len(X_test)}")

    model = lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.02,
        num_leaves=31,
        max_depth=6,
        min_child_samples=15,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1
    )

    model.fit(X_train, y_train)

    # Avaliação
    y_pred_proba = model.predict_proba(X_test)[:, 1]

    # Avaliação com Threshold de Confiança (Regra de Ouro: 55%)
    threshold = 0.55
    mask_conf = y_pred_proba >= threshold

    print("\n--- Resultados do Modelo S16 ---")
    print(f"🎯 Winrate base (sem filtro) no teste: {y_test.mean():.2%}")

    if mask_conf.any():
        y_test_conf = y_test[mask_conf]
        win_rate = y_test_conf.mean()
        n_operable = mask_conf.sum()

        print(f"✅ Win Rate Filtrado (Confiança >= {threshold*100}%): {win_rate:.2%}")
        print(f"📊 Sinais Operáveis: {n_operable} de {len(y_test)} no teste ({n_operable/len(y_test):.1%})")
        print(f"📈 Acurácia Geral (threshold 50%): {accuracy_score(y_test, (y_pred_proba >= 0.5).astype(int)):.4f}")

        # Verifica se atinge a meta de 60%+
        if win_rate >= 0.60:
            print(f"\n🎉 META ATINGIDA: winrate filtrado {win_rate:.2%} >= 60%!")
        elif win_rate >= 0.55:
            print(f"\n✅ META PARCIAL: winrate filtrado {win_rate:.2%} >= 55% (acima do breakeven 54.05%)")
        else:
            print(f"\n⚠️ Abaixo da meta: winrate filtrado {win_rate:.2%} < 55%")
    else:
        print(f"⚠️ Nenhum sinal atingiu a confiança de {threshold*100}% no conjunto de teste.")

    # Salvar modelo e lista de features
    model_data = {
        'model': model,
        'features': features,
        'threshold': threshold,
    }
    model_path = 'corretora-evemex/signal_filter_s16.pkl'
    joblib.dump(model_data, model_path)
    print(f"\n✨ Modelo salvo em {model_path}")


if __name__ == "__main__":
    train_aligned_model("s16", Path(__file__).parent / "ml_dataset_s16.csv")
