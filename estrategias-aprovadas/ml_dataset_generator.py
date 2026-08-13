import pandas as pd
import numpy as np
from pathlib import Path
import os
import sys
import importlib.util

# Adicionar diretório ao path para importar backtest-full
sys.path.append(str(Path(__file__).parent))

# Carregar backtest-full.py como módulo (nome com hífen não é importável diretamente)
backtest_path = Path(__file__).parent / "backtest-full.py"
spec = importlib.util.spec_from_file_location("backtest_full", backtest_path)
backtest_full = importlib.util.module_from_spec(spec)
sys.modules["backtest_full"] = backtest_full
spec.loader.exec_module(backtest_full)

BacktestEngine = backtest_full.BacktestEngine
Trade = backtest_full.Trade

from ml_feature_engineering import calculate_features

def generate_ml_dataset(data_dir, output_path):
    """
    Gera dataset de ML de forma otimizada:
    1. Pré-calcula features para todos os dataframes de cada símbolo.
    2. Executa o backtest para extrair os sinais reais.
    3. Associa cada sinal às suas features pré-calculadas.
    """
    data_dir = Path(data_dir)
    if not data_dir.exists():
        print(f"Erro: Pasta {data_dir} não encontrada.")
        return None
    
    # Instanciar o motor de backtest
    engine = BacktestEngine(data_dir)
    if not engine.load_data():
        return None
    
    # 1. Pré-calcular features para cada símbolo
    print("Pré-calculando features para cada par de moedas...")
    features_by_symbol = {}
    for symbol, df in engine.dataframes.items():
        print(f"  Calcular features para {symbol} ({len(df)} velas)...")
        df_feat = calculate_features(df)
        # Mapear por timestamp (from_ts) para busca O(1)
        features_by_symbol[symbol] = df_feat.set_index('from_ts')
    
    # 2. Executar backtest
    print("\nExecutando backtest para extrair sinais de todas as estratégias...")
    results = engine.run_backtest()
    
    all_samples = []
    
    # 3. Mapear cada trade para suas features
    for strategy_name, stats in results.items():
        print(f"Processando {strategy_name}: {stats.total_trades} trades")
        
        for trade in stats.trades:
            if trade.result not in ["WIN", "LOSS", "DOJI"]:
                continue
            
            symbol = trade.symbol
            if symbol not in features_by_symbol:
                continue
            
            df_feat = features_by_symbol[symbol]
            ts = trade.timestamp
            
            if ts not in df_feat.index:
                continue
            
            # Obter features da linha correspondente
            row = df_feat.loc[ts]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            
            features = row.to_dict()
            
            # Rotulagem: Target = 1 se WIN, 0 se LOSS ou DOJI
            target = 1 if trade.result == "WIN" else 0
            
            features['target'] = target
            features['strategy'] = strategy_name
            features['direction'] = trade.direction
            features['symbol'] = symbol
            
            all_samples.append(features)
    
    if not all_samples:
        print("Nenhum sinal extraído.")
        return None
    
    dataset = pd.DataFrame(all_samples)
    dataset.to_csv(output_path, index=False)
    print(f"\nDataset gerado com sucesso! {len(dataset)} amostras salvas em {output_path}")
    print(f"Distribuição do Target:\n{dataset['target'].value_counts(normalize=True)}")
    return dataset

if __name__ == "__main__":
    data_dir = "estrategias-aprovadas/dados/iq_option/m1"
    output_path = "estrategias-aprovadas/ml_dataset.csv"
    generate_ml_dataset(data_dir, output_path)