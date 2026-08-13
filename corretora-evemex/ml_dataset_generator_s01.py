"""Gera o dataset de treinamento para o filtro de IA da Estratégia S01 (Três Velas Reversão).

As features calculadas aqui são IDÊNTICAS às da S13 (ml_dataset_generator_s13.py),
garantindo consistência na comparação justa entre estratégias. A diferença está
apenas na lógica de detecção do sinal (detect_s01_signals).
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys
from retrain_models import generate_dataset as generate_aligned_dataset

# Adiciona o diretório atual ao path
sys.path.append(str(Path(__file__).parent))


def calculate_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula as features espelhando exatamente o gerador da S13.

    Todas as features são calculadas na vela fechada (sem data leakage):
    usa apenas dados disponíveis no fechamento da vela atual.
    """
    df = df.copy()
    df = df.sort_values("from_ts").reset_index(drop=True)

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    open_ = df["open"].astype(float)

    # 1. Volatilidade recente
    tr = np.maximum(
        high - low,
        np.maximum(
            abs(high - close.shift(1)),
            abs(low - close.shift(1)),
        ),
    )
    df["atr_14"] = tr.rolling(14).mean()
    df["std_14"] = close.rolling(14).std()

    # 2. Inclinação da tendência
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    df["trend_slope"] = (ema9 - ema21) / ema21 * 100

    # 3. Sazonalidade
    dt = pd.to_datetime(df["from_ts"], unit="s")
    df["hour_sin"] = np.sin(2 * np.pi * dt.dt.hour / 24)
    df["hour_cos"] = np.cos(2 * np.pi * dt.dt.hour / 24)

    # 4. Corpos e pavios (últimos 5 candles)
    body_size = abs(close - open_)
    upper_wick = high - pd.concat([open_, close], axis=1).max(axis=1)
    lower_wick = pd.concat([open_, close], axis=1).min(axis=1) - low
    rg = high - low
    body_ratio = body_size / rg.replace(0, np.nan)
    upper_wick_ratio = upper_wick / rg.replace(0, np.nan)
    lower_wick_ratio = lower_wick / rg.replace(0, np.nan)

    df["avg_body_5"] = body_size.rolling(5).mean()
    df["avg_upper_wick_5"] = upper_wick.rolling(5).mean()
    df["avg_lower_wick_5"] = lower_wick.rolling(5).mean()
    df["avg_body_ratio_5"] = body_ratio.rolling(5).mean()
    df["avg_upper_wick_ratio_5"] = upper_wick_ratio.rolling(5).mean()
    df["avg_lower_wick_ratio_5"] = lower_wick_ratio.rolling(5).mean()

    # 5. Suporte/Resistência (H1 = 60 velas M1)
    res_h1 = high.rolling(60).max()
    sup_h1 = low.rolling(60).min()
    dist_res_h1 = res_h1 - close
    dist_sup_h1 = close - sup_h1

    # Normalização em pips (mesma lógica do bot)
    pip_scale = np.where(close < 100, 1e-4, 1e-2)
    df["dist_res_h1"] = dist_res_h1 / pip_scale
    df["dist_sup_h1"] = dist_sup_h1 / pip_scale

    # 6. RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi_14"] = 100 - (100 / (1 + rs))

    # 7. Momentum
    df["mom_3"] = close.pct_change(3) * 100
    df["mom_5"] = close.pct_change(5) * 100

    # 8. Distâncias normalizadas
    df["atr_pct"] = df["atr_14"] / close * 100
    df["dist_ema9"] = (close - ema9) / ema9 * 100
    df["dist_ema21"] = (close - ema21) / ema21 * 100

    # 9. Proporções da vela atual
    df["body_ratio"] = body_ratio
    df["upper_wick_ratio"] = upper_wick_ratio
    df["lower_wick_ratio"] = lower_wick_ratio

    return df


