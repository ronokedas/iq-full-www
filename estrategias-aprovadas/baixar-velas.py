"""Coletor massivo de candles M1 da IQ Option (OTC).

Este script varre TODOS os ativos OTC disponíveis na plataforma (Forex, Crypto, Commodities, Índices)
e baixa automaticamente as velas de 1 minuto dos últimos 30 dias.

Executar:
  python baixar-velas.py

O programa solicita e-mail/senha no terminal, usa conta DEMO (PRACTICE) 
e salva os dados em formato Parquet na pasta 'dados/iq_option/m1'.
"""
from __future__ import annotations

import getpass
import json
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from iqoptionapi.stable_api import IQ_Option
except ImportError as exc:
    raise SystemExit(
        "Biblioteca ausente. Execute: pip install iqoptionapi"
    ) from exc

try:
    import pandas as pd
except ImportError as exc:
    raise SystemExit("Instale pandas e pyarrow: pip install pandas pyarrow") from exc

# Configurações
OUT = Path(__file__).resolve().parent / "dados" / "iq_option" / "m1"
DIAS_HISTORICO = 30
MAX_PARES = 60  # Limite de segurança para não sobrecarregar a requisição inicial


def norm_symbol(value: str) -> str:
    """Normaliza o nome do ativo para o padrão XXX-OTC."""
    if not value:
        return ""
    value = str(value).split(".")[-1].upper()
    # Remove sufixos antigos e padroniza
    value = value.replace("_OTC", "-OTC").replace("OTC_", "-OTC")
    if not value.endswith("-OTC"):
        # Se não tem OTC no nome, ignora (não é OTC)
        return ""
    return value


def coletar_lista_otc(api: IQ_Option) -> list[str]:
    """Varre todos os grupos da API e extrai ativos OTC habilitados."""
    print("🔍 Varrendo catálogo completo da IQ Option em busca de ativos OTC...")
    found_symbols = set()
    
    try:
        # Tenta obter o catálogo V2 (mais completo)
        catalog = api.get_all_init_v2()
        if not catalog:
            # Fallback para método antigo se V2 falhar
            catalog = api.get_all_init()
            
        if not isinstance(catalog, dict):
            print("⚠️ Catálogo retornado em formato inesperado.")
            return []

        # Grupos comuns onde existem ativos OTC
        grupos_para_varrer = ["turbo", "binary", "cfd", "digital", "forex", "crypto"]
        
        for grupo_nome in grupos_para_varrer:
            grupo_dados = catalog.get(grupo_nome, {})
            if not isinstance(grupo_dados, dict):
                continue
                
            actives = grupo_dados.get("actives", {})
            if not isinstance(actives, dict):
                continue

            for key, item in actives.items():
                if not isinstance(item, dict):
                    continue
                
                # Verifica se está habilitado e não suspenso
                if not item.get("enabled", False) or item.get("is_suspended", False):
                    continue
                
                symbol_raw = item.get("name", "") or item.get("underlying", "")
                symbol_norm = norm_symbol(symbol_raw)
                
                if symbol_norm:
                    found_symbols.add(symbol_norm)

    except Exception as e:
        print(f"⚠️ Erro ao varrer catálogo: {e}")
        # Fallback manual caso a varredura automática falhe completamente
        print("Usando lista de fallback de pares conhecidos...")
        fallback = {
            "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC", "USDCAD-OTC",
            "USDCHF-OTC", "NZDUSD-OTC", "EURJPY-OTC", "GBPJPY-OTC", "EURGBP-OTC",
            "AUDCAD-OTC", "AUDJPY-OTC", "AUDNZD-OTC", "CADJPY-OTC", "CHFJPY-OTC",
            "EURAUD-OTC", "EURCAD-OTC", "EURCHF-OTC", "EURNZD-OTC", "GBPAUD-OTC",
            "GBPCAD-OTC", "GBPCHF-OTC", "GBPNZD-OTC", "NZDCAD-OTC", "NZDJPY-OTC",
            "NZDCHF-OTC", "USDINR-OTC", "USDSGD-OTC", "USDHKD-OTC", "USDMXN-OTC",
            "USDZAR-OTC", "USDBRL-OTC", "USDRUB-OTC", "USDTRY-OTC", "USDXOF-OTC",
            "BTCUSD-OTC", "ETHUSD-OTC", "LTCUSD-OTC", "XRPUSD-OTC", "ADAUSD-OTC",
            "DOGEUSD-OTC", "SOLUSD-OTC", "MATICUSD-OTC", "DOTUSD-OTC", "AVAXUSD-OTC",
            "LINKUSD-OTC", "UNIUSD-OTC", "ATOMUSD-OTC", "XLMUSD-OTC", "ALGOUSD-OTC",
            "GOLD-OTC", "SILVER-OTC", "OIL-OTC", "BRENT-OTC", "NGAS-OTC",
            "SPX500-OTC", "NAS100-OTC", "DJI30-OTC", "GER40-OTC", "UK100-OTC"
        }
        return sorted(list(fallback))

    symbols_list = sorted(list(found_symbols))
    print(f"✅ Encontrados {len(symbols_list)} ativos OTC habilitados.")
    return symbols_list


