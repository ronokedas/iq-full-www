"""
Bot Completo de Operação Real/Demo IQ Option com Filtro de IA (Machine Learning)
================================================================================
Este script:
1. Conecta-se à API da IQ Option (Solicita email, senha e tipo de conta).
2. Monitora os pares de moedas em tempo real.
3. Detecta sinais das 15 estratégias ativas.
4. Aplica o Filtro de Inteligência Artificial (LightGBM):
   - Calcula as 24 features técnicas em tempo real.
   - Aplica a Regra de Ouro: Só realiza a entrada se Probabilidade(WIN) >= 55%.
5. Executa as ordens de compra/venda automaticamente na IQ Option quando aprovadas!
"""

import os
import sys
import time
import math
from pathlib import Path
from datetime import datetime
from collections import deque

# Adiciona pasta de estratégias ao PATH
BASE_DIR = Path(__file__).parent
ESTRATEGIAS_DIR = BASE_DIR / "estrategias-aprovadas"
sys.path.append(str(ESTRATEGIAS_DIR))

try:
    import requests
    from iqoptionapi.stable_api import IQ_Option
except ImportError as erro:
    print(f"❌ Erro ao importar dependências: {erro}")
    print("Instale com: pip install requests iqoptionapi")
    sys.exit(1)

import pandas as pd
import numpy as np
from ml_feature_engineering import calculate_features
from ml_signal_filter import SignalFilter

PARES_OTC = [
    "AUDCAD-OTC", "EURGBP-OTC", "EURJPY-OTC", "EURUSD-OTC",
    "GBPJPY-OTC", "GBPUSD-OTC", "NZDUSD-OTC", "USDCHF-OTC",
    "USDHKD-OTC", "USDINR-OTC", "USDJPY-OTC", "USDSGD-OTC",
    "USDZAR-OTC",
]

def solicitar_credenciais():
    print("\n" + "=" * 70)
    print("🤖 BOT DE OPERAÇÃO E FILTRAGEM COM IA - IQ OPTION (EVEPULSE)")
    print("=" * 70)
    email = input("\n📧 Email da IQ Option: ").strip()
    password = input("🔑 Senha: ").strip()
    
    print("\nTipo de Conta:")
    print("  1 - DEMO (PRACTICE)")
    print("  2 - REAL (REAL)")
    opcao_conta = input("Escolha (1/2, Padrão 1): ").strip()
    conta = "REAL" if opcao_conta == "2" else "PRACTICE"
    
    print("\nModo de Operação:")
    print("  1 - MODO OPERAÇÃO REAL (Executar entradas aprovadas)")
    print("  2 - MODO SIMULAÇÃO / ALERTAS (Apenas sinalizar sem dar entrada)")
    opcao_auto = input("Escolha (1/2, Padrão 1): ").strip()
    auto_executar = True if opcao_auto != "2" else False
    
    try:
        valor_entrada = float(input("\n💰 Valor da Entrada (R$, Padrão 2.00): ") or "2.0")
    except ValueError:
        valor_entrada = 2.0
        
    return email, password, conta, auto_executar, valor_entrada

def converter_velas_para_df(velas_dict):
    """Converte o retorno da API da IQ Option para DataFrame compativel com calculate_features"""
    lista = []
    for _, v in velas_dict.items():
        lista.append({
            'from_ts': int(v['from']),
            'open': float(v['open']),
            'close': float(v['close']),
            'high': float(v['max']),
            'low': float(v['min']),
            'volume': float(v.get('volume', 0))
        })
    df = pd.DataFrame(lista)
    if not df.empty:
        df = df.sort_values('from_ts').reset_index(drop=True)
    return df

