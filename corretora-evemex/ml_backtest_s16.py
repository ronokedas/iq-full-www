"""
Backtest da Estratégia S16 - Fundo/Topo Duplo (M5)

Regra literal (usuário):
  COMPRA:
    v1: vela VERMELHA
    v2: vela VERDE que nasce no close da v1 (tolerância pip)
    v3: vela que TOCA o nível (close v1 = open v2) e FECHA VERMELHA
    v4: na vela seguinte entramos CALL; expiração = 1 vela M5 (5 min)
    WIN se v4 fechar verde
  VENDA: inverso lógico

Também testa a variação clássica (v3 fecha VERDE para compra = teste duplo do suporte
com fechamento acima), para comparação.
"""
import pandas as pd
import numpy as np
from pathlib import Path

PAYOUT = 0.85
BET = 10.0


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


def detect_dual(m5: pd.DataFrame, tol_pips: float, cooldown: int = 5, unique_level: bool = True) -> list[dict]:
    """Detecção literal da S16 e variação clássica.

    cooldown: número de velas M5 que devem passar entre sinais do mesmo ativo
    para evitar sobreposição (mesmo resultado contado múltiplas vezes).

    unique_level: se True, cada região de preço (nível) só pode ser usada UMA vez.
    Depois que o preço toca o nível e gera um sinal, aquele nível não é mais
    válido para novos sinais (mesmo que o preço volte a tocá-lo).
    """
    signals: list[dict] = []
    last_ts = -10**18
    used_levels: list[float] = []  # níveis já usados (regiões de preço)
    for i in range(2, len(m5) - 1):
        v1, v2, v3, v4 = m5.iloc[i - 2], m5.iloc[i - 1], m5.iloc[i], m5.iloc[i + 1]
        scale = pip_scale(v1["close"])
        tol = scale * tol_pips
        nivel = v1["close"]

        # Se unique_level, verifica se este nível já foi usado (região de preço)
        if unique_level:
            region_tol = scale * 2.0  # faixa de ±2 pips = mesma região
            if any(abs(nivel - used) <= region_tol for used in used_levels):
                continue

        # ---------- COMPRA ----------
        if v1["close"] < v1["open"] and v2["close"] > v2["open"] and abs(v2["open"] - nivel) <= tol:
            # v3 toca o nível
            if v3["low"] <= nivel + scale:  # +0.5 pip de folga
                # LITERAL: v3 fecha vermelha
                if v3["close"] < v3["open"]:
                    if v3["from_ts"] - last_ts >= cooldown * 300:
                        win = 1 if v4["close"] > v4["open"] else 0
                        signals.append({
                            "ts": v3["from_ts"], "dir": "CALL", "variant": "literal", "win": win,
                        })
                        last_ts = v3["from_ts"]
                        used_levels.append(nivel)
                # CLÁSSICA: v3 fecha verde (martelo) — só se não entrou como literal
                elif v3["close"] > v3["open"]:
                    if v3["from_ts"] - last_ts >= cooldown * 300:
                        win = 1 if v4["close"] > v4["open"] else 0
                        signals.append({
                            "ts": v3["from_ts"], "dir": "CALL", "variant": "classic", "win": win,
                        })
                        last_ts = v3["from_ts"]
                        used_levels.append(nivel)

        # ---------- VENDA ----------
        if v1["close"] > v1["open"] and v2["close"] < v2["open"] and abs(v2["open"] - nivel) <= tol:
            if v3["high"] >= nivel - scale:
                if v3["close"] > v3["open"]:
                    if v3["from_ts"] - last_ts >= cooldown * 300:
                        win = 1 if v4["close"] < v4["open"] else 0
                        signals.append({
                            "ts": v3["from_ts"], "dir": "PUT", "variant": "literal", "win": win,
                        })
                        last_ts = v3["from_ts"]
                        used_levels.append(nivel)
                elif v3["close"] < v3["open"]:
                    if v3["from_ts"] - last_ts >= cooldown * 300:
                        win = 1 if v4["close"] < v4["open"] else 0
                        signals.append({
                            "ts": v3["from_ts"], "dir": "PUT", "variant": "classic", "win": win,
                        })
                        last_ts = v3["from_ts"]
                        used_levels.append(nivel)
    return signals


