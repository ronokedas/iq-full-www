"""
Estratégia Medalha de Bronze: SMC Institucional (FVG + EMA + Momentum) M1.
Timeframe Analisado: M1
Timeframe Expiração: M1 (60 segundos)
"""
import pandas as pd
import pandas_ta as ta

STRATEGY_ID = "smc_m1"
STRATEGY_LABEL = "SMC FVG Institucional M1"

def detect_latest(history: list, symbol: str, entry_bucket: int) -> list[dict]:
    if len(history) < 30:
        return []
        
    df = pd.DataFrame([
        {'open': c.open, 'high': c.high, 'low': c.low, 'close': c.close}
        for c in history
    ])
    
    df.ta.ema(length=3, append=True)
    df.ta.ema(length=8, append=True)
    df.ta.mom(length=10, append=True)
    
    try:
        ema3_col = [c for c in df.columns if c.startswith("EMA_3")][0]
        ema8_col = [c for c in df.columns if c.startswith("EMA_8")][0]
        mom_col = [c for c in df.columns if c.startswith("MOM_10")][0]
    except IndexError:
        return []
        
    v4 = df.iloc[-1]
    v3 = df.iloc[-2]
    v2 = df.iloc[-3]
    v1 = df.iloc[-4]
    
    ema3 = v4[ema3_col]
    ema8 = v4[ema8_col]
    mom = v4[mom_col]
    
    if pd.isna(ema3) or pd.isna(ema8) or pd.isna(mom):
        return []
        
    signals = []
    
    # SETUP CALL
    v1_red = v1['close'] < v1['open']
    v2_green = v2['close'] > v2['open']
    v3_green = v3['close'] > v3['open']
    
    if v1_red and v2_green and v3_green:
        if v2['close'] > v1['high'] and v3['close'] > v2['high']:
            if v3['low'] > v1['high']: # FVG ALTA
                if v4['low'] <= v1['high'] and v4['high'] >= v1['high']: 
                    if mom > 0 and ema3 > ema8:
                        signals.append({
                            "strategy": STRATEGY_LABEL,
                            "strategy_id": STRATEGY_ID,
                            "symbol": symbol,
                            "direction": "CALL",
                            "entry_from_ts": entry_bucket,
                            "expiration_tf_sec": 60, # EXPIRAÇÃO M1
                            "approved": True
                        })
                        
    # SETUP PUT
    v1_green = v1['close'] > v1['open']
    v2_red = v2['close'] < v2['open']
    v3_red = v3['close'] < v3['open']
    
    if v1_green and v2_red and v3_red:
        if v2['close'] < v1['low'] and v3['close'] < v2['low']:
            if v3['high'] < v1['low']: # FVG BAIXA
                if v4['high'] >= v1['low'] and v4['low'] <= v1['low']: 
                    if mom < 0 and ema3 < ema8:
                        signals.append({
                            "strategy": STRATEGY_LABEL,
                            "strategy_id": STRATEGY_ID,
                            "symbol": symbol,
                            "direction": "PUT",
                            "entry_from_ts": entry_bucket,
                            "expiration_tf_sec": 60, # EXPIRAÇÃO M1
                            "approved": True
                        })
                        
    return signals
