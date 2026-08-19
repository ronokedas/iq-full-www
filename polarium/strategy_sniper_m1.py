"""
Estratégia Medalha de Prata: Robô Sniper M1 (Exaustão BB + RSI).
Timeframe Analisado: M1
Timeframe Expiração: M1 (60 segundos)
"""
import pandas as pd
import pandas_ta as ta

STRATEGY_ID = "sniper_m1"
STRATEGY_LABEL = "Sniper Bollinger + RSI M1"

def detect_latest(history: list, symbol: str, entry_bucket: int) -> list[dict]:
    if len(history) < 30:
        return []
        
    df = pd.DataFrame([
        {'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close}
        for c in history
    ])
    
    # Calcular Indicadores M1
    df.ta.rsi(length=14, append=True)
    df.ta.bbands(length=20, std=2.0, append=True)
    
    try:
        rsi_col = [c for c in df.columns if c.startswith("RSI_14")][0]
        bbl_col = [c for c in df.columns if c.startswith("BBL_20")][0]
        bbu_col = [c for c in df.columns if c.startswith("BBU_20")][0]
    except IndexError:
        return []
        
    v_atual = df.iloc[-1]
    
    rsi = v_atual[rsi_col]
    bbl = v_atual[bbl_col]
    bbu = v_atual[bbu_col]
    close_price = v_atual['close']
    open_price = v_atual['open']
    
    if pd.isna(rsi) or pd.isna(bbl):
        return []
        
    signals = []
    
    # Condição Sniper: Velas expressivas saindo da banda
    body_size = abs(close_price - open_price)
    avg_body = df['close'].diff().abs().mean()
    is_expressive = body_size > (avg_body * 1.5)
    
    # SETUP CALL (Mercado Derreteu)
    if rsi < 25 and close_price < bbl and is_expressive and close_price < open_price:
        signals.append({
            "strategy": STRATEGY_LABEL,
            "strategy_id": STRATEGY_ID,
            "symbol": symbol,
            "direction": "CALL",
            "entry_from_ts": entry_bucket,
            "expiration_tf_sec": 60,
            "approved": True
        })
        
    # SETUP PUT (Mercado Explodiu)
    elif rsi > 75 and close_price > bbu and is_expressive and close_price > open_price:
        signals.append({
            "strategy": STRATEGY_LABEL,
            "strategy_id": STRATEGY_ID,
            "symbol": symbol,
            "direction": "PUT",
            "entry_from_ts": entry_bucket,
            "expiration_tf_sec": 60,
            "approved": True
        })
        
    return signals
