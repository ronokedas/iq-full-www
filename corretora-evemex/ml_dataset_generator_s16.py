"""Gera o dataset de treinamento para o filtro de IA da Estratégia S16.

As features são calculadas na vela M5 fechada (sem data leakage), no momento
do sinal S16 (literal). O target é:
  - 1 se o sinal resultou em WIN (v4 fecha na direção esperada)
  - 0 se o sinal resultou em LOSS ou DOJI

A detecção usa a regra de nível único (cada região de preço só pode ser usada
uma vez) e cooldown de 10 velas, idêntico ao backtest validado.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import sys
from retrain_models import generate_dataset as generate_aligned_dataset

sys.path.append(str(Path(__file__).parent))


def pip_scale(close: float) -> float:
    return 1e-4 if close < 100 else 1e-2


def load_m5(symbol: str, data_dir: Path) -> pd.DataFrame:
    """Lê parquet M1 e agrega em candles M5."""
    df = pd.read_parquet(data_dir / f"{symbol}.parquet")
    if len(df) < 100:
        return pd.DataFrame()
    df = df.sort_values("from_ts").reset_index(drop=True)
    ts5 = (df["from_ts"] // 300) * 300
    m5 = df.groupby(ts5).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        from_ts=("from_ts", "last"),
    ).reset_index(drop=True)
    return m5


def calculate_features(m5: pd.DataFrame) -> pd.DataFrame:
    """Calcula features na vela M5 fechada (sem data leakage).

    Todas as features usam apenas dados disponíveis no fechamento da vela
    atual (shift para evitar olhar o futuro).
    """
    df = m5.copy()
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

    # 2. Inclinação da tendência (EMA9 - EMA21)
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    df["trend_slope"] = (ema9 - ema21) / ema21 * 100

    # 3. Sazonalidade (horário do dia)
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

    # 5. Suporte/Resistência (M15 = 3 velas M5, H1 = 12 velas M5)
    res_m15 = high.rolling(3).max()
    sup_m15 = low.rolling(3).min()
    res_h1 = high.rolling(12).max()
    sup_h1 = low.rolling(12).min()

    pip_scale_arr = np.where(close < 100, 1e-4, 1e-2)
    df["dist_res_m15"] = (res_m15 - close) / pip_scale_arr
    df["dist_sup_m15"] = (close - sup_m15) / pip_scale_arr
    df["dist_res_h1"] = (res_h1 - close) / pip_scale_arr
    df["dist_sup_h1"] = (close - sup_h1) / pip_scale_arr

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


def detect_s16_signals(m5: pd.DataFrame, tol_pips: float = 0.5, cooldown: int = 10) -> list[dict]:
    """Detecta sinais S16 literal com regra de nível único.

    Retorna lista de dicts com timestamp, direção e target.
    """
    signals: list[dict] = []
    last_ts = -10**18
    used_levels: list[float] = []

    for i in range(2, len(m5) - 1):
        v1, v2, v3, v4 = m5.iloc[i - 2], m5.iloc[i - 1], m5.iloc[i], m5.iloc[i + 1]
        scale = pip_scale(v1["close"])
        tol = scale * tol_pips
        nivel = v1["close"]

        # Regra de nível único
        region_tol = scale * 2.0
        if any(abs(nivel - used) <= region_tol for used in used_levels):
            continue

        # ---------- COMPRA ----------
        if v1["close"] < v1["open"] and v2["close"] > v2["open"] and abs(v2["open"] - nivel) <= tol:
            if v3["low"] <= nivel + scale:
                if v3["close"] < v3["open"]:  # LITERAL: v3 fecha vermelha
                    if v3["from_ts"] - last_ts >= cooldown * 300:
                        win = 1 if v4["close"] > v4["open"] else 0
                        signals.append({
                            "ts": v3["from_ts"], "dir": "CALL", "target": win,
                        })
                        last_ts = v3["from_ts"]
                        used_levels.append(nivel)

        # ---------- VENDA ----------
        if v1["close"] > v1["open"] and v2["close"] < v2["open"] and abs(v2["open"] - nivel) <= tol:
            if v3["high"] >= nivel - scale:
                if v3["close"] > v3["open"]:  # LITERAL: v3 fecha verde
                    if v3["from_ts"] - last_ts >= cooldown * 300:
                        win = 1 if v4["close"] < v4["open"] else 0
                        signals.append({
                            "ts": v3["from_ts"], "dir": "PUT", "target": win,
                        })
                        last_ts = v3["from_ts"]
                        used_levels.append(nivel)

    return signals


def generate_dataset() -> None:
    data_dir = Path("corretora-evemex/dados/m1")
    output_path = "corretora-evemex/ml_dataset_s16.csv"

    if not data_dir.exists():
        print(f"❌ Erro: Pasta {data_dir} não encontrada.")
        return

    all_samples: list[dict] = []
    files = sorted(data_dir.glob("*.parquet"))

    print(f"🚀 Iniciando processamento de {len(files)} arquivos...")

    for file in files:
        symbol = file.stem
        m5 = load_m5(symbol, data_dir)
        if m5.empty:
            continue

        # 1. Calcula features
        df_feat = calculate_features(m5)

        # 2. Detecta sinais S16 (literal, nível único, cooldown 10)
        signals = detect_s16_signals(m5)

        if not signals:
            continue

        # 3. Mapeia sinais para features
        df_feat_indexed = df_feat.set_index("from_ts")

        for sig in signals:
            ts = sig["ts"]
            if ts not in df_feat_indexed.index:
                continue
            feat_row = df_feat_indexed.loc[ts]
            if isinstance(feat_row, pd.DataFrame):
                feat_row = feat_row.iloc[0]

            sample = feat_row.to_dict()
            sample.update({
                "target": sig["target"],
                "direction": sig["dir"],
                "symbol": symbol,
            })
            all_samples.append(sample)

    if all_samples:
        dataset = pd.DataFrame(all_samples)
        dataset.to_csv(output_path, index=False)
        print(f"\n✅ Dataset S16 gerado com sucesso!")
        print(f"📊 Total de amostras: {len(dataset)}")
        print(f"🎯 Distribuição do Target:\n{dataset['target'].value_counts(normalize=True)}")
        print(f"📈 Sinais por direção:\n{dataset['direction'].value_counts()}")
    else:
        print("\n⚠️ Nenhum sinal S16 encontrado nos dados fornecidos.")


if __name__ == "__main__":
    generate_aligned_dataset("s16")
