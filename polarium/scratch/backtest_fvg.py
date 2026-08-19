import pandas as pd
import pandas_ta as ta
from pathlib import Path

BACKTEST_DIR = Path(r"C:\iq-full-www\polarium\backtest")

def backtest_fvg_strategy(filepath):
    try:
        df = pd.read_csv(filepath)
    except Exception:
        return None
        
    if len(df) < 100:
        return None
        
    df = df.sort_values(by='timestamp').reset_index(drop=True)
    
    # Calcular Indicadores
    df.ta.ema(length=3, append=True)
    df.ta.ema(length=8, append=True)
    df.ta.mom(length=10, append=True)
    
    try:
        ema3_col = [c for c in df.columns if c.startswith("EMA_3")][0]
        ema8_col = [c for c in df.columns if c.startswith("EMA_8")][0]
        mom_col = [c for c in df.columns if c.startswith("MOM_10")][0]
    except IndexError:
        return None
        
    wins_call = 0
    losses_call = 0
    wins_put = 0
    losses_put = 0
    
    # Iteramos até len(df)-2 para permitir expiração de M2 (2 candles para frente)
    for i in range(30, len(df) - 2):
        v1 = df.iloc[i-3]
        v2 = df.iloc[i-2]
        v3 = df.iloc[i-1]
        v4 = df.iloc[i]     # A vela do "Toque"
        v5 = df.iloc[i+1]   # Vela da Entrada (Abertura)
        v6 = df.iloc[i+2]   # Vela da Saída (Fechamento) -> M2 expiração
        
        # Valores dos indicadores no momento do toque (V4)
        ema3 = v4[ema3_col]
        ema8 = v4[ema8_col]
        mom = v4[mom_col]
        
        if pd.isna(ema3) or pd.isna(ema8) or pd.isna(mom):
            continue
            
        # SETUP CALL
        v1_red = v1['close'] < v1['open']
        v2_green = v2['close'] > v2['open']
        v3_green = v3['close'] > v3['open']
        
        if v1_red and v2_green and v3_green:
            # V2 fecha acima da máxima de V1
            if v2['close'] > v1['high']:
                # V3 fecha acima da máxima de V2
                if v3['close'] > v2['high']:
                    # FVG: Mínima da V3 acima da máxima da V1
                    if v3['low'] > v1['high']:
                        # V4 deve tocar a máxima da V1 (baixa além dela ou bate nela)
                        if v4['low'] <= v1['high'] and v4['high'] >= v1['high']:
                            # Confluências para CALL
                            if mom > 0 and ema3 > ema8:
                                # Entrada na abertura de V5, saída no fechamento de V6 (Expiração M2)
                                entry_price = v5['open']
                                exit_price = v6['close']
                                if exit_price > entry_price:
                                    wins_call += 1
                                else:
                                    losses_call += 1
                                    
        # SETUP PUT
        v1_green = v1['close'] > v1['open']
        v2_red = v2['close'] < v2['open']
        v3_red = v3['close'] < v3['open']
        
        if v1_green and v2_red and v3_red:
            # V2 fecha abaixo da mínima de V1
            if v2['close'] < v1['low']:
                # V3 fecha abaixo da mínima de V2
                if v3['close'] < v2['low']:
                    # FVG: Máxima da V3 abaixo da mínima da V1
                    if v3['high'] < v1['low']:
                        # V4 deve tocar a mínima da V1 (sobe além dela ou bate nela)
                        if v4['high'] >= v1['low'] and v4['low'] <= v1['low']:
                            # Confluências para PUT
                            if mom < 0 and ema3 < ema8:
                                # Entrada na abertura de V5, saída no fechamento de V6 (Expiração M2)
                                entry_price = v5['open']
                                exit_price = v6['close']
                                if exit_price < entry_price:
                                    wins_put += 1
                                else:
                                    losses_put += 1
                                    
    return {"cw": wins_call, "cl": losses_call, "pw": wins_put, "pl": losses_put}

def main():
    print("Iniciando backtest do Setup Institucional FVG (Fair Value Gap) + Toque + Momentum + EMA 3/8...")
    print("Expiração: M2 (2 Minutos)\n")
    
    files = list(BACKTEST_DIR.glob("*.csv"))
    results = []
    
    total_w = 0
    total_l = 0
    
    for f in files:
        stats = backtest_fvg_strategy(f)
        if stats:
            w = stats["cw"] + stats["pw"]
            l = stats["cl"] + stats["pl"]
            total_w += w
            total_l += l
            
            t = w + l
            if t > 0:
                wr = (w / t) * 100
                results.append((f.stem.replace("_M1_7days", ""), wr, w, l, t))
                
    results.sort(key=lambda x: x[1], reverse=True)
    
    print("=== ESTATÍSTICAS GLOBAIS DA ESTRATÉGIA FVG ===")
    total = total_w + total_l
    global_wr = (total_w / total) * 100 if total > 0 else 0
    print(f"Total de Entradas: {total}")
    print(f"Wins: {total_w} | Losses: {total_l}")
    print(f"Taxa de Acerto Global (Mão Fixa M2): {global_wr:.2f}%\n")
    
    print("=== PARES ANALISADOS (Win Rate) ===")
    count = 0
    for par, wr, w, l, t in results:
        # Padrões institucionais são muito raros, qualquer entrada importa
        print(f"{par:20} | Acerto: {wr:.2f}% | Entradas: {t} | Wins: {w} | Loss: {l}")
        count += 1
        if count >= 30:
            break

if __name__ == "__main__":
    main()
