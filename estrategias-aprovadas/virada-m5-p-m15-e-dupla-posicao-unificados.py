import time
from datetime import datetime
import requests
from iqoptionapi.stable_api import IQ_Option

# ==========================================
# 1. CONFIGURAÇÕES UNIFICADAS
# ==========================================
CONFIG = {
    "email": "dicasbbom@gmail.com",
    "password": "1P9w@w4a5",
    "pairs": [
        "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "EURGBP", "USDCHF",
        "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "EURJPY-OTC",
        "EURGBP-OTC", "USDCHF-OTC"
    ],
    "whatsapp": "5591982702062",
    "timeframe": 300 # 300 = M5
}

alertas_enviados = []

def enviar_alerta(mensagem):
    url = "http://144.22.217.13:3001/send-message"
    try:
        requests.post(url, json={"number": CONFIG["whatsapp"], "message": mensagem}, timeout=5)
    except:
        pass
    print(f"\n[WHATSAPP] {mensagem.replace(chr(10), ' | ')}")

# ==========================================
# 2. SISTEMA 1 — ENGOLFO M5 NA VIRADA DO M15
# ==========================================
def eh_primeira_m5_de_nova_m15(vela_atual, vela_anterior):
    """
    Detecta a virada do M15 comparando os timestamps das velas M5.
    Cada vela M15 dura 900 segundos (15 min).
    Se o período M15 (from // 900) mudou entre duas velas M5 consecutivas,
    então vela_atual é a 1ª M5 da nova M15.
    """
    periodo_atual = vela_atual['from'] // 900
    periodo_anterior = vela_anterior['from'] // 900
    return periodo_atual != periodo_anterior

def verificar_engolfo_m15(v2, v1):
    """
    v2 = última M5 da M15 anterior (vela chave)
    v1 = 1ª M5 da nova M15 (vela gatilho)

    CALL: v2 vermelha + v1 verde + v1 fecha acima da máxima de v2
    PUT:  v2 verde + v1 vermelha + v1 fecha abaixo da mínima de v2
    """
    alertas = []

    if not eh_primeira_m5_de_nova_m15(v1, v2):
        return alertas

    # CALL
    if v2['close'] < v2['open'] and v1['close'] > v1['open'] and v1['close'] > v2['max']:
        alertas.append(
            "🟢 ALERTA DE COMPRA (CALL)\n"
            "Padrão: Engolfo M5 na Virada do M15\n"
            "A 1ª vela M5 da nova M15 engolfou a última vela M5 da M15 anterior para CIMA."
        )

    # PUT
    if v2['close'] > v2['open'] and v1['close'] < v1['open'] and v1['close'] < v2['min']:
        alertas.append(
            "🔴 ALERTA DE VENDA (PUT)\n"
            "Padrão: Engolfo M5 na Virada do M15\n"
            "A 1ª vela M5 da nova M15 engolfou a última vela M5 da M15 anterior para BAIXO."
        )

    return alertas

# ==========================================
# 3. SISTEMA 2 — ROMPIMENTO DE DUPLA POSIÇÃO
# ==========================================
def verificar_rompimento_dupla_posicao(v3, v2, v1):
    alertas = []

    dp_alta = (v3['close'] > v3['open']) and (v2['close'] > v2['open']) and (v2['max'] <= v3['max'])
    rompeu_dp_alta = v1['close'] > v3['max']

    if dp_alta and rompeu_dp_alta:
        alertas.append(
            "📈 GATILHO: ROMPIMENTO DUPLA POSIÇÃO DE ALTA\n"
            "Ação: A última vela fechou rompendo a máxima do lote anterior. Ponto de continuação para CALL!"
        )

    dp_baixa = (v3['close'] < v3['open']) and (v2['close'] < v2['open']) and (v2['min'] >= v3['min'])
    rompeu_dp_baixa = v1['close'] < v3['min']

    if dp_baixa and rompeu_dp_baixa:
        alertas.append(
            "📉 GATILHO: ROMPIMENTO DUPLA POSIÇÃO DE BAIXA\n"
            "Ação: A última vela fechou rompendo a mínima do lote anterior. Ponto de continuação para PUT!"
        )

    return alertas

# ==========================================
# 4. MOTOR UNIFICADO
# ==========================================
print("=" * 50)
print("  RADAR UNIFICADO — IQ Option")
print("  Engolfo M15 + Dupla Posição")
print("=" * 50)

API = IQ_Option(CONFIG["email"], CONFIG["password"])
check, reason = API.connect()

if check:
    print("✅ Autenticado com sucesso na IQ Option!")

    print(f"Abrindo canais de dados ({CONFIG['timeframe']}s) para {len(CONFIG['pairs'])} pares...")
    for p in CONFIG["pairs"]:
        API.start_candles_stream(p, CONFIG["timeframe"], 10)
        time.sleep(0.5)

    enviar_alerta(
        "👁️‍🗨️ Radar Unificado Ativado!\n"
        "Monitorando:\n"
        "• Engolfo M5 na Virada do M15\n"
        "• Rompimento de Dupla Posição (Alta/Baixa)"
    )

    while True:
        for par in CONFIG["pairs"]:
            try:
                velas_dict = API.get_realtime_candles(par, CONFIG["timeframe"])
                if not velas_dict or len(velas_dict) < 5:
                    continue

                velas = sorted([v for k, v in velas_dict.items()], key=lambda x: x['from'])

                v3 = velas[-4]  # Antepenúltima
                v2 = velas[-3]  # Penúltima
                v1 = velas[-2]  # Última vela fechada

                id_base = f"{par}_{v1['from']}"

                if id_base in alertas_enviados:
                    continue

                mensagens = []

                # --- Sistema 1: Engolfo M5 na Virada do M15 ---
                mensagens.extend(verificar_engolfo_m15(v2, v1))

                # --- Sistema 2: Rompimento de Dupla Posição ---
                mensagens.extend(verificar_rompimento_dupla_posicao(v3, v2, v1))

                if mensagens:
                    for msg in mensagens:
                        enviar_alerta(f"Ativo: {par}\n{msg}")
                    alertas_enviados.append(id_base)

            except Exception as e:
                pass

        if len(alertas_enviados) > 100:
            alertas_enviados.pop(0)

        time.sleep(1)

else:
    print(f"❌ Falha ao conectar na IQ Option: {reason}")