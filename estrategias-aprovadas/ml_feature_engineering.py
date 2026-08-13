import pandas as pd
import numpy as np
from pathlib import Path
import os

def calculate_features(df):
    """
    Calcula as características (features) para o dataset de ML.
    """
    df = df.copy()
    
    # 1. Volatilidade recente (ATR simplificado e Desvio Padrão)
    df['tr'] = np.maximum(df['high'] - df['low'], 
                          np.maximum(abs(df['high'] - df['close'].shift(1)), 
                                     abs(df['low'] - df['close'].shift(1))))
    df['atr_14'] = df['tr'].rolling(window=14).mean()
    df['std_14'] = df['close'].rolling(window=14).std()
    
    # 2. Inclinação da tendência (Diferencial entre EMA9 e EMA21)
    df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['trend_slope'] = (df['ema9'] - df['ema21']) / df['ema21'] * 100
    
    # 3. Sazonalidade (Horário do dia)
    df['dt'] = pd.to_datetime(df['from_ts'], unit='s')
    df['hour'] = df['dt'].dt.hour
    df['minute'] = df['dt'].dt.minute
    # Seno/Cosseno para representar ciclicidade do tempo
    df['hour_sin'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['hour_cos'] = np.cos(2 * np.pi * df['hour'] / 24)
    
    # 4. Proporção do tamanho dos corpos e pavios nos últimos 5 candles
    df['body_size'] = abs(df['close'] - df['open'])
    df['upper_wick'] = df['high'] - df.loc[:, ['open', 'close']].max(axis=1)
    df['lower_wick'] = df.loc[:, ['open', 'close']].min(axis=1) - df['low']
    
    df['avg_body_5'] = df['body_size'].rolling(window=5).mean()
    df['avg_upper_wick_5'] = df['upper_wick'].rolling(window=5).mean()
    df['avg_lower_wick_5'] = df['lower_wick'].rolling(window=5).mean()
    
    # 5. Distância em pips em relação às zonas de suporte/resistência (M15/H1 simplificado)
    # Usaremos máximas e mínimas de janelas maiores como proxies de S/R
    df['res_h1'] = df['high'].rolling(window=60).max()
    df['sup_h1'] = df['low'].rolling(window=60).min()
    df['res_m15'] = df['high'].rolling(window=15).max()
    df['sup_m15'] = df['low'].rolling(window=15).min()
    
    df['dist_res_h1'] = (df['res_h1'] - df['close'])
    df['dist_sup_h1'] = (df['close'] - df['sup_h1'])
    df['dist_res_m15'] = (df['res_m15'] - df['close'])
    df['dist_sup_m15'] = (df['close'] - df['sup_m15'])
    
    # 6. Features adicionais de momentum e força
    # RSI (Relative Strength Index) - 14 períodos
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = (-delta.clip(upper=0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df['rsi_14'] = 100 - (100 / (1 + rs))
    
    # Momentum (retorno percentual em diferentes janelas)
    df['mom_3'] = df['close'].pct_change(periods=3) * 100
    df['mom_5'] = df['close'].pct_change(periods=5) * 100
    
    # Proporção corpo/pavio (normalizada pelo range do candle)
    df['range'] = df['high'] - df['low']
    df['body_ratio'] = df['body_size'] / df['range'].replace(0, np.nan)
    df['upper_wick_ratio'] = df['upper_wick'] / df['range'].replace(0, np.nan)
    df['lower_wick_ratio'] = df['lower_wick'] / df['range'].replace(0, np.nan)
    
    # Médias móveis de corpo/pavio (últimos 5 candles)
    df['avg_body_ratio_5'] = df['body_ratio'].rolling(window=5).mean()
    df['avg_upper_wick_ratio_5'] = df['upper_wick_ratio'].rolling(window=5).mean()
    df['avg_lower_wick_ratio_5'] = df['lower_wick_ratio'].rolling(window=5).mean()
    
    # Distância do preço em relação à EMA (normalizada)
    df['dist_ema9'] = (df['close'] - df['ema9']) / df['ema9'] * 100
    df['dist_ema21'] = (df['close'] - df['ema21']) / df['ema21'] * 100
    
    # Volatilidade relativa (ATR / preço)
    df['atr_pct'] = df['atr_14'] / df['close'] * 100
    
    return df.dropna()

if __name__ == "__main__":
    # Teste rápido
    data_path = Path("estrategias-aprovadas/dados/iq_option/m1/EURUSD_OTC.parquet")
    if data_path.exists():
        df = pd.read_parquet(data_path)
        df_features = calculate_features(df)
        print(f"Features calculadas. Shape: {df_features.shape}")
        print(df_features[['trend_slope', 'atr_14', 'hour_sin', 'avg_body_5', 'dist_res_h1']].head())