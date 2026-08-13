"""Backtest Estratégia 17 — Pavil de Vela / Reversão Time (M5) com Bandas de Bollinger 14/2.

Regras:
- Bandas de Bollinger com 14 períodos e 2 desvios-padrão no gráfico M5.
- A verificação ocorre no fechamento da vela H1, ou seja, no último candle M5 da hora:
  candles M5 que iniciam às HH:55 (horário UTC) — por padrão HH em {10, 11, 12, 13}.
- Se esse candle M5 fechar IGUAL ou ACIMA da banda superior  -> sinal VENDA (DOWN).
  Se fechar ABAIXO da banda inferior                      -> sinal COMPRA (UP).
- A vitória é medida na próxima vela M5 (primeira vela da hora seguinte):
  DOWN vence se a vela seguinte fechar abaixo do preço de entrada;
  UP   vence se a vela seguinte fechar acima do preço de entrada.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "dados" / "m1"

# Horas (UTC) dos fechamentos de H1 verificados: candles M5 iniciando às HH:55
DEFAULT_HOURS_UTC = (10, 11, 12, 13)


def load_m1(symbol: str, path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if "from_ts" not in df.columns:
        raise ValueError(f"{path.name}: coluna 'from_ts' ausente")
    df = df[["from_ts", "open", "high", "low", "close"]].copy()
    df["symbol"] = symbol
    df = df.dropna().sort_values("from_ts").drop_duplicates("from_ts")
    return df


def resample_m5(m1: pd.DataFrame) -> pd.DataFrame:
    """Agrega candles 1m em 5m alinhados ao epoch (fechamentos às HH:00/HH:05/...)."""
    m1 = m1.copy()
    m1["bucket"] = (m1["from_ts"] // 300) * 300
    symbol = m1["symbol"].iloc[0] if "symbol" in m1.columns else ""
    agg = (
        m1.groupby("bucket", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
        )
        .reset_index()
    )
    agg.rename(columns={"bucket": "from_ts"}, inplace=True)
    agg["to_ts"] = agg["from_ts"] + 300
    agg["symbol"] = symbol
    return agg


def bollinger(close: pd.Series, period: int = 14, num_std: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    return pd.DataFrame(
        {
            "bb_mid": mid,
            "bb_upper": mid + num_std * std,
            "bb_lower": mid - num_std * std,
        }
    )


def generate_signals(
    m5: pd.DataFrame, hours_utc: tuple[int, ...], mode: str = "hh55"
) -> pd.DataFrame:
    df = m5.copy()
    df["dt"] = pd.to_datetime(df["from_ts"], unit="s", utc=True)
    df["hour_utc"] = df["dt"].dt.hour
    df["minute_utc"] = df["dt"].dt.minute
    df["is_green"] = df["close"] > df["open"]
    df["is_red"] = df["close"] < df["open"]

    bb = bollinger(df["close"], period=14, num_std=2.0)
    df["bb_upper"] = bb["bb_upper"]
    df["bb_lower"] = bb["bb_lower"]

    # Vela seguinte
    df["next_close"] = df["close"].shift(-1)
    df["next_open"] = df["open"].shift(-1)
    df["next_from"] = df["from_ts"].shift(-1)

    # Candle M5 avaliado: HH:55 (fechamento da H1 anterior) ou HH:00 (hora cheia)
    minute_target = 55 if mode == "hh55" else 0
    is_target = (df["minute_utc"] == minute_target) & (df["hour_utc"].isin(hours_utc))
    df["candidate"] = is_target & df["bb_upper"].notna() & df["bb_lower"].notna()

    # Sinais conforme regras
    if mode == "hh55":
        # Regra original: fecha igual/acima da banda superior -> DOWN; abaixo da banda inferior -> UP
        df["signal"] = np.where(
            df["candidate"] & (df["close"] >= df["bb_upper"]),
            "DOWN",
            np.where(df["candidate"] & (df["close"] < df["bb_lower"]), "UP", None),
        )
    else:
        # Modo hora cheia (hh00): vela VERDE tocando a banda superior -> DOWN (reversão);
        # vela VERMELHA tocando a banda inferior -> UP (reversão)
        df["signal"] = np.where(
            df["candidate"] & df["is_green"] & (df["close"] >= df["bb_upper"]),
            "DOWN",
            np.where(
                df["candidate"] & df["is_red"] & (df["close"] <= df["bb_lower"]),
                "UP",
                None,
            ),
        )

    # Resultado na próxima vela M5
    entry = df["close"]
    df["win"] = np.where(
        df["signal"] == "DOWN",
        df["next_close"] < entry,
        np.where(df["signal"] == "UP", df["next_close"] > entry, np.nan),
    )
    df["next_is_red"] = df["next_close"] < df["next_open"]

    has_next = df["next_close"].notna()
    out = df[df["signal"].notna() & has_next].copy()
    out["entry_price"] = entry[out.index]
    return out


def summarize(signals: pd.DataFrame, payout: float) -> dict[str, float | int]:
    if signals.empty:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "winrate": 0.0,
            "profit": 0.0,
            "profit_factor": 0.0,
    }
    total = len(signals)
    wins = int(signals["win"].sum())
    losses = total - wins
    winrate = wins / total * 100.0
    profit = wins * payout - losses
    pf = (wins * payout) / losses if losses else float("inf")
    return {
        "trades": total,
        "wins": wins,
        "losses": losses,
        "winrate": round(winrate, 2),
        "profit": round(profit, 2),
        "profit_factor": round(pf, 2) if losses else float("inf"),
    }


def run_backtest(
    hours_utc: tuple[int, ...],
    payout: float,
    mode: str = "hh55",
    min_m5: int = 300,
) -> None:
    files = sorted(DATA_DIR.glob("*_otc.parquet"))
    if not files:
        print(f"Nenhum parquet em {DATA_DIR}", file=sys.stderr)
        sys.exit(1)

    all_signals: list[pd.DataFrame] = []
    print(f"Carregando {len(files)} ativos de {DATA_DIR} ...")
    for path in files:
        symbol = path.stem
        try:
            m1 = load_m1(symbol, path)
        except Exception as exc:
            print(f"  [skip] {symbol}: {exc}")
            continue
        if len(m1) < min_m5 * 5:
            print(f"  [skip] {symbol}: apenas {len(m1)} candles 1m")
            continue
        m5 = resample_m5(m1)
        if len(m5) < 30:
            continue
        signals = generate_signals(m5, hours_utc, mode)
        if not signals.empty:
            all_signals.append(signals)
        print(
            f"  {symbol}: {len(m1):>6} candles 1m -> {len(m5):>6} M5 | "
            f"sinais={len(signals)}"
        )

    if not all_signals:
        print("Nenhum sinal gerado.")
        return

    merged = pd.concat(all_signals, ignore_index=True)

    print("\n" + "=" * 72)
    print(f"ESTRATÉGIA 17 — PAVIL DE VELA / REVERSÃO TIME (M5) — BOLLINGER 14/2")
    if mode == "hh55":
        print(f"Modo HH:55 — candles M5 iniciando às {sorted(hours_utc)}h: "
              f"fecha >= banda sup -> DOWN; fecha < banda inf -> UP")
    else:
        print(f"Modo HH:00 (hora cheia) — candles M5 iniciando às {sorted(hours_utc)}h: "
              f"vela VERDE tocando banda sup -> DOWN; vela VERMELHA tocando banda inf -> UP")
    print(f"Payout: {payout*100:.0f}% | Período: "
          f"{datetime.fromtimestamp(merged['from_ts'].min(), tz=timezone.utc):%d/%m/%Y %H:%M} — "
          f"{datetime.fromtimestamp(merged['from_ts'].max(), tz=timezone.utc):%d/%m/%Y %H:%M} UTC")
    print("=" * 72)

    total = summarize(merged, payout)
    down = summarize(merged[merged["signal"] == "DOWN"], payout)
    up = summarize(merged[merged["signal"] == "UP"], payout)

    def row(name: str, s: dict[str, float | int]) -> str:
        pf = f"{s['profit_factor']:.2f}" if s["profit_factor"] != float("inf") else "∞"
        return (
            f"{name:<22} | {s['trades']:>5} | {s['wins']:>4} | {s['losses']:>6} | "
            f"{s['winrate']:>6.2f}% | R$ {s['profit']:>9.2f} | {pf:>7}"
        )

    print(f"{'Métrica':<22} | {'Ops':>5} | {'WIN':>4} | {'LOSS':>6} | {'Acerto':>7} | {'Lucro':>10} | {'PF':>7}")
    print("-" * 72)
    print(row("TOTAL", total))
    print(row("VENDA (DOWN)", down))
    print(row("COMPRA (UP)", up))
    print("-" * 72)

    # Acerto separado por condição de toque exato na banda
    touch_upper = merged[merged["close"] == merged["bb_upper"]]
    touch_lower = merged[merged["close"] == merged["bb_lower"]]
    below_upper = merged[(merged["close"] > merged["bb_upper"])]
    below_lower = merged[(merged["close"] < merged["bb_lower"]) & (merged["signal"] == "UP")]
    print(f"Toques exatos na banda superior (close == banda):  {len(touch_upper)}")
    print(f"Toques exatos na banda inferior (close == banda):  {len(touch_lower)}")
    print(f"Fechamentos ACIMA da banda superior:               {len(below_upper)}")
    print(f"Fechamentos ABAIXO da banda inferior:              {len(below_lower)}")

    # Cor da vela seguinte (contexto "se vermelha")
    red = merged[merged["next_is_red"]]
    green = merged[~merged["next_is_red"]]
    print(f"\nVela seguinte VERMELHA: {len(red)} ({len(red)/len(merged)*100:.1f}%) | "
          f"VERDE: {len(green)} ({len(green)/len(merged)*100:.1f}%)")

    # Por símbolo (top 15 por volume de sinais)
    print("\nPor ativo (ordenado por nº de sinais):")
    print(f"{'Ativo':<20} | {'Ops':>5} | {'WIN':>4} | {'LOSS':>6} | {'Acerto':>7} | {'Lucro':>10} | {'PF':>7}")
    print("-" * 64)
    per_symbol = []
    for symbol, group in merged.groupby("symbol"):
        summary = summarize(group, payout)
        summary["symbol"] = symbol
        per_symbol.append(summary)
    per_symbol.sort(key=lambda item: item["trades"], reverse=True)
    for item in per_symbol[:15]:
        print(row(f"{item['symbol']}", item))

    # Distribuição por horário UTC
    merged["hour_utc"] = (
        pd.to_datetime(merged["from_ts"], unit="s", utc=True).dt.tz_convert("UTC").dt.hour
    )
    print("\nPor horário de fechamento H1 (UTC):")
    print(f"{'Hora':<8} | {'Ops':>5} | {'WIN':>4} | {'LOSS':>6} | {'Acerto':>7} | {'Lucro':>10} | {'PF':>7}")
    print("-" * 60)
    for hour, group in merged.groupby("hour_utc"):
        print(row(f"{hour:02d}:55", summarize(group, payout)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours", type=int, nargs="+", default=list(DEFAULT_HOURS_UTC),
        help="Horas UTC dos fechamentos H1 avaliados (padrão: 10 11 12 13)",
    )
    parser.add_argument("--payout", type=float, default=0.85, help="payout (padrão 0.85)")
    parser.add_argument(
        "--mode", choices=["hh55", "hh00"], default="hh55",
        help="hh55: candle M5 às HH:55 (original) | hh00: candle M5 da hora cheia (com cor da vela)",
    )
    args = parser.parse_args()

    hours = tuple(sorted(set(args.hours)))
    for hour in hours:
        if not 0 <= hour <= 23:
            print(f"Hora inválida: {hour}", file=sys.stderr)
            return 2

    run_backtest(hours, args.payout, args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())