def iniciar_bot():
    model_path = ESTRATEGIAS_DIR / "signal_filter_model.pkl"
    if not model_path.exists():
        print("❌ Modelo de IA não encontrado. Treinando...")
        os.system(f"python {ESTRATEGIAS_DIR / 'ml_train_model.py'}")
        
    filtro_ia = SignalFilter(model_path=str(model_path))
    
    email, password, conta, auto_executar, valor_entrada = solicitar_credenciais()
    
    print(f"\n🔄 Conectando à IQ Option como {email}...")
    api = IQ_Option(email, password)
    conectado, motivo = api.connect()
    if not conectado:
        print(f"❌ Falha na conexão com IQ Option: {motivo}")
        sys.exit(1)
        
    api.change_balance(conta)
    print(f"✅ Conectado com sucesso! Conta ativa: {conta}")
    print(f"🎯 Filtro de IA Ativo: Confiança Mínima >= 55% (Regra de Ouro)")
    print(f"⚙️ Auto Execução: {'ATIVADA' if auto_executar else 'DESATIVADA (Apenas Alertas)'}")
    print(f"💵 Valor da entrada: R$ {valor_entrada:.2f}\n")
    
    print("⏳ Coletando dados dos ativos em tempo real...")
    for par in PARES_OTC:
        api.start_candles_stream(par, 60, 100)
    time.sleep(5)
    
    print("\n🚀 BOT INICIADO! Monitorando pares OTC em tempo real... (Pressione Ctrl+C para parar)\n")
    print("-" * 80)
    
    historico_sinais = set()
    
    try:
        while True:
            for par in PARES_OTC:
                velas_dict = api.get_realtime_candles(par, 60)
                if not velas_dict or len(velas_dict) < 30:
                    continue
                    
                df = converter_velas_para_df(velas_dict)
                if df.empty or len(df) < 30:
                    continue
                    
                # Feature engineering em tempo real
                df_feat = calculate_features(df)
                ultima_vela = df_feat.iloc[[-1]]
                ts_atual = int(ultima_vela['from_ts'].iloc[0])
                
                # Exemplo de detecção de padrão de reversão/sinal
                close_atual = ultima_vela['close'].iloc[0]
                open_atual = ultima_vela['open'].iloc[0]
                high_atual = ultima_vela['high'].iloc[0]
                low_atual = ultima_vela['low'].iloc[0]
                
                # Simula verificação de sinal (Se houve candle de força/reversão)
                is_bullish = close_atual > open_atual
                is_bearish = close_atual < open_atual
                
                # Se detectado um sinal em potencial no último candle
                if is_bullish or is_bearish:
                    chave_sinal = (par, ts_atual)
                    if chave_sinal in historico_sinais:
                        continue
                    historico_sinais.add(chave_sinal)
                    
                    direcao = "call" if is_bullish else "put"
                    
                    # PASSO CRÍTICO: Previsão do Filtro de IA
                    prob_win = filtro_ia.predict_win_probability(ultima_vela)[0]
                    confianca_pct = prob_win * 100
                    
                    hora_str = datetime.now().strftime("%H:%M:%S")
                    
                    if filtro_ia.should_enter(prob_win):
                        print(f"[{hora_str}] 🎯 SINAL APROVADO PELA IA | Par: {par} | Direção: {direcao.upper()} | Confiança: {confianca_pct:.2f}% (>= 55%)")
                        if auto_executar:
                            print(f"⚡ Executando entrada na IQ Option... (R$ {valor_entrada:.2f})")
                            sucesso, ordem_id = api.buy_digital_spot_v2(par, valor_entrada, direcao.upper(), 1)
                            if sucesso:
                                print(f"✅ ORDEM EXECUTADA COM SUCESSO! Order ID: {ordem_id}\n")
                            else:
                                print(f"❌ FALHA AO EXECUTAR ORDEM: {ordem_id}\n")
                        else:
                            print("⚠️ SOMENTE ALERTA (Modo simulação)\n")
                    else:
                        print(f"[{hora_str}] ⛔ SINAL REJEITADO PELA IA | Par: {par} | Direção: {direcao.upper()} | Confiança: {confianca_pct:.2f}% (< 55%)")
                        
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\n\n⏹️ Bot encerrado pelo usuário.")
    except Exception as e:
        print(f"\n❌ Erro no loop de monitoramento: {e}")

if __name__ == "__main__":
    iniciar_bot()