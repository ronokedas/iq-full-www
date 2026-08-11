"""
Backtest Full - Sistema Completo de Validação de Estratégias
------------------------------------------------------------
Lê todo o histórico de velas (Parquet) da pasta 'dados/iq_option/m1'
e executa backtest de TODAS as estratégias do catálogo EvePulse/SuperFull.

Gera relatório preciso com:
- Taxa de Acerto (Win Rate)
- Lucro/Prejuízo Líquido (considerando Payout médio)
- Drawdown Máximo
- Ranking das melhores estratégias por par e geral
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np

# Configurações
DADOS_DIR = Path(__file__).resolve().parent / "dados" / "iq_option" / "m1"
MANIFESTO_FILE = DADOS_DIR.parent / "manifest.json"
RESULTADOS_DIR = Path(__file__).resolve().parent / "resultados_backtest"

# Configuração de Payout Médio (pode ser ajustado ou lido de um config)
PAYOUT_PADRAO = 0.87  # 87%
VALOR_ENTRADA = 100.0  # Valor base para cálculo de lucro/prejuízo

class CandleStick:
    """Representação de uma vela."""
    def __init__(self, row: dict):
        self.ts = int(row['from_ts'])
        self.open = float(row['open'])
        self.high = float(row['high'])
        self.low = float(row['low'])
        self.close = float(row['close'])
        self.volume = float(row.get('volume', 0))
        
    @property
    def is_bullish(self) -> bool:
        return self.close > self.open
    
    @property
    def is_bearish(self) -> bool:
        return self.close < self.open
    
    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)
    
    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)
    
    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low
    
    @property
    def total_size(self) -> float:
        return self.high - self.low

class EstrategiaBase:
    """Classe base para todas as estratégias."""
    nome = "Base"
    timeframe_operacao = 1  # minutos para expiração
    
    def analisar(self, velas: List[CandleStick], indice_atual: int) -> Optional[str]:
        """
        Retorna 'CALL', 'PUT' ou None (sem sinal).
        'velas': lista histórica completa até o momento.
        'indice_atual': índice da vela que acabou de fechar (gatilho).
        """
        raise NotImplementedError

# ==============================================================================
# IMPLEMENTAÇÃO DAS ESTRATÉGIAS (Baseadas no Catálogo EvePulse)
# ==============================================================================

class S1_TresVelasReversao(EstrategiaBase):
    nome = "S1 - Três Velas Reversão"
    
    def analisar(self, velas: List[CandleStick], idx: int) -> Optional[str]:
        if idx < 3: return None
        v1, v2, v3 = velas[idx-2], velas[idx-1], velas[idx]
        
        # Tendência de alta (3 verdes) -> PUT na 4ª
        if v1.is_bullish and v2.is_bullish and v3.is_bullish:
            # Filtro: tamanho das velas não pode ser exausto (doji)
            if v3.body_size > 0.0001: 
                return "PUT"
        
        # Tendência de baixa (3 vermelhas) -> CALL na 4ª
        if v1.is_bearish and v2.is_bearish and v3.is_bearish:
            if v3.body_size > 0.0001:
                return "CALL"
        return None

class S5_PrimeiroRetornoM1(EstrategiaBase):
    nome = "S5 - Primeiro Retorno M1"
    
    def analisar(self, velas: List[CandleStick], idx: int) -> Optional[str]:
        if idx < 2: return None
        v_ant = velas[idx-1]
        v_atu = velas[idx]
        
        # Identificar tendência forte anterior
        # Exemplo simplificado: Vela anterior grande a favor da tendência
        if v_ant.is_bullish and v_ant.body_size > 0.0005:
            # Retração pequena (doji ou vela pequena contra)
            if v_atu.body_size < (v_ant.body_size * 0.3):
                return "CALL" # A favor da tendência
        
        if v_ant.is_bearish and v_ant.body_size > 0.0005:
            if v_atu.body_size < (v_ant.body_size * 0.3):
                return "PUT"
        return None

class S9_LateralH1(EstrategiaBase):
    nome = "S9 - Lateral H1 Reversão"
    
    def analisar(self, velas: List[CandleStick], idx: int) -> Optional[str]:
        if idx < 60: return None # Precisa de 1 hora (60 velas M1)
        
        # Verificar lateralidade nas últimas 60 velas
        ultimas_60 = velas[idx-59:idx+1]
        highs = [v.high for v in ultimas_60]
        lows = [v.low for v in ultimas_60]
        
        topo = max(highs)
        fundo = min(lows)
        range_size = topo - fundo
        
        # Se o range for pequeno (lateralização)
        if range_size < 0.0010: # Ajustar conforme o par
            v_atual = velas[idx]
            
            # Toque no topo -> PUT
            if v_atual.high >= topo - 0.0001 and v_atual.is_bearish:
                return "PUT"
            
            # Toque no fundo -> CALL
            if v_atual.low <= fundo + 0.0001 and v_atual.is_bullish:
                return "CALL"
        return None

class S13_PaviosRejeicao(EstrategiaBase):
    nome = "S13 - Pavios de Rejeição"
    
    def analisar(self, velas: List[CandleStick], idx: int) -> Optional[str]:
        if idx < 1: return None
        v = velas[idx]
        
        ratio_upper = v.upper_wick / v.total_size if v.total_size > 0 else 0
        ratio_lower = v.lower_wick / v.total_size if v.total_size > 0 else 0
        
        # Pavio superior longo (rejeição de alta) -> PUT
        if ratio_upper > 0.6 and v.is_bearish:
            return "PUT"
        
        # Pavio inferior longo (rejeição de baixa) -> CALL
        if ratio_lower > 0.6 and v.is_bullish:
            return "CALL"
        return None

class S14_ContinuacaoRejeicao(EstrategiaBase):
    nome = "S14 - Continuação com Rejeição"
    
    def analisar(self, velas: List[CandleStick], idx: int) -> Optional[str]:
        if idx < 2: return None
        v_ant = velas[idx-1]
        v_atu = velas[idx]
        
        # Tendência de alta + rejeição de baixa na retração
        if v_ant.is_bullish:
            if v_atu.lower_wick > (v_atu.body_size * 1.5) and v_atu.is_bullish:
                return "CALL"
        
        # Tendência de baixa + rejeição de alta na retração
        if v_ant.is_bearish:
            if v_atu.upper_wick > (v_atu.body_size * 1.5) and v_atu.is_bearish:
                return "PUT"
        return None

class S15_FalsoRompimento(EstrategiaBase):
    nome = "S15 - Falso Rompimento"
    
    def analisar(self, velas: List[CandleStick], idx: int) -> Optional[str]:
        if idx < 20: return None
        
        # Identificar máximo das últimas 20 velas
        max_recente = max(v.high for v in velas[idx-19:idx])
        min_recente = min(v.low for v in velas[idx-19:idx])
        
        v_atual = velas[idx]
        
        # Rompeu máximo mas fechou abaixo (falso rompimento) -> PUT
        if v_atual.high > max_recente and v_atual.close < max_recente and v_atual.is_bearish:
            return "PUT"
            
        # Rompeu mínimo mas fechou acima (falso rompimento) -> CALL
        if v_atual.low < min_recente and v_atual.close > min_recente and v_atual.is_bullish:
            return "CALL"
        return None

class S16_EngolfoM5_M15(EstrategiaBase):
    nome = "S16 - Engolfo M5 na Abertura M15"
    
    def analisar(self, velas: List[CandleStick], idx: int) -> Optional[str]:
        # Simplificação: Detectar engolfo em M1 considerando contexto
        if idx < 2: return None
        v_ant = velas[idx-1]
        v_atu = velas[idx]
        
        # Engolfo de Alta
        if v_ant.is_bearish and v_atu.is_bullish:
            if v_atu.open < v_ant.close and v_atu.close > v_ant.open:
                return "CALL"
        
        # Engolfo de Baixa
        if v_ant.is_bullish and v_atu.is_bearish:
            if v_atu.open > v_ant.close and v_atu.close < v_ant.open:
                return "PUT"
        return None

class S17_RompimentoDuplaPosicao(EstrategiaBase):
    nome = "S17 - Rompimento Dupla Posição"
    
    def analisar(self, velas: List[CandleStick], idx: int) -> Optional[str]:
        if idx < 5: return None
        
        # Identificar consolidação (2 topos ou 2 fundos)
        # Lógica simplificada: Rompimento de máxima das últimas 5 velas com força
        max_consol = max(v.high for v in velas[idx-4:idx])
        v_atual = velas[idx]
        
        if v_atual.close > max_consol and v_atual.body_size > 0.0003:
            return "CALL"
            
        min_consol = min(v.low for v in velas[idx-4:idx])
        if v_atual.close < min_consol and v_atual.body_size > 0.0003:
            return "PUT"
            
        return None

# Adicione mais estratégias aqui seguindo o padrão...
# class S_Laboratorio_X(EstrategiaBase): ...

LISTA_ESTRATEGIAS = [
    S1_TresVelasReversao(),
    S5_PrimeiroRetornoM1(),
    S9_LateralH1(),
    S13_PaviosRejeicao(),
    S14_ContinuacaoRejeicao(),
    S15_FalsoRompimento(),
    S16_EngolfoM5_M15(),
    S17_RompimentoDuplaPosicao(),
]

# ==============================================================================
# MOTOR DE BACKTEST
# ==============================================================================

def executar_backtest_par(symbol: str, df: pd.DataFrame, estrategias: List[EstrategiaBase]) -> Dict:
    """Executa backtest para um único par e várias estratégias."""
    
    # Converter DataFrame para lista de objetos CandleStick
    velas = [CandleStick(row) for _, row in df.iterrows()]
    total_velas = len(velas)
    
    resultados = {}
    
    print(f"\n🚀 Processando {symbol} ({total_velas} velas)...")
    
    for estrat in estrategias:
        wins = 0
        losses = 0
        draws = 0
        equity_curve = [1000]  # Começa com 1000 fictícios
        max_drawdown = 0
        
        # Iterar sobre as velas (deixando margem para expiração)
        # Explicação: Se a estratégia opera M1 e expira em 1 vela, analisamos até a penúltima
        for i in range(len(velas) - 2): 
            sinal = estrat.analisar(velas, i)
            
            if sinal:
                # Simular entrada na abertura da próxima vela (i+1)
                entrada_vela = velas[i+1]
                preco_entrada = entrada_vela.open
                
                # Simular resultado na expiração (1 vela depois, i+2)
                saida_vela = velas[i+2]
                preco_saida = saida_vela.close
                
                ganhou = False
                
                if sinal == "CALL":
                    if preco_saida > preco_entrada:
                        ganhou = True
                elif sinal == "PUT":
                    if preco_saida < preco_entrada:
                        ganhou = True
                
                # Atualizar contadores
                if ganhou:
                    wins += 1
                    lucro = VALOR_ENTRADA * PAYOUT_PADRAO
                    equity_curve.append(equity_curve[-1] + lucro)
                else:
                    losses += 1
                    prejuizo = VALOR_ENTRADA
                    equity_curve.append(equity_curve[-1] - prejuizo)
                
                # Calcular Drawdown
                pico_anterior = max(equity_curve)
                drawdown_atual = pico_anterior - equity_curve[-1]
                if drawdown_atual > max_drawdown:
                    max_drawdown = drawdown_atual
        
        total_operacoes = wins + losses
        taxa_acerto = (wins / total_operacoes * 100) if total_operacoes > 0 else 0
        lucro_liquido = equity_curve[-1] - 1000
        
        resultados[estrat.nome] = {
            "operacoes": total_operacoes,
            "wins": wins,
            "losses": losses,
            "taxa_acerto": round(taxa_acerto, 2),
            "lucro_liquido": round(lucro_liquido, 2),
            "drawdown_max": round(max_drawdown, 2),
            "roi": round((lucro_liquido / 1000) * 100, 2) if total_operacoes > 0 else 0
        }
        
        print(f"   ✅ {estrat.nome}: {total_operacoes} ops | {taxa_acerto:.1f}% | R$ {lucro_liquido:.2f}")
    
    return resultados

def main():
    print("📊 INICIANDO BACKTEST FULL SYSTEM")
    print("="*50)
    
    if not DADOS_DIR.exists():
        print(f"❌ Pasta de dados não encontrada: {DADOS_DIR}")
        print("Execute primeiro o script 'baixar-velas.py'")
        return
    
    RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Carregar manifesto para saber quais arquivos processar
    if not MANIFESTO_FILE.exists():
        print("❌ Manifesto não encontrado. Execute o download primeiro.")
        return
        
    with open(MANIFESTO_FILE, 'r', encoding='utf-8') as f:
        manifesto = json.load(f)
    
    pares = manifesto.get('pairs', {})
    if not pares:
        print("Nenhum par encontrado no manifesto.")
        return
    
    print(f"📂 Encontrados {len(pares)} pares para backtest.")
    print(f"🧠 Estratégias carregadas: {len(LISTA_ESTRATEGIAS)}")
    for e in LISTA_ESTRATEGIAS:
        print(f"   - {e.nome}")
    
    ranking_global = []
    
    for symbol, info in pares.items():
        arquivo_parquet = DADOS_DIR / info['file']
        
        if not arquivo_parquet.exists():
            print(f"⚠️ Arquivo não encontrado: {arquivo_parquet}")
            continue
            
        try:
            df = pd.read_parquet(arquivo_parquet)
            # Ordenar por tempo apenas por segurança
            df = df.sort_values('from_ts').reset_index(drop=True)
            
            resultados_par = executar_backtest_par(symbol, df, LISTA_ESTRATEGIAS)
            
            # Salvar resultado individual
            arquivo_resultado = RESULTADOS_DIR / f"{symbol.replace('-', '_')}_backtest.json"
            with open(arquivo_resultado, 'w', encoding='utf-8') as f:
                json.dump({
                    "symbol": symbol,
                    "data_processamento": datetime.now(timezone.utc).isoformat(),
                    "resultados": resultados_par
                }, f, indent=2, ensure_ascii=False)
            
            # Compilar para ranking global
            for estrat_nome, dados in resultados_par.items():
                ranking_global.append({
                    "estrategia": estrat_nome,
                    "par": symbol,
                    "taxa_acerto": dados['taxa_acerto'],
                    "lucro_liquido": dados['lucro_liquido'],
                    "operacoes": dados['operacoes']
                })
                
        except Exception as e:
            print(f"❌ Erro ao processar {symbol}: {e}")
            continue
    
    # Gerar Relatório Global
    print("\n" + "="*50)
    print("🏆 TOP 10 MELHORES COMBINAÇÕES (Por Taxa de Acerto)")
    print("="*50)
    
    # Filtrar apenas estratégias com número significativo de operações (> 50)
    ranking_filtrado = [r for r in ranking_global if r['operacoes'] >= 50]
    ranking_filtrado.sort(key=lambda x: x['taxa_acerto'], reverse=True)
    
    for i, item in enumerate(ranking_filtrado[:10], 1):
        print(f"{i}. {item['estrategia']} em {item['par']}")
        print(f"   🎯 Acerto: {item['taxa_acerto']}% | 💰 Lucro: R$ {item['lucro_liquido']} | #Ops: {item['operacoes']}")
    
    # Salvar Ranking Completo
    ranking_file = RESULTADOS_DIR / "ranking_global.json"
    with open(ranking_file, 'w', encoding='utf-8') as f:
        json.dump(ranking_filtrado, f, indent=2)
    
    print(f"\n💾 Relatórios salvos em: {RESULTADOS_DIR}")
    print("✅ Backtest concluído!")

if __name__ == "__main__":
    main()
