import pandas as pd
import pandas_ta as ta
from pathlib import Path

BACKTEST_DIR = Path(r"C:\iq-full-www\polarium\backtest")

def backtest_zigzag_falso_romp(filepath):
    try:
        df = pd.read_csv(filepath)
    except Exception:
        return None
        
    if len(df) < 500:
        return None
        
    df = df.sort_values(by='timestamp').reset_index(drop=True)
    
    # Indicadores
    df.ta.ema(length=50, append=True)
    df.ta.zigzag(deviation=0.5, backtest=True, append=True)
    
    try:
        ema_col = [c for c in df.columns if c.startswith("EMA_50")][0]
        # Pegar as colunas do zigzag geradas dinamicamente
        zig_v_col = [c for c in df.columns if c.startswith("ZIGZAGv_")][0]
        zig_d_col = [c for c in df.columns if c.startswith("ZIGZAGd_")][0]
    except IndexError:
        return None
        
    # Variáveis de Estado
    # state_top: 0=Procurando rompimento, 1=Rompimento de alta ocorreu, 2=Retornou para dentro (abaixo do topo)
    # state_bot: 0=Procurando rompimento, 1=Rompimento de baixa ocorreu, 2=Retornou para dentro (acima do fundo)
    
    current_top = None
    current_bot = None
    
    state_top = 0
    state_bot = 0
    
    wins_call = 0
    losses_call = 0
    wins_put = 0
    losses_put = 0
    
    # Para o loop de backtest, iteramos linha por linha
    for i in range(100, len(df) - 1):
        row = df.iloc[i]
        next_candle = df.iloc[i+1]
        
        # 1) Identificar Topo/Fundo
        # O pandas_ta zigzag (backtest=True) coloca o valor da perna na linha atual que confirmou
        zig_v = row[zig_v_col]
        zig_d = row[zig_d_col]
        
        if pd.notna(zig_v):
            if zig_d == 1.0 or zig_d == -1.0:
                # É um pivô. 
                # Vamos simplificar: se for maior que a EMA, consideramos um Topo. Ou podemos olhar o histórico próximo.
                # A forma correta: ZIGZAGd = 1 significa perna de alta (fundo para topo). Então o valor anterior foi um fundo.
                # Como o zigzag do pandas_ta funciona: ele marca ZIGZAGs_...
                # Vamos simplificar usando a máxima e mínima local: se zig_v é próximo do High, é topo. Se é próximo do Low, é fundo.
                if zig_v >= row['high'] * 0.999:
                    current_top = zig_v
                    state_top = 0 # Reset state
                elif zig_v <= row['low'] * 1.001:
                    current_bot = zig_v
                    state_bot = 0 # Reset state

        # Atualizações de estado do Topo
        if current_top is not None:
            if state_top == 0:
                # Aguarde o fechamento acima do topo
                if row['close'] > current_top:
                    state_top = 1
            elif state_top == 1:
                # Espere o retorno para dentro (fechar abaixo do topo)
                if row['close'] < current_top:
                    state_top = 2
            elif state_top == 2:
                # Confirme o falso rompimento: PUT com candle verde fechando abaixo do topo
                is_green = row['close'] > row['open']
                if is_green and row['close'] < current_top:
                    # Verifique a EMA50 contrária (Preço abaixo da EMA50 para PUT)
                    ema50 = row[ema_col]
                    if pd.notna(ema50) and row['close'] < ema50:
                        # ENTRADA DE PUT
                        if next_candle['close'] < next_candle['open']:
                            wins_put += 1
                        else:
                            losses_put += 1
                        state_top = 0 # Reset após trade
                        
        # Atualizações de estado do Fundo
        if current_bot is not None:
            if state_bot == 0:
                # Aguarde o fechamento abaixo do fundo
                if row['close'] < current_bot:
                    state_bot = 1
            elif state_bot == 1:
                # Espere o retorno para dentro (fechar acima do fundo)
                if row['close'] > current_bot:
                    state_bot = 2
            elif state_bot == 2:
                # Confirme o falso rompimento: CALL com candle vermelho fechando acima do fundo
                is_red = row['close'] < row['open']
                if is_red and row['close'] > current_bot:
                    # Verifique a EMA50 contrária (Preço acima da EMA50 para CALL)
                    ema50 = row[ema_col]
                    if pd.notna(ema50) and row['close'] > ema50:
                        # ENTRADA DE CALL
                        if next_candle['close'] > next_candle['open']:
                            wins_call += 1
                        else:
                            losses_call += 1
                        state_bot = 0 # Reset após trade
                        
    return {"cw": wins_call, "cl": losses_call, "pw": wins_put, "pl": losses_put}

def main():
    print("Iniciando backtest do Falso Rompimento com ZigZag Causal (0.50%)...")
    files = list(BACKTEST_DIR.glob("*.csv"))
    
    results = []
    total_w = 0
    total_l = 0
    
    for f in files:
        stats = backtest_zigzag_falso_romp(f)
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
    
    print("\n=== ESTATÍSTICAS GLOBAIS DO FALSO ROMPIMENTO ZIGZAG ===")
    total = total_w + total_l
    global_wr = (total_w / total) * 100 if total > 0 else 0
    print(f"Total de Entradas: {total}")
    print(f"Taxa de Acerto Global: {global_wr:.2f}%\n")
    
    print("=== PARES ANALISADOS ===")
    count = 0
    for par, wr, w, l, t in results:
        if t >= 5: # Filtro menor pois é um padrão hiper-específico
            print(f"{par:20} | Acerto: {wr:.2f}% | Entradas: {t} | W/L: {w}/{l}")
            count += 1
        if count >= 15:
            break

if __name__ == "__main__":
    main()
