import pandas as pd
import pandas_ta as ta
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

BACKTEST_DIR = Path(r"C:\iq-full-www\polarium\backtest")

def backtest_fvg_m2(filepath):
    try:
        df = pd.read_csv(filepath)
    except Exception:
        return None
        
    if len(df) < 100:
        return None
        
    # Ordenar por timestamp
    df = df.sort_values(by='timestamp').reset_index(drop=True)
    
    # 1. Transformar M1 em M2 (Resampling)
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
    df.set_index('datetime', inplace=True)
    
    # Agrupar de 2 em 2 minutos
    df_m2 = df.resample('2min').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last'
    }).dropna()
    
    df_m2.reset_index(inplace=True)
    
    if len(df_m2) < 50:
        return None
        
    # Calcular Indicadores na base de M2
    df_m2.ta.ema(length=3, append=True)
    df_m2.ta.ema(length=8, append=True)
    df_m2.ta.mom(length=10, append=True)
    
    try:
        ema3_col = [c for c in df_m2.columns if c.startswith("EMA_3")][0]
        ema8_col = [c for c in df_m2.columns if c.startswith("EMA_8")][0]
        mom_col = [c for c in df_m2.columns if c.startswith("MOM_10")][0]
    except IndexError:
        return None
        
    wins_call = 0
    losses_call = 0
    wins_put = 0
    losses_put = 0
    
    # Agora iteramos na base de M2. Próxima vela = 1 vela de M2
    for i in range(30, len(df_m2) - 1):
        v1 = df_m2.iloc[i-3]
        v2 = df_m2.iloc[i-2]
        v3 = df_m2.iloc[i-1]
        v4 = df_m2.iloc[i]     # A vela do "Toque" em M2
        v5 = df_m2.iloc[i+1]   # Próxima Vela de M2 (Entrada e Fechamento)
        
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
            if v2['close'] > v1['high']:
                if v3['close'] > v2['high']:
                    if v3['low'] > v1['high']: # FVG ALTA
                        if v4['low'] <= v1['high'] and v4['high'] >= v1['high']: # Toca V1 high
                            if mom > 0 and ema3 > ema8:
                                # Entrada na abertura de V5, saída no fechamento de V5 (Tudo em M2)
                                entry_price = v5['open']
                                exit_price = v5['close']
                                if exit_price > entry_price:
                                    wins_call += 1
                                else:
                                    losses_call += 1
                                    
        # SETUP PUT
        v1_green = v1['close'] > v1['open']
        v2_red = v2['close'] < v2['open']
        v3_red = v3['close'] < v3['open']
        
        if v1_green and v2_red and v3_red:
            if v2['close'] < v1['low']:
                if v3['close'] < v2['low']:
                    if v3['high'] < v1['low']: # FVG BAIXA
                        if v4['high'] >= v1['low'] and v4['low'] <= v1['low']: # Toca V1 low
                            if mom < 0 and ema3 < ema8:
                                # Entrada na abertura de V5, saída no fechamento de V5 (Tudo em M2)
                                entry_price = v5['open']
                                exit_price = v5['close']
                                if exit_price < entry_price:
                                    wins_put += 1
                                else:
                                    losses_put += 1
                                    
    return {"cw": wins_call, "cl": losses_call, "pw": wins_put, "pl": losses_put}

def main():
    print("Iniciando backtest do Setup FVG convertido ESTRITAMENTE para M2...")
    print("Convertendo velas M1 -> M2 e rodando indicadores em M2...\n")
    
    files = list(BACKTEST_DIR.glob("*.csv"))
    results = []
    total_w = 0
    total_l = 0
    
    for f in files:
        stats = backtest_fvg_m2(f)
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
    
    print("=== ESTATÍSTICAS GLOBAIS DA ESTRATÉGIA FVG (TEMPO GRÁFICO M2) ===")
    total = total_w + total_l
    global_wr = (total_w / total) * 100 if total > 0 else 0
    print(f"Total de Entradas em M2: {total}")
    print(f"Wins: {total_w} | Losses: {total_l}")
    print(f"Taxa de Acerto Global: {global_wr:.2f}%\n")
    
    print("=== PARES ANALISADOS (Win Rate) ===")
    count = 0
    for par, wr, w, l, t in results:
        print(f"{par:20} | Acerto: {wr:.2f}% | Entradas: {t:3} | Wins: {w} | Loss: {l}")
        count += 1
        if count >= 30:
            break

if __name__ == "__main__":
    main()
