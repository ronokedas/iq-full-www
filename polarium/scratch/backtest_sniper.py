import csv
import pandas as pd
import pandas_ta as ta
from pathlib import Path

BACKTEST_DIR = Path(r"C:\iq-full-www\polarium\backtest")

def backtest_sniper(filepath):
    try:
        df = pd.read_csv(filepath)
    except Exception:
        return None
        
    if len(df) < 100:
        return None
        
    # Ordenar por timestamp
    df = df.sort_values(by='timestamp').reset_index(drop=True)
    
    # Calcular indicadores
    df.ta.rsi(length=14, append=True)
    df.ta.bbands(length=20, std=2.0, append=True)
    
    # Encontrar as colunas dinamicamente para evitar KeyError
    rsi_col = f"RSI_14"
    try:
        bbl_col = [c for c in df.columns if c.startswith("BBL_20")][0]
        bbu_col = [c for c in df.columns if c.startswith("BBU_20")][0]
    except IndexError:
        return None # Falha ao gerar colunas
        
    wins = 0
    losses = 0
    cooldown = 0
    
    # A iterar pelas linhas (ignorando a última pois precisamos da "next candle" para verificar o resultado)
    for i in range(30, len(df) - 1):
        if cooldown > 0:
            cooldown -= 1
            continue
            
        current = df.iloc[i]
        next_candle = df.iloc[i+1]
        
        rsi = current[rsi_col]
        close_price = current['close']
        bbl = current[bbl_col]
        bbu = current[bbu_col]
        
        # O preço de entrada na vida real sofre pequeno delay, mas a teoria diz que entramos na abertura da próxima
        entry_price = next_candle['open']
        exit_price = next_candle['close']
        
        # Condição de Compra (CALL)
        if pd.notna(rsi) and pd.notna(bbl):
            if rsi < 25 and close_price < bbl:
                if exit_price > entry_price:
                    wins += 1
                else:
                    losses += 1
                cooldown = 1 # Pausa a próxima vela (60s)
                continue
                
        # Condição de Venda (PUT)
        if pd.notna(rsi) and pd.notna(bbu):
            if rsi > 75 and close_price > bbu:
                if exit_price < entry_price:
                    wins += 1
                else:
                    losses += 1
                cooldown = 1 # Pausa a próxima vela (60s)
                continue
                
    return {"w": wins, "l": losses}

def main():
    print("Iniciando backtest massivo da estratégia Sniper (RSI + Bollinger)...")
    files = list(BACKTEST_DIR.glob("*.csv"))
    
    results = []
    total_w = 0
    total_l = 0
    
    for f in files:
        stats = backtest_sniper(f)
        if stats:
            w = stats["w"]
            l = stats["l"]
            total_w += w
            total_l += l
            
            total_trades = w + l
            if total_trades > 0: # Como é sniper, pode ter poucos trades
                wr = (w / total_trades) * 100
                results.append((f.stem.replace("_M1_7days", ""), wr, w, l, total_trades))
                
    results.sort(key=lambda x: x[1], reverse=True)
    
    print("\n=== ESTATÍSTICAS GLOBAIS DA ESTRATÉGIA SNIPER ===")
    total = total_w + total_l
    global_wr = (total_w / total) * 100 if total > 0 else 0
    print(f"Total de Entradas: {total}")
    print(f"Wins: {total_w} | Losses: {total_l}")
    print(f"Taxa de Acerto Global (Mão Fixa): {global_wr:.2f}%\n")
    
    print("=== TOP 50 PARES PARA O ROBÔ SNIPER (Win Rate Mão Fixa) ===")
    print("Obs: Pares com poucas entradas significam que a anomalia é rara, mas mortal.\n")
    
    count = 0
    for par, wr, w, l, t in results:
        if t >= 10: # Filtrar por ativos que deram pelo menos 10 oportunidades na semana
            print(f"{par:20} | Acerto: {wr:.2f}% | Wins: {w} | Loss: {l}")
            count += 1
        if count >= 50:
            break

if __name__ == "__main__":
    main()