def detect_s01_signals(df: pd.DataFrame) -> list[dict]:
    """Detecta sinais da estratégia S01 - Três Velas Reversão.

    Lógica (conforme ESTRATEGIAS_DETALHADAS.md):
    1. V0: vela de cor OPOSTA à sequência OU um Doji (Close == Open).
    2. V1, V2, V3: três velas consecutivas da MESMA cor exata.
       Nenhuma das 3 velas pode ser Doji.
    3. CALL se V1,V2,V3 forem VERMELHAS (após V0 Verde ou Doji).
       PUT se V1,V2,V3 forem VERDES (após V0 Vermelha ou Doji).
    4. O padrão é confirmado no fechamento de V3. Sinal timestamp = from_ts de V3.

    Expiração: 60s (próxima vela M1).
    """
    signals: list[dict] = []

    # Precisamos de V0, V1, V2, V3 para o sinal + 1 vela futura para o resultado
    for i in range(4, len(df) - 1):
        v0 = df.iloc[i - 4]
        v1 = df.iloc[i - 3]
        v2 = df.iloc[i - 2]
        v3 = df.iloc[i - 1]

        # Vela de resultado (expiração de 1m)
        v_result = df.iloc[i + 1]

        # Helper: é Doji?
        def is_doji(v):
            return abs(v["close"] - v["open"]) < 1e-12

        # Nenhuma das 3 velas pode ser Doji
        if is_doji(v1) or is_doji(v2) or is_doji(v3):
            continue

        c1 = v1["close"] > v1["open"]  # v1 verde
        c2 = v2["close"] > v2["open"]  # v2 verde
        c3 = v3["close"] > v3["open"]  # v3 verde

        # Verifica se as 3 velas são da mesma cor
        if not (c1 == c2 == c3):
            continue

        if c1:  # Todas VERDES -> Padrão de reversão de baixa (PUT)
            # V0 deve ser Vermelha ou Doji
            v0_vermelha = v0["close"] < v0["open"]
            v0_doji = is_doji(v0)
            if not (v0_vermelha or v0_doji):
                continue

            # Sinal de PUT: espera reversão para baixo
            target = 1 if v_result["close"] < v_result["open"] else 0
            signals.append({
                "timestamp": v3["from_ts"],
                "direction": "PUT",
                "target": target,
            })

        else:  # Todas VERMELHAS -> Padrão de reversão de alta (CALL)
            # V0 deve ser Verde ou Doji
            v0_verde = v0["close"] > v0["open"]
            v0_doji = is_doji(v0)
            if not (v0_verde or v0_doji):
                continue

            # Sinal de CALL: espera reversão para cima
            target = 1 if v_result["close"] > v_result["open"] else 0
            signals.append({
                "timestamp": v3["from_ts"],
                "direction": "CALL",
                "target": target,
            })

    return signals


def generate_dataset() -> None:
    data_dir = Path("corretora-evemex/dados/m1")
    output_path = "corretora-evemex/ml_dataset_s01.csv"

    if not data_dir.exists():
        print(f"❌ Erro: Pasta {data_dir} não encontrada.")
        return

    all_samples: list[dict] = []
    files = list(data_dir.glob("*.parquet"))

    print(f"🚀 Iniciando processamento de {len(files)} arquivos (S01 - Três Velas Reversão)...")

    for file in files:
        symbol = file.stem
        print(f"📈 Processando {symbol}...")

        df = pd.read_parquet(file)
        if len(df) < 100:
            continue

        # 1. Calcula Features (mesmas do gerador da S13)
        df_feat = calculate_features(df)

        # 2. Detecta Sinais S01
        s01_signals = detect_s01_signals(df)

        if not s01_signals:
            continue

        # 3. Mapeia Sinais para Features
        df_feat_indexed = df_feat.set_index("from_ts")

        for signal in s01_signals:
            ts = signal["timestamp"]
            if ts not in df_feat_indexed.index:
                continue
            feat_row = df_feat_indexed.loc[ts]
            if isinstance(feat_row, pd.DataFrame):
                feat_row = feat_row.iloc[0]

            sample = feat_row.to_dict()
            sample.update({
                "target": signal["target"],
                "direction": signal["direction"],
                "symbol": symbol,
            })
            all_samples.append(sample)

    if all_samples:
        dataset = pd.DataFrame(all_samples)
        dataset.to_csv(output_path, index=False)
        print(f"\n✅ Dataset S01 gerado com sucesso!")
        print(f"📊 Total de amostras: {len(dataset)}")
        print(f"🎯 Distribuição do Target:\n{dataset['target'].value_counts(normalize=True)}")
    else:
        print("\n⚠️ Nenhum sinal S01 encontrado nos dados fornecidos.")


if __name__ == "__main__":
    generate_aligned_dataset("s01")
