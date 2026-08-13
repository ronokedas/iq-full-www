import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import joblib
import os
from pathlib import Path
from retrain_models import train_model as train_aligned_model

def train_model_s13(dataset_path):
    if not os.path.exists(dataset_path):
        print(f"❌ Erro: Dataset {dataset_path} não encontrado.")
        return

    print(f"📂 Carregando dataset de {dataset_path}...")
    df = pd.read_csv(dataset_path)
    
    if len(df) < 50:
        print("⚠️ Dataset muito pequeno para treinamento confiável.")
        return

    # Seleção de features
    exclude_cols = ['target', 'symbol', 'timeframe', 'from_ts', 'to_ts', 'dt', 
                    'open', 'high', 'low', 'close', 'volume', 'tr', 'ema9', 'ema21',
                    'hour', 'minute', 'body_size', 'upper_wick', 'lower_wick',
                    'res_h1', 'sup_h1', 'res_m15', 'sup_m15', 'range', 'strategy', 'direction']
    
    features = [c for c in df.columns if c not in exclude_cols]
    
    X = df[features]
    y = df['target']

    # Validação temporal (sem embaralhamento) para evitar data leakage.
    # Treina nos primeiros 80% e testa nos últimos 20% (dados que o modelo nunca viu).
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, shuffle=False)

    print(f"🚀 Treinando LightGBM para S13 com {len(X_train)} amostras e {len(features)} features...")
    
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
    
    # Avaliação com Threshold de Confiança (Meta: 55%)
    threshold = 0.55
    mask_conf = y_pred_proba >= threshold
    
    print("\n--- Resultados do Modelo S13 ---")
    if mask_conf.any():
        y_test_conf = y_test[mask_conf]
        y_pred_conf = (y_pred_proba[mask_conf] >= 0.5).astype(int)
        acc_conf = accuracy_score(y_test_conf, (y_pred_proba[mask_conf] >= 0.5).astype(int))
        
        # Precisão real (quantos dos que a IA disse que seriam WIN realmente foram)
        win_rate = y_test_conf.mean()
        
        print(f"✅ Win Rate Filtrado (Confiança >= {threshold*100}%): {win_rate:.2%}")
        print(f"📊 Sinais Operáveis: {mask_conf.sum()} de {len(y_test)} no teste")
        print(f"📈 Acurácia Geral: {accuracy_score(y_test, (y_pred_proba >= 0.5).astype(int)):.4f}")
    else:
        print(f"⚠️ Nenhum sinal atingiu a confiança de {threshold*100}% no conjunto de teste.")

    # Salvar modelo e lista de features
    model_data = {
        'model': model,
        'features': features
    }
    model_path = 'corretora-evemex/signal_filter_s13.pkl'
    joblib.dump(model_data, model_path)
    print(f"\n✨ Modelo salvo em {model_path}")

if __name__ == "__main__":
    train_aligned_model("s13", Path(__file__).parent / "ml_dataset_s13.csv")