def main() -> int:
    print("=" * 60)
    print("🤖 SUPER DOWNLOAD DE VELAS OTC (IQ OPTION)")
    print("=" * 60)
    
    email = input("📧 E-mail da IQ Option: ").strip()
    if not email:
        print("❌ E-mail obrigatório.")
        return 2
        
    password = getpass.getpass("🔑 Senha (não será exibida): ")
    if not password:
        print("❌ Senha obrigatória.")
        return 2

    # Validação simples de dias
    try:
        dias_input = input(f"📅 Quantos dias de histórico? [{DIAS_HISTORICO}]: ").strip()
        dias = int(dias_input) if dias_input else DIAS_HISTORICO
        dias = max(1, min(90, dias))  # Limite de segurança 90 dias
    except ValueError:
        dias = DIAS_HISTORICO

    print(f"\n🚀 Iniciando conexão com {dias} dias de histórico...")
    
    api = IQ_Option(email, password)
    # Conecta com timeout
    check, reason = api.connect()
    
    # Limpa senha da memória
    password = "" 
    
    if not check:
        print(f"❌ Falha na conexão: {reason}")
        return 3
    
    # Força conta Demo para não arriscar saldo real durante download
    api.change_balance("PRACTICE")
    print("✅ Conectado! Conta: PRACTICE (DEMO)")

    try:
        # 1. Coletar lista dinâmica de pares
        todos_pares = coletar_lista_otc(api)
        
        if not todos_pares:
            print("❌ Nenhum ativo OTC encontrado ou erro na coleta.")
            return 4

        # Limita a quantidade para não travar o script se houver centenas
        pares_selecionados = todos_pares[:MAX_PARES]
        print(f"📋 Processando os primeiros {len(pares_selecionados)} pares encontrados:")
        print(f"   {', '.join(pares_selecionados[:5])} ... e mais {len(pares_selecionados)-5}")

        # Preparar pastas
        OUT.mkdir(parents=True, exist_ok=True)
        
        # Timestamps
        end_ts = int(time.time())
        start_ts = end_ts - (dias * 86400)
        
        manifest = {
            "schema": 1,
            "broker": "IQOPTION",
            "account": "PRACTICE",
            "timeframe": "1m",
            "days": dias,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "total_pairs": len(pares_selecionados),
            "pairs": {}
        }

        print("\n⬇️  Iniciando download das velas...\n")

        # 2. Loop de Download
        for idx, symbol in enumerate(pares_selecionados, 1):
            print(f"[{idx}/{len(pares_selecionados)}] Baixando {symbol}...", end=" ", flush=True)
            
            rows_dict = {}
            cursor = start_ts
            tentativas_erro = 0
            
            while cursor < end_ts:
                # Define janela de busca (max 1000 velas por chamada da API)
                window_end = min(end_ts, cursor + (1000 * 60))
                
                try:
                    # API Call: get_candles(active, period, count, end_time)
                    # Period 60 = 1 minuto
                    candles = api.get_candles(symbol, 60, 1000, window_end)
                    
                    if not candles:
                        # Se não retornou nada, pode ser fim dos dados ou erro temporário
                        if tentativas_erro > 2:
                            break 
                        tentativas_erro += 1
                        time.sleep(1)
                        continue
                    
                    # Processar velas recebidas
                    for candle in candles:
                        ts = int(candle.get("from", 0))
                        # Filtra duplicatas e fora do range
                        if start_ts <= ts < end_ts and ts not in rows_dict:
                            rows_dict[ts] = {
                                "symbol": symbol,
                                "timeframe": "1m",
                                "from_ts": ts,
                                "to_ts": int(candle.get("to", ts + 60)),
                                "open": float(candle.get("open", 0)),
                                "high": float(candle.get("max", candle.get("high", 0))),
                                "low": float(candle.get("min", candle.get("low", 0))),
                                "close": float(candle.get("close", 0)),
                                "volume": float(candle.get("volume", 0)),
                            }
                    
                    # Avança o cursor
                    cursor = window_end
                    time.sleep(0.15)  # Respeito à rate limit
                    
                except Exception as e:
                    print(f"\n   ⚠️ Erro em {symbol}: {str(e)[:50]}")
                    time.sleep(2)
                    cursor = window_end # Avança mesmo com erro para não loop infinito
                    break

            # Salvar Arquivo Parquet
            if rows_dict:
                df = pd.DataFrame(sorted(rows_dict.values(), key=lambda x: x["from_ts"]))
                filename_safe = symbol.replace("-", "_").replace("/", "_")
                filename = f"{filename_safe}.parquet"
                
                df.to_parquet(OUT / filename, index=False)
                
                manifest["pairs"][symbol] = {
                    "file": filename,
                    "rows": len(df),
                    "start_date": datetime.fromtimestamp(df["from_ts"].iloc[0]).isoformat(),
                    "end_date": datetime.fromtimestamp(df["from_ts"].iloc[-1]).isoformat()
                }
                print(f"Sucesso ({len(df)} velas)")
            else:
                print("⚠️ Sem dados retornados")
                manifest["pairs"][symbol] = {"file": None, "rows": 0, "error": "No data"}

        # Salvar Manifesto
        manifest_file = OUT.parent / "manifest_otc.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            
        print("\n" + "=" * 60)
        print(f"✅ CONCLUÍDO!")
        print(f"📂 Dados salvos em: {OUT}")
        print(f"📄 Manifesto gerado: {manifest_file}")
        print(f"📊 Total de pares processados: {len(pares_selecionados)}")
        print("=" * 60)
        return 0

    except KeyboardInterrupt:
        print("\n⚠️ Interrompido pelo usuário.")
        return 1
    finally:
        try:
            api.close()
        except:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
