"""Análise final FX + cor da vela atual — margem, hora e direção."""
import pandas as pd
import numpy as np
from analise_final import load_all, base_signals, summarize, PAYOUT

FX_PREFIXES = ("EUR", "GBP", "USD", "AUD", "NZD", "CAD", "CHF", "JPY")


def main():
    frames = load_all()
    all_sig = []
    for m1 in frames:
        sig = base_signals(m1)
        if not sig.empty:
            all_sig.append(sig)
    merged = pd.concat(all_sig, ignore_index=True)
    merged["is_fx"] = merged["symbol"].str.startswith(FX_PREFIXES)
    cor = ((merged["signal"] == "DOWN") & merged["cur_green"]) | (
        (merged["signal"] == "UP") & merged["cur_red"]
    )
    merged["margem"] = np.where(
        merged["signal"] == "DOWN", merged["margem_up"], merged["margem_lo"]
    )

    print("=== FX + cor vela atual + margem ===")
    for limiar in [0.0, 0.01, 0.02, 0.05, 0.1]:
        sub = merged[cor & merged["is_fx"] & (merged["margem"] >= limiar)]
        s = summarize(sub, PAYOUT)
        print(f"  margem >= {limiar}%: ops={s['trades']} acerto={s['winrate']}% lucro=R${s['profit']}")

    print("\n=== FX + cor, por hora ===")
    for hora in sorted(merged["hour"].unique()):
        sub = merged[cor & merged["is_fx"] & (merged["hour"] == hora)]
        s = summarize(sub, PAYOUT)
        print(f"  {hora}:55 -> ops={s['trades']} acerto={s['winrate']}% lucro=R${s['profit']}")

    print("\n=== FX + cor, por direção ===")
    for d in ["DOWN", "UP"]:
        sub = merged[cor & merged["is_fx"] & (merged["signal"] == d)]
        s = summarize(sub, PAYOUT)
        print(f"  {d}: ops={s['trades']} acerto={s['winrate']}% lucro=R${s['profit']}")

    print("\n=== FX + cor, por ativo ===")
    rows = []
    for symbol, group in merged[cor & merged["is_fx"]].groupby("symbol"):
        s = summarize(group, PAYOUT)
        rows.append((symbol, s))
    rows.sort(key=lambda x: x[1]["winrate"], reverse=True)
    for symbol, s in rows:
        print(f"  {symbol:<20} ops={s['trades']:<4} acerto={s['winrate']:>6.2f}% lucro=R${s['profit']:>7.2f}")


if __name__ == "__main__":
    main()