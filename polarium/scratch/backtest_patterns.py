import os
import csv
from pathlib import Path

BACKTEST_DIR = Path(r"C:\iq-full-www\polarium\backtest")

def is_green(c):
    return float(c['close']) > float(c['open'])

def is_red(c):
    return float(c['close']) < float(c['open'])

def doji(c):
    return float(c['close']) == float(c['open'])

def analyze_file(filepath):
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

    # Ordenar por timestamp (do mais antigo pro mais novo)
    # A extração colocou os mais recentes primeiro ou último? Vamos verificar pelo from
    candles.sort(key=lambda x: int(x['timestamp']))
    
    # 1. Padrão: Reversão após 3 cores iguais (Three in a row -> Reversal)
    # 2. Padrão: Reversão após 4 cores iguais
    # 3. MHI-1: Maioria das últimas 3 velas (minutos 3, 4, 5 do bloco de 5) -> entra na cor da minoria no min 1
    
    stats = {
        "3_red_to_green": {"wins": 0, "losses": 0},
        "3_green_to_red": {"wins": 0, "losses": 0},
        "4_red_to_green": {"wins": 0, "losses": 0},
        "4_green_to_red": {"wins": 0, "losses": 0},
        "mhi_1": {"wins": 0, "losses": 0, "g1_wins": 0, "g2_wins": 0} # MHI com até 2 martingales
    }
    
    colors = []
    for c in candles:
        if is_green(c): colors.append('G')
        elif is_red(c): colors.append('R')
        else: colors.append('D') # Doji
        
    for i in range(4, len(colors)):
        # Reversão após 3
        if colors[i-3:i] == ['R', 'R', 'R']:
            if colors[i] == 'G': stats["3_red_to_green"]["wins"] += 1
            elif colors[i] == 'R': stats["3_red_to_green"]["losses"] += 1
            
        if colors[i-3:i] == ['G', 'G', 'G']:
            if colors[i] == 'R': stats["3_green_to_red"]["wins"] += 1
            elif colors[i] == 'G': stats["3_green_to_red"]["losses"] += 1
            
        # Reversão após 4
        if i >= 5:
            if colors[i-4:i] == ['R', 'R', 'R', 'R']:
                if colors[i] == 'G': stats["4_red_to_green"]["wins"] += 1
                elif colors[i] == 'R': stats["4_red_to_green"]["losses"] += 1
                
            if colors[i-4:i] == ['G', 'G', 'G', 'G']:
                if colors[i] == 'R': stats["4_green_to_red"]["wins"] += 1
                elif colors[i] == 'G': stats["4_green_to_red"]["losses"] += 1

    # MHI-1 (blocos de 5 minutos: ex 10:00 a 10:04, analisar 10:02, 10:03, 10:04)
    # MHI entra em 10:05 apostando na minoria
    for i in range(len(candles) - 3):
        # Encontrar início de bloco (minuto termina em 0 ou 5)
        dt = candles[i]['datetime']
        minute = int(dt[14:16])
        
        if minute % 5 == 2 and i+3 < len(colors): # i = min 2, i+1 = min 3, i+2 = min 4. Entrar em i+3 (min 5/0)
            c1, c2, c3 = colors[i], colors[i+1], colors[i+2]
            if 'D' in [c1, c2, c3]: continue # Ignorar dojis na análise
            
            reds = [c1, c2, c3].count('R')
            greens = [c1, c2, c3].count('G')
            
            minority = 'G' if reds > greens else 'R'
            
            # Entrada principal (i+3)
            if colors[i+3] == minority:
                stats["mhi_1"]["wins"] += 1
            else:
                # Martingale 1 (i+4)
                if i+4 < len(colors) and colors[i+4] == minority:
                    stats["mhi_1"]["g1_wins"] += 1
                else:
                    # Martingale 2 (i+5)
                    if i+5 < len(colors) and colors[i+5] == minority:
                        stats["mhi_1"]["g2_wins"] += 1
                    else:
                        stats["mhi_1"]["losses"] += 1

    return stats

