"""Validação rápida do bot unificado."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import joblib
import unified_ai_bot

# 1. Verifica modelos
for s in ["s01", "s13", "s16", "s5_m5"]:
    path = Path(__file__).parent / f"signal_filter_{s}.pkl"
    if path.exists():
        data = joblib.load(path)
        print(f"✅ Modelo {s.upper()}: {len(data['features'])} features")
    else:
        print(f"❌ Modelo {s.upper()} NÃO encontrado")

# 2. Testa detectores com dados sintéticos
from evemexapi import Candle


def make_candle(open_, close, high, low, ts):
    return Candle(symbol="TESTE_otc", timeframe="1m", from_ts=ts, to_ts=ts,
                  open=open_, close=close, high=high, low=low)


# S01: 3 velas verdes + 1 vermelha antes -> PUT
candles_s01 = [
    make_candle(1.0, 0.9, 1.05, 0.85, 100),   # v0 vermelha
    make_candle(0.9, 1.0, 1.05, 0.88, 200),   # v1 verde
    make_candle(1.0, 1.1, 1.15, 0.98, 300),   # v2 verde
    make_candle(1.1, 1.2, 1.25, 1.08, 400),   # v3 verde
]
print(f"\nS01 detectado: {unified_ai_bot.detect_s01(candles_s01)} (esperado: DOWN)")

# S13: primeira vela verde possui pavio superior; as próximas duas fecham abaixo da máxima -> PUT
candles_s13 = [
    make_candle(1.0, 1.1, 1.20, 0.98, 100),
    make_candle(1.08, 1.12, 1.15, 1.05, 200),
    make_candle(1.10, 1.14, 1.17, 1.07, 300),
]
print(f"S13 detectado: {unified_ai_bot.detect_s13(candles_s13)} (esperado: DOWN)")

# S16: Fundo duplo -> CALL
# 16 buckets M5 = 80 candles M1 de 60s (timestamps 0..4740)
# Padrão (últimos 4 M5):
#   v1 = vermelho (fundo em 0.9990)
#   v2 = verde    (reversão: open = fundo 0.9990)
#   v3 = vermelho (testa fundo: low <= 0.9991 e close < open)
# Scale = 1e-4 (preço < 100), tol = 0.5e-4
M5_BUCKETS = 16
M1_PER_M5 = 5
M1_INTERVAL = 60


def m1_for(o, c, h, l):
    return (o, c, h, l)


# Preenche os primeiros 12 buckets com candles neutros (pequenos corpos)
seq = []
for bucket in range(M5_BUCKETS - 4):
    base_o = 1.0000 + bucket * 0.0001
    for i in range(M1_PER_M5):
        seq.append(m1_for(base_o, base_o + 0.0002, base_o + 0.0005, base_o - 0.0003))

# v1 (bucket 12): vermelho, fundo em 0.9990
for i in range(M1_PER_M5):
    seq.append(m1_for(1.0000, 0.9990, 1.0005, 0.9985))

# v2 (bucket 13): verde, reversão exata no fundo
for i in range(M1_PER_M5):
    seq.append(m1_for(0.9990, 1.0000, 1.0005, 0.9985))

# v3 (bucket 14): vermelho, testa o fundo e fecha abaixo
for i in range(M1_PER_M5):
    seq.append(m1_for(1.0000, 0.9994, 1.0005, 0.9990))

candles_s16 = [
    make_candle(*ohlc, ts=i * M1_INTERVAL)
    for i, ohlc in enumerate(seq)
]

m5 = unified_ai_bot.aggregate_m5(candles_s16)
print(f"S16 detectado: {unified_ai_bot.detect_s16(m5)} (esperado: UP)")

# 3. Testa FeatureBuilder
history_m1 = [
    make_candle(1.0, 1.1, 1.2, 0.9, index * M1_INTERVAL)
    for index in range(60)
]
feats_m1 = unified_ai_bot.FeatureBuilder.build_m1(history_m1)
print(f"\nFeatures M1: {len(feats_m1) if feats_m1 else 'None'}")

feats_m5 = unified_ai_bot.FeatureBuilder.build_m5(m5)
print(f"Features M5: {len(feats_m5) if feats_m5 else 'None'}")

print("\n✅ Validação concluída com sucesso!")
