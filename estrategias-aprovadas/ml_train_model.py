import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
import joblib
import os

def train_model(dataset_path):
    if not os.path.exists(dataset_path):
        print(f"Erro: Dataset {dataset_path} não encontrado.")
        return

    print(f"Carregando dataset de {dataset_path}...")
    df = pd.read_csv(dataset_path)
    
    if len(df) < 100:
        print("Dataset muito pequeno para treinamento confiável.")
        return

    # Seleção de features - todas as features calculadas
    exclude_cols = ['target', 'symbol', 'timeframe', 'from_ts', 'to_ts', 'dt', 
                    'open', 'high', 'low', 'close', 'volume', 'tr', 'ema9', 'ema21',
                    'hour', 'minute', 'body_size', 'upper_wick', 'lower_wick',
                    'res_h1', 'sup_h1', 'res_m15', 'sup_m15', 'range', 'strategy']
    
    features = [c for c in df.columns if c not in exclude_cols]
    
    # Adicionar strategy como dummy se houver mais de uma
    if 'strategy' in df.columns and df['strategy'].nunique() > 1:
        df = pd.get_dummies(df, columns=['strategy'])
        features = [c for c in df.columns if c not in exclude_cols]

    X = df[features]
    y = df['target']

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    print(f"Treinando LightGBM com {len(X_train)} amostras e {len(features)} features...")
    
    model = lgb.LGBMClassifier(
        n_estimators=200,
        learning_rate=0.03,
        num_leaves=63,
        max_depth=7,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=0.1,
        random_state=42,
        verbose=-1
    )
    
    model.fit(X_train, y_train)

    # Avaliação
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    y_pred = (y_pred_proba >= 0.5).astype(int)

    print("\n--- Resultados do Modelo (Threshold 0.50) ---")
    print(f"Acurácia: {accuracy_score(y_test, y_pred):.4f}")
    print(classification_report(y_test, y_pred))

    # Avaliação com Threshold de Confiança (Meta: 55%)
    threshold = 0.55
    y_pred_conf = (y_pred_proba >= threshold).astype(int)
    
    # Filtrar apenas onde o modelo deu sinal de confiança
    mask_conf = y_pred_proba >= threshold
    if mask_conf.any():
        acc_conf = accuracy_score(y_test[mask_conf], y_pred_conf[mask_conf])
        print(f"\n--- Resultados com Confiança >= {threshold*100}% ---")
        print(f"Acurácia Filtrada: {acc_conf:.4f}")
        print(f"Sinais Filtrados: {mask_conf.sum()} de {len(y_test)}")
    else:
        print(f"\nNenhum sinal atingiu a confiança de {threshold*100}% no conjunto de teste.")

    # Salvar modelo e lista de features
    model_data = {
        'model': model,
        'features': features
    }
    joblib.dump(model_data, 'estrategias-aprovadas/signal_filter_model.pkl')
    print("\nModelo salvo em estrategias-aprovadas/signal_filter_model.pkl")

if __name__ == "__main__":
    train_model('estrategias-aprovadas/ml_dataset.csv')