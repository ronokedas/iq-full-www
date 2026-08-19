import csv
import pandas as pd
import pandas_ta as ta
from pathlib import Path

BACKTEST_DIR = Path(r"C:\iq-full-www\polarium\backtest")

def backtest_engolfo(filepath):
    try:
        df = pd.read_csv(filepath)
    except Exception:
        return None
        
    if len(df) < 100:
        return None
        
    df = df.sort_values(by='timestamp').reset_index(drop=True)
    
    # Calcular indicadores de confluência
    df.ta.ema(length=9, append=True)
    df.ta.ema(length=21, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.mom(length=10, append=True)
    
    try:
        ema9_col = [c for c in df.columns if c.startswith("EMA_9")][0]
        ema21_col = [c for c in df.columns if c.startswith("EMA_21")][0]
        rsi_col = [c for c in df.columns if c.startswith("RSI_14")][0]
        mom_col = [c for c in df.columns if c.startswith("MOM_10")][0]
    except IndexError:
        return None
        
    wins_bullish = 0
    losses_bullish = 0
    wins_bearish = 0
    losses_bearish = 0
    
    # Avaliar o padrão (requer v1, v2 e precisamos da v3 para ver se deu win)
    for i in range(30, len(df) - 1):
        v1 = df.iloc[i-1]
        v2 = df.iloc[i]
        v3 = df.iloc[i+1] # Próxima vela (resultado)
        
        # Valores de confluência da vela de gatilho (v2)
        ema9 = v2[ema9_col]
        ema21 = v2[ema21_col]
        rsi = v2[rsi_col]
        mom = v2[mom_col]
        
        if pd.isna(ema9) or pd.isna(ema21) or pd.isna(rsi) or pd.isna(mom):
            continue
            
        # Padrão: ENGOLFO DE ALTA (Bullish Engulfing)
        # V1 é Vermelha
        v1_red = v1['close'] < v1['open']
        # V2 é Verde
        v2_green = v2['close'] > v2['open']
        # V2 fecha acima da MÁXIMA da V1
        v2_engulfs_up = v2['close'] > v1['high']
        
        if v1_red and v2_green and v2_engulfs_up:
            # Filtro de Confluência para ALTA
            if ema9 > ema21 and v2['close'] > ema9 and rsi > 50 and mom > 0:
                # Simulando entrada de COMPRA na abertura da V3
                if v3['close'] > v3['open']:
                    wins_bullish += 1
                else:
                    losses_bullish += 1
                    
        # Padrão: ENGOLFO DE BAIXA (Bearish Engulfing)
        # V1 é Verde
        v1_green = v1['close'] > v1['open']
        # V2 é Vermelha
        v2_red = v2['close'] < v2['open']
        # V2 fecha abaixo da MÍNIMA da V1
        v2_engulfs_down = v2['close'] < v1['low']
        
        if v1_green and v2_red and v2_engulfs_down:
            # Filtro de Confluência para BAIXA
            if ema9 < ema21 and v2['close'] < ema9 and rsi < 50 and mom < 0:
                # Simulando entrada de VENDA na abertura da V3
                if v3['close'] < v3['open']:
                    wins_bearish += 1
                else:
                    losses_bearish += 1
                    
    return {
        "bull_w": wins_bullish, "bull_l": losses_bullish,
        "bear_w": wins_bearish, "bear_l": losses_bearish
    }

def main():
    print("Iniciando backtest do Padrão de ENGOLFO COM CONFLUÊNCIA (EMA 9/21, RSI, Momentum)...")
    files = list(BACKTEST_DIR.glob("*.csv"))
    
    results = []
    total_bull_w, total_bull_l = 0, 0
    total_bear_w, total_bear_l = 0, 0
    
    for f in files:
        stats = backtest_engolfo(f)
        if stats:
            bull_w = stats["bull_w"]
            bull_l = stats["bull_l"]
            bear_w = stats["bear_w"]
            bear_l = stats["bear_l"]
            
            total_bull_w += bull_w
            total_bull_l += bull_l
            total_bear_w += bear_w
            total_bear_l += bear_l
            
            t_bull = bull_w + bull_l
            t_bear = bear_w + bear_l
            t_total = t_bull + t_bear
            
            if t_total > 0:
                wr = ((bull_w + bear_w) / t_total) * 100
                results.append((f.stem.replace("_M1_7days", ""), wr, bull_w+bear_w, bull_l+bear_l, t_total))
                
    results.sort(key=lambda x: x[1], reverse=True)
    
    print("\n=== ESTATÍSTICAS GLOBAIS DO ENGOLFO + CONFLUÊNCIA ===")
    t_bull_global = total_bull_w + total_bull_l
    bull_wr = (total_bull_w / t_bull_global * 100) if t_bull_global > 0 else 0
    print(f"Engolfo de ALTA  -> Wins: {total_bull_w} | Loss: {total_bull_l} | Acerto: {bull_wr:.2f}%")
    
    t_bear_global = total_bear_w + total_bear_l
    bear_wr = (total_bear_w / t_bear_global * 100) if t_bear_global > 0 else 0
    print(f"Engolfo de BAIXA -> Wins: {total_bear_w} | Loss: {total_bear_l} | Acerto: {bear_wr:.2f}%")
    
    total_global = t_bull_global + t_bear_global
    global_wr = ((total_bull_w + total_bear_w) / total_global * 100) if total_global > 0 else 0
    print(f"Taxa de Acerto Global: {global_wr:.2f}%\n")
    
    print("=== TOP 20 PARES PARA ENGOLFO (Win Rate Mão Fixa) ===")
    count = 0
    for par, wr, w, l, t in results:
        if t >= 10: # Filtrar por ativos com pelo menos 10 oportunidades
            print(f"{par:20} | Acerto: {wr:.2f}% | Wins: {w} | Loss: {l}")
            count += 1
        if count >= 20:
            break

if __name__ == "__main__":
    main()
