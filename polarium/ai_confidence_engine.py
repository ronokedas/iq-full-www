"""
Engine de Inteligência Artificial para Confiança de Sinais (Filtro por Win-Rate Histórico).
Autoriza sinais apenas para pares que possuem >= 60% de assertividade na estratégia específica.
"""

from typing import Dict, Tuple

# Mapping of Strategy_ID -> { Symbol -> Win Rate % }
# Apenas pares com win-rate >= 60% baseados nos backtests de 7 dias Mão Fixa
CONFIDENCE_DATABASE: Dict[str, Dict[str, float]] = {
    
    # 🥇 Medalha de Ouro: SMC Institucional (FVG) em M2
    "smc_m2": {
        "CADCHF-OTC": 88.89,
        "AUDCHF-OTC": 83.33,
        "NZDJPY-OTC": 77.78,
        "USOUSD-OTC": 75.00,
        "XAGUSD-OTC": 73.33,
        "USDINR-OTC": 72.73,
        "LINKUSD-OTC": 71.43,
        "MelaniaCoin OTC": 71.43,
        "GBPCAD-OTC": 70.00,
        "USDCHF-OTC": 69.23,
        "AUDUSD-OTC": 66.67,
        "CADJPY-OTC": 66.67,
        "EURGBP-OTC": 66.67,
        "GBPAUD-OTC": 66.67,
        "GOOGLE_MSFT-OTC": 66.67,
        "ICPUSD-OTC": 66.67,
        "SEIUSD-OTC": 66.67,
        "EOSUSD-OTC": 64.71,
        "AMZN_EBAY-OTC": 64.29,
        "CHFNOK-OTC": 64.29,
        "IMXUSD-OTC": 64.29,
        "LTCUSD-OTC": 63.16,
        "USDTHB-OTC": 63.16,
        "XAUUSD-OTC": 62.50,
        "USDSGD-OTC": 60.00
    },
    
    # 🥈 Medalha de Prata: Robô Sniper M1 (Exaustão BB + RSI)
    "sniper_m1": {
        "USDCAD-OTC": 63.50,
        "PYTHUSD-OTC": 62.20,
        "PENGUUSD-OTC": 61.10,
        "EURUSD-OTC": 60.50,
        "NZDUSD-OTC": 60.10
    },
    
    # 🥉 Medalha de Bronze: SMC Institucional (FVG) em M1
    "smc_m1": {
        "FLOKIUSD-OTC": 81.82,
        "EURCAD-OTC": 72.00,
        "USOUSD-OTC": 68.75,
        "ORDIUSD-OTC": 68.42,
        "DYDXUSD-OTC": 66.67,
        "USDSEK-OTC": 66.67,
        "ATOMUSD-OTC": 65.71,
        "DASHUSD-OTC": 62.50,
        "MATICUSD-OTC": 62.50,
        "GOOGLE_MSFT-OTC": 62.07,
        "AUDUSD-OTC": 61.76,
        "EURTHB-OTC": 60.71,
        "ONDOUSD-OTC": 60.71,
        "GBPJPY-OTC": 60.00,
        "TIAUSD-OTC": 60.00
    }
}

MINIMUM_CONFIDENCE_THRESHOLD = 60.0

def _normalize_symbol(symbol: str) -> str:
    """
    Normaliza o símbolo para o formato canônico do banco de dados: EURCAD-OTC.
    Aceita qualquer variação: EURCAD_otc, eurcad-otc, EURCAD_OTC, etc.
    """
    # Substitui underscore por hífen e converte para maiúsculas
    normalized = symbol.replace("_", "-").upper()
    # Garante o sufixo -OTC
    if not normalized.endswith("-OTC"):
        normalized = normalized + "-OTC"
    return normalized

def get_confidence(strategy_id: str, symbol: str) -> float:
    """
    Retorna o nível de confiança (0-100%) da IA para aquele par naquela estratégia.
    """
    if strategy_id not in CONFIDENCE_DATABASE:
        return 0.0
    
    canonical = _normalize_symbol(symbol)
    return CONFIDENCE_DATABASE[strategy_id].get(canonical, 0.0)

def is_approved_by_ai(strategy_id: str, symbol: str) -> Tuple[bool, float]:
    """
    Avalia se a IA aprova a entrada baseada na assertividade matemática histórica.
    Retorna (Aprovado, WinRate%).
    """
    confidence = get_confidence(strategy_id, symbol)
    approved = confidence >= MINIMUM_CONFIDENCE_THRESHOLD
    return approved, confidence