def main():
    print("Iniciando varredura nos arquivos de backtest...")
    files = list(BACKTEST_DIR.glob("*.csv"))
    
    overall_stats = {
        "3_red_to_green": {"w": 0, "l": 0},
        "3_green_to_red": {"w": 0, "l": 0},
        "4_red_to_green": {"w": 0, "l": 0},
        "4_green_to_red": {"w": 0, "l": 0},
        "mhi_1_no_gale": {"w": 0, "l": 0},
        "mhi_1_gale1": {"w": 0, "l": 0},
        "mhi_1_gale2": {"w": 0, "l": 0}
    }
    
    pair_mhi = {}

    for f in files:
        res = analyze_file(f)
        if not res: continue
        
        # Agregar globais
        overall_stats["3_red_to_green"]["w"] += res["3_red_to_green"]["wins"]
        overall_stats["3_red_to_green"]["l"] += res["3_red_to_green"]["losses"]
        
        overall_stats["3_green_to_red"]["w"] += res["3_green_to_red"]["wins"]
        overall_stats["3_green_to_red"]["l"] += res["3_green_to_red"]["losses"]
        
        overall_stats["4_red_to_green"]["w"] += res["4_red_to_green"]["wins"]
        overall_stats["4_red_to_green"]["l"] += res["4_red_to_green"]["losses"]
        
        overall_stats["4_green_to_red"]["w"] += res["4_green_to_red"]["wins"]
        overall_stats["4_green_to_red"]["l"] += res["4_green_to_red"]["losses"]
        
        mhi_w = res["mhi_1"]["wins"]
        mhi_g1 = res["mhi_1"]["g1_wins"]
        mhi_g2 = res["mhi_1"]["g2_wins"]
        mhi_l = res["mhi_1"]["losses"]
        
        overall_stats["mhi_1_no_gale"]["w"] += mhi_w
        overall_stats["mhi_1_no_gale"]["l"] += (mhi_g1 + mhi_g2 + mhi_l)
        
        overall_stats["mhi_1_gale1"]["w"] += (mhi_w + mhi_g1)
        overall_stats["mhi_1_gale1"]["l"] += (mhi_g2 + mhi_l)
        
        overall_stats["mhi_1_gale2"]["w"] += (mhi_w + mhi_g1 + mhi_g2)
        overall_stats["mhi_1_gale2"]["l"] += mhi_l
        
        # Salvar MHI Gale 1 para o ranking
        total_mhi_g1 = mhi_w + mhi_g1 + mhi_g2 + mhi_l
        if total_mhi_g1 > 0:
            win_rate_g1 = (mhi_w + mhi_g1) / total_mhi_g1
            pair_mhi[f.stem] = win_rate_g1

    print("\n=== RESULTADOS GLOBAIS (TODOS OS PARES OTC) ===")
    
    def print_stat(name, w, l):
        t = w + l
        wr = (w/t*100) if t > 0 else 0
        print(f"{name:20}: {wr:.2f}% de Acerto (Wins: {w}, Loss: {l})")

    print_stat("3 Red -> Comprar", overall_stats["3_red_to_green"]["w"], overall_stats["3_red_to_green"]["l"])
    print_stat("3 Green -> Vender", overall_stats["3_green_to_red"]["w"], overall_stats["3_green_to_red"]["l"])
    print_stat("4 Red -> Comprar", overall_stats["4_red_to_green"]["w"], overall_stats["4_red_to_green"]["l"])
    print_stat("4 Green -> Vender", overall_stats["4_green_to_red"]["w"], overall_stats["4_green_to_red"]["l"])
    
    print("\n--- ESTRATÉGIA MHI (Minoria nas 3 últimas velas de 5m) ---")
    print_stat("MHI (Mão Fixa)", overall_stats["mhi_1_no_gale"]["w"], overall_stats["mhi_1_no_gale"]["l"])
    print_stat("MHI (Com 1 Gale)", overall_stats["mhi_1_gale1"]["w"], overall_stats["mhi_1_gale1"]["l"])
    print_stat("MHI (Com 2 Gales)", overall_stats["mhi_1_gale2"]["w"], overall_stats["mhi_1_gale2"]["l"])
    
    print("\n=== TOP 50 PARES PARA MHI (Com 1 Gale) ===")
    top_pairs = sorted(pair_mhi.items(), key=lambda x: x[1], reverse=True)[:50]
    for p, wr in top_pairs:
        print(f"{p}: {wr*100:.2f}%")

if __name__ == "__main__":
    main()