def report(name: str, signals: list[dict], payout: float = PAYOUT):
    if not signals:
        print(f"\n  {name}: nenhum sinal")
        return
    wins = int(sum(s["win"] for s in signals))
    total = len(signals)
    losses = total - wins
    wr = wins / total * 100
    profit = (wins * BET * payout) - (losses * BET)
    pf = (wins * BET * payout) / (losses * BET) if losses > 0 else float("inf")
    print(f"\n  {name}:")
    print(f"    Sinais: {total} | WIN: {wins} ({wr:.2f}%) | LOSS: {losses}")
    print(f"    R$ por 100 sinais (payout {payout*100:.0f}%): {profit/BET*10*100/10:.2f} -> {profit/total*100:+.2f} por sinal")
    print(f"    Profit Factor: {pf:.2f}")


def run(tol_pips: float = 0.5, payout: float = PAYOUT):
    data_dir = Path("corretora-evemex/dados/m1")
    files = sorted(data_dir.glob("*.parquet"))
    print(f"🚀 Backtest S16 - Fundo/Topo Duplo M5 | tolerância = {tol_pips} pip | payout = {payout*100:.0f}%")
    print(f"📁 {len(files)} ativos\n")

    all_lit, all_class = [], []
    per_symbol = {}

    for file in files:
        symbol = file.stem
        m5 = load_m5(symbol, data_dir)
        if m5.empty:
            continue
        sigs = detect_dual(m5, tol_pips, cooldown=10)
        lit = [s for s in sigs if s["variant"] == "literal"]
        cls = [s for s in sigs if s["variant"] == "classic"]
        all_lit += lit
        all_class += cls
        if lit or cls:
            per_symbol[symbol] = (len(lit), len(cls))

    print(f"{'Ativo':<14}{'S16 literal':>12}{'clássica':>10}")
    print("-" * 36)
    for sym in sorted(per_symbol):
        l, c = per_symbol[sym]
        print(f"{sym:<14}{l:>12}{c:>10}")

    print("\n" + "=" * 50)
    print("📊 RESULTADOS AGREGADOS (43 ATIVOS)")
    print("=" * 50)
    report(f"S16 LITERAL (como descrito)", all_lit, payout)
    report("S16 variação clássica (v3 verde/martelo p/ CALL)", all_class, payout)

    # Direção (literal)
    if all_lit:
        calls = [s for s in all_lit if s["dir"] == "CALL"]
        puts = [s for s in all_lit if s["dir"] == "PUT"]
        print("\n  Por direção (literal):")
        for d, label in ((calls, "CALLs"), (puts, "PUTs")):
            if d:
                w = sum(s["win"] for s in d)
                print(f"    {label}: {len(d)} sinais | winrate {w/len(d)*100:.2f}%")

    # Breakeven
    be = 100 * (1 / (1 + payout))
    print(f"\n  ⚖️  Breakeven com payout {payout*100:.0f}%: {be:.2f}% de acerto")

    # ---- VALIDAÇÃO TEMPORAL (out-of-sample) ----
    print("\n" + "=" * 50)
    print("🔬 VALIDAÇÃO TEMPORAL (últimos 20% dos dados)")
    print("=" * 50)
    for p in (0.85, 0.75):
        be_p = 100 * (1 / (1 + p))
        # Ordena por timestamp e pega últimos 20%
        all_lit_sorted = sorted(all_lit, key=lambda s: s["ts"])
        split = int(len(all_lit_sorted) * 0.8)
        oos = all_lit_sorted[split:]
        wins = sum(s["win"] for s in oos)
        total = len(oos)
        wr = wins / total * 100 if total else 0
        profit = (wins * BET * p) - ((total - wins) * BET)
        print(f"\n  Payout {p*100:.0f}% (breakeven {be_p:.2f}%):")
        print(f"    Sinais OOS: {total} | WIN: {wins} ({wr:.2f}%) | LOSS: {total - wins}")
        print(f"    Lucro: R$ {profit:.2f} | por sinal: R$ {profit/total:.2f}" if total else "    Sem sinais")


if __name__ == "__main__":
    run(tol_pips=0.5)
