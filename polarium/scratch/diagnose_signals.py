"""
Script de diagnostico: Simula exatamente o que o bot faz com dados reais de CSV.
"""
import sys, traceback
sys.stdout.reconfigure(errors='replace')
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

class FakeCandle:
    def __init__(self, row):
        self.from_ts = int(row['timestamp'])
        self.open = float(row['open'])
        self.high = float(row['high'])
        self.low = float(row['low'])
        self.close = float(row['close'])
        self.symbol = ""
        self.timeframe = "1m"
        self.volume = 0.0
        self.tick_count = 0
        self.to_ts = self.from_ts + 60

BACKTEST_DIR = Path(r"C:\iq-full-www\polarium\backtest")

print("=" * 60)
print("DIAGNOSTICO: ESTRATEGIAS VS DADOS REAIS")
print("=" * 60)

test_pairs = ["CADCHF-OTC", "FLOKIUSD-OTC", "USDCAD-OTC", "USOUSD-OTC"]

for pair_name in test_pairs:
    csv_file = BACKTEST_DIR / f"{pair_name}_M1_7days.csv"
    if not csv_file.exists():
        print(f"\nArquivo nao encontrado: {csv_file.name}")
        continue
    
    df = pd.read_csv(csv_file).sort_values('timestamp').reset_index(drop=True)
    print(f"\nTestando {pair_name} ({len(df)} velas)...")
    print(f"  Colunas CSV: {list(df.columns)}")
    
    candles = [FakeCandle(df.iloc[i]) for i in range(min(200, len(df)))]
    entry_bucket = int(candles[-1].from_ts)
    symbol_otc = pair_name.lower().replace("-", "_")
    
    print(f"  Simbolo formato Polarium: {symbol_otc}")
    
    try:
        from strategy_sniper_m1 import detect_latest as sniper
        signals = sniper(candles, symbol_otc, entry_bucket)
        print(f"  Sniper M1: {len(signals)} sinais")
        if signals: print(f"    -> {signals[0]}")
    except Exception as e:
        print(f"  Sniper M1 ERRO: {e}")
        traceback.print_exc()
    
    try:
        from strategy_smc_m1 import detect_latest as smc1
        signals = smc1(candles, symbol_otc, entry_bucket)
        print(f"  SMC M1: {len(signals)} sinais")
        if signals: print(f"    -> {signals[0]}")
    except Exception as e:
        print(f"  SMC M1 ERRO: {e}")
        traceback.print_exc()
    
    try:
        from strategy_smc_m2 import detect_latest as smc2
        signals = smc2(candles, symbol_otc, entry_bucket)
        print(f"  SMC M2: {len(signals)} sinais")
        if signals: print(f"    -> {signals[0]}")
    except Exception as e:
        print(f"  SMC M2 ERRO: {e}")
        traceback.print_exc()

# Contagem total na semana inteira para CADCHF
print("\n" + "=" * 60)
print("CONTAGEM TOTAL DE SINAIS - SEMANA INTEIRA (CADCHF-OTC)")
print("=" * 60)

csv_file = BACKTEST_DIR / "CADCHF-OTC_M1_7days.csv"
if csv_file.exists():
    df = pd.read_csv(csv_file).sort_values('timestamp').reset_index(drop=True)
    candles_all = [FakeCandle(df.iloc[i]) for i in range(len(df))]

    from strategy_sniper_m1 import detect_latest as sniper
    from strategy_smc_m1 import detect_latest as smc1
    from strategy_smc_m2 import detect_latest as smc2

    sniper_count = smc1_count = smc2_count = 0
    for i in range(60, len(candles_all)-1):
        entry = int(candles_all[i].from_ts)
        h = candles_all[:i+1]
        try: sniper_count += len(sniper(h, "cadchf_otc", entry))
        except: pass
        try: smc1_count += len(smc1(h, "cadchf_otc", entry))
        except: pass
        try: smc2_count += len(smc2(h, "cadchf_otc", entry))
        except: pass
    
    print(f"Sniper M1 : {sniper_count}")
    print(f"SMC M1    : {smc1_count}")
    print(f"SMC M2    : {smc2_count}")
    total = sniper_count + smc1_count + smc2_count
    print(f"Total 7d  : {total} sinais | Media/dia: {total/7:.1f}")
