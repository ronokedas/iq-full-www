import csv
from pathlib import Path

BACKTEST_DIR = Path(r"C:\iq-full-www\polarium\backtest")

def is_green(c): return float(c['close']) > float(c['open'])
def is_red(c): return float(c['close']) < float(c['open'])

def get_color(c):
    if is_green(c): return 'G'
    if is_red(c): return 'R'
    return 'D'

def analyze_advanced(filepath):
    candles = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                candles.append(row)
    except:
        return None
        
    if len(candles) < 100:
        return None

    candles.sort(key=lambda x: int(x['timestamp']))
    colors = [get_color(c) for c in candles]
    
    stats = {
        # Padrão de FLUXO (Continuação de Tendência)
        "flux_3G_to_G": {"w": 0, "l": 0},
        "flux_3R_to_R": {"w": 0, "l": 0},
        "flux_4G_to_G": {"w": 0, "l": 0},
        "flux_4R_to_R": {"w": 0, "l": 0},
        "flux_5G_to_G": {"w": 0, "l": 0},
        "flux_5R_to_R": {"w": 0, "l": 0},
        
        # Padrão TORRES GÊMEAS (Espelhamento do início de bloco)
        "torres_gemeas": {"w": 0, "l": 0},
        
        # Padrão 23 (G-R-R -> G ou R-G-G -> R)
        "padrao_23": {"w": 0, "l": 0},
        
        # Padrão TRIÂNGULO (R-G-R -> G ou G-R-G -> R)
        "padrao_triangulo": {"w": 0, "l": 0}
    }
    
    # Análise linear
    for i in range(5, len(colors)):
        c = colors[i]
        hist = colors[i-5:i] # 5 anteriores: hist[0], hist[1], hist[2], hist[3], hist[4]
        
        # Fluxo 3
        if hist[2:] == ['G','G','G']:
            if c == 'G': stats["flux_3G_to_G"]["w"] += 1
            elif c == 'R': stats["flux_3G_to_G"]["l"] += 1
        if hist[2:] == ['R','R','R']:
            if c == 'R': stats["flux_3R_to_R"]["w"] += 1
            elif c == 'G': stats["flux_3R_to_R"]["l"] += 1
            
        # Fluxo 4
        if hist[1:] == ['G','G','G','G']:
            if c == 'G': stats["flux_4G_to_G"]["w"] += 1
            elif c == 'R': stats["flux_4G_to_G"]["l"] += 1
        if hist[1:] == ['R','R','R','R']:
            if c == 'R': stats["flux_4R_to_R"]["w"] += 1
            elif c == 'G': stats["flux_4R_to_R"]["l"] += 1
            
        # Fluxo 5
        if hist == ['G','G','G','G','G']:
            if c == 'G': stats["flux_5G_to_G"]["w"] += 1
            elif c == 'R': stats["flux_5G_to_G"]["l"] += 1
        if hist == ['R','R','R','R','R']:
            if c == 'R': stats["flux_5R_to_R"]["w"] += 1
            elif c == 'G': stats["flux_5R_to_R"]["l"] += 1
            
        # Padrão 23
        if hist[2:] == ['G', 'R', 'R']:
            if c == 'G': stats["padrao_23"]["w"] += 1
            elif c == 'R': stats["padrao_23"]["l"] += 1
        if hist[2:] == ['R', 'G', 'G']:
            if c == 'R': stats["padrao_23"]["w"] += 1
            elif c == 'G': stats["padrao_23"]["l"] += 1
            
        # Triângulo
        if hist[2:] == ['R', 'G', 'R']:
            if c == 'G': stats["padrao_triangulo"]["w"] += 1
            elif c == 'R': stats["padrao_triangulo"]["l"] += 1
        if hist[2:] == ['G', 'R', 'G']:
            if c == 'R': stats["padrao_triangulo"]["w"] += 1
            elif c == 'G': stats["padrao_triangulo"]["l"] += 1

    # Torres Gêmeas (blocos de 5m)
    for i in range(len(candles) - 5):
        dt = candles[i]['datetime']
        minute = int(dt[14:16])
        if minute % 5 == 0: # Início de bloco (vela 1)
            cor_vela1 = colors[i]
            # Próximo bloco começa no índice i+5
            if i+5 < len(colors) and cor_vela1 != 'D':
                cor_vela_proximo_bloco = colors[i+5]
                if cor_vela_proximo_bloco == cor_vela1:
                    stats["torres_gemeas"]["w"] += 1
                elif cor_vela_proximo_bloco != 'D':
                    stats["torres_gemeas"]["l"] += 1

    return stats

def main():
    files = list(BACKTEST_DIR.glob("*.csv"))
    
    top_results = [] # Lista de (par, nome_estrategia, win_rate, total_trades)
    
    for f in files:
        res = analyze_advanced(f)
        if not res: continue
        
        for strat_name, data in res.items():
            total = data["w"] + data["l"]
            if total > 50: # Exige no mínimo 50 entradas na semana pra ter relevância estatística
                wr = data["w"] / total * 100
                if wr >= 60.0: # Salvar as que bateram 60%+ sem gale
                    top_results.append((f.stem.replace("_M1_7days", ""), strat_name, wr, total))
                    
    # Ordenar por win_rate
    top_results.sort(key=lambda x: x[2], reverse=True)
    
    print("\n=== CAÇADOR DE PADRÕES: MÃO FIXA (SEM GALE) ===")
    print("Mostrando os padrões que dão MÃO FIXA acima de 60% no OTC da Polarium\n")
    
    count = 0
    for par, strat, wr, total in top_results:
        if wr >= 65.0:
            print(f"🔥 EXCELENTE: {par} | {strat} | Acerto: {wr:.2f}% (Amostras: {total})")
            count += 1
        elif count < 20: # Imprimir pelo menos os 20 melhores se não tiver muitos excelentes
            print(f"⭐ BOM: {par} | {strat} | Acerto: {wr:.2f}% (Amostras: {total})")
            count += 1
            
    if not top_results:
        print("Triste... Nenhuma estratégia sem martingale alcançou mais de 60% nessa semana.")

if __name__ == "__main__":
    main()
