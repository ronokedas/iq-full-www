import sys
import pandas as pd
import numpy as np
import joblib
from pathlib import Path

def run_backtest(csv_path="corretora-evemex/ml_dataset_s13.csv", model_path="corretora-evemex/signal_filter_s13.pkl", payout=0.85, bet_amount=10.0, threshold=0.55):
    print("📂 Carregando dados para Backtest com IA...")
    if not Path(csv_path).exists():
        print(f"❌ Arquivo {csv_path} não encontrado. Execute ml_dataset_generator_s13.py primeiro.")
        return
        
    if not Path(model_path).exists():
        print(f"❌ Modelo {model_path} não encontrado. Execute ml_train_model_s13.py primeiro.")
        return

    df = pd.read_csv(csv_path)
    model_data = joblib.load(model_path)
    model = model_data['model']
    feature_cols = model_data['features']
    
    # Separa features e target (na mesma ordem do treinamento)
    X = df[feature_cols]
    y = df['target'].values
    
    # Modos de validação: Test Set (últimos 20% do dataset) ou Dataset Completo
    # Para backtest realista, usaremos a fatia de teste (out-of-sample)
    test_size = int(len(df) * 0.2)
    X_test = X.iloc[-test_size:].copy()
    y_test = y[-test_size:]
    
    # Predição do Modelo
    probs = model.predict_proba(X_test)[:, 1]
    
    # --- 1. PERFORMANCE SEM IA (TODOS OS SINAIS S13) ---
    total_trades_base = len(y_test)
    wins_base = int(np.sum(y_test == 1))
    losses_base = total_trades_base - wins_base
    win_rate_base = (wins_base / total_trades_base) * 100 if total_trades_base > 0 else 0
    
    profit_base = (wins_base * bet_amount * payout) - (losses_base * bet_amount)
    profit_factor_base = (wins_base * bet_amount * payout) / (losses_base * bet_amount) if losses_base > 0 else np.inf
    
    # --- 2. PERFORMANCE COM FILTRO DE IA (PROB >= THRESHOLD) ---
    mask_ai = probs >= threshold
    y_test_ai = y_test[mask_ai]
    total_trades_ai = len(y_test_ai)
    wins_ai = int(np.sum(y_test_ai == 1))
    losses_ai = total_trades_ai - wins_ai
    win_rate_ai = (wins_ai / total_trades_ai) * 100 if total_trades_ai > 0 else 0
    
    profit_ai = (wins_ai * bet_amount * payout) - (losses_ai * bet_amount)
    profit_factor_ai = (wins_ai * bet_amount * payout) / (losses_ai * bet_amount) if losses_ai > 0 else np.inf
    
    # Cálculo de Drawdown para IA
    trade_results_ai = np.where(y_test_ai == 1, bet_amount * payout, -bet_amount)
    equity_curve_ai = np.cumsum(trade_results_ai)
    peak = np.maximum.accumulate(equity_curve_ai) if len(equity_curve_ai) > 0 else np.array([0])
    drawdown = peak - equity_curve_ai
    max_dd_ai = np.max(drawdown) if len(drawdown) > 0 else 0.0

    print("\n" + "="*55)
    print("📊 RESULTADOS DO BACKTEST - ESTRATÉGIA S13 (OUT-OF-SAMPLE)")
    print("="*55)
    print(f"💵 Configurações: Entrada = R$ {bet_amount:.2f} | Payout = {payout*100:.1f}% | Limiar IA = {threshold*100:.1f}%")
    print(f"📈 Período de Teste: {total_trades_base} sinais gerados\n")
    
    print(f"{'Métrica':<25} | {'SEM IA (Base)':<12} | {'COM IA (Filtrado)':<15}")
    print("-" * 58)
    print(f"{'Total de Operações':<25} | {total_trades_base:<12} | {total_trades_ai:<15}")
    print(f"{'Vitórias (WIN)':<25} | {wins_base:<12} | {wins_ai:<15}")
    print(f"{'Derrotas (LOSS)':<25} | {losses_base:<12} | {losses_ai:<15}")
    print(f"{'Taxa de Acerto (WinRate)':<25} | {win_rate_base:>11.2f}% | {win_rate_ai:>14.2f}%")
    print(f"{'Resultado Financeiro':<25} | R$ {profit_base:>9.2f} | R$ {profit_ai:>12.2f}")
    print(f"{'Profit Factor':<25} | {profit_factor_base:>12.2f} | {profit_factor_ai:>15.2f}")
    print(f"{'Max Drawdown':<25} | {'N/A':<12} | R$ {max_dd_ai:>12.2f}")
    print("="*55)

if __name__ == "__main__":
    run_backtest()