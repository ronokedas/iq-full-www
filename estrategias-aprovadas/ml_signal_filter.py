import pandas as pd
import numpy as np
import joblib
import os
from ml_feature_engineering import calculate_features

class SignalFilter:
    """
    Filtro de sinais baseado em Machine Learning.
    Regra de Ouro: Só entra se Probabilidade_Modelo(WIN) >= 0.55
    """
    
    def __init__(self, model_path='estrategias-aprovadas/signal_filter_model.pkl'):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Modelo não encontrado em {model_path}. Treine primeiro com ml_train_model.py")
        
        model_data = joblib.load(model_path)
        self.model = model_data['model']
        self.features = model_data['features']
        self.threshold = 0.55  # Regra de Ouro: confiança mínima de 55%
    
    def predict_win_probability(self, df_features):
        """
        Calcula a probabilidade de WIN para cada sinal.
        df_features: DataFrame com as features calculadas via calculate_features()
        """
        X = df_features[self.features]
        return self.model.predict_proba(X)[:, 1]
    
    def should_enter(self, prob_win):
        """
        Decide se deve entrar na operação.
        Retorna True se prob_win >= 0.55 (Regra de Ouro).
        """
        return prob_win >= self.threshold
    
    def filter_signals(self, df_features):
        """
        Filtra os sinais, retornando apenas aqueles com confiança >= 55%.
        """
        df = df_features.copy()
        df['prob_win'] = self.predict_win_probability(df)
        df['should_enter'] = df['prob_win'] >= self.threshold
        return df

if __name__ == "__main__":
    # Teste rápido do filtro
    try:
        filtro = SignalFilter()
        print("Filtro de sinais carregado com sucesso!")
        print(f"Features usadas: {filtro.features}")
        print(f"Threshold de confiança: {filtro.threshold*100}%")
        
        # Teste com dados de exemplo
        data_path = "estrategias-aprovadas/dados/iq_option/m1/EURUSD_OTC.parquet"
        if os.path.exists(data_path):
            df = pd.read_parquet(data_path)
            df_features = calculate_features(df)
            
            # Simular um sinal (última linha)
            ultimo_sinal = df_features.iloc[[-1]]
            prob = filtro.predict_win_probability(ultimo_sinal)[0]
            decisao = filtro.should_enter(prob)
            
            print(f"\nTeste com último candle de EURUSD-OTC:")
            print(f"Probabilidade de WIN: {prob:.4f} ({prob*100:.2f}%)")
            print(f"Decisão: {'ENTRAR' if decisao else 'NÃO ENTRAR'} (confiança {'>=' if decisao else '<'} 55%)")
    except FileNotFoundError as e:
        print(f"Erro: {e}")