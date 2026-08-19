import json
import time
import asyncio
import sys
import csv
from datetime import datetime
from pathlib import Path

# Garante UTF-8 no Windows
sys.stdout.reconfigure(encoding="utf-8")
import websockets

WS_URL = "wss://ws.trade.polariumbroker.com:443/echo/websocket"
SSID = "c0953c8f14aeda34327bfbe8f6a7ebfc"
BACKTEST_DIR = Path(r"C:\iq-full-www\polarium\backtest")
CANDLES_TO_DOWNLOAD = 10080  # 7 dias em M1 (60s)

async def main():
    print(f"🚀 Iniciando download em lote (7 dias) dos pares OTC...")
    
    async with websockets.connect(WS_URL, max_size=20_000_000) as ws:
        req_counter = [0]
        def next_id():
            req_counter[0] += 1
            return str(req_counter[0])
            
        print("1. Autenticando...")
        await ws.send(json.dumps({
            "name": "authenticate", "request_id": "auth_1",
            "msg": {"ssid": SSID, "protocol": 3, "session_id": "", "client_session_id": ""}
        }))
        
        for _ in range(5):
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if resp.get("name") == "front":
                break
                
        print("2. Solicitando Initialization Data para encontrar os pares OTC...")
        await ws.send(json.dumps({
            "name": "sendMessage", "request_id": next_id(),
            "msg": {"name": "get-initialization-data", "version": "3.0", "body": {}}
        }))
        
        otc_pairs = {}
        for _ in range(15):
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if resp.get("name") == "initialization-data":
                data = resp.get("msg", {})
                for cat in ["binary", "turbo"]:
                    actives = data.get(cat, {}).get("actives", {})
                    for aid, info in actives.items():
                        ticker = info.get("ticker", "")
                        # Selecionar apenas pares OTC habilitados
                        if "OTC" in ticker.upper() and info.get("enabled"):
                            # Evitar duplicações, priorizando o ID do turbo
                            if ticker not in otc_pairs or cat == "turbo":
                                otc_pairs[ticker] = int(aid)
                break
                
        print(f"   ✅ Encontrados {len(otc_pairs)} pares OTC ativos.")
        
        # Iniciar downloads
        for ticker, active_id in sorted(otc_pairs.items()):
            print(f"\n📥 Baixando {ticker} (active_id={active_id})...")
            
            all_candles = []
            to_timestamp = int(time.time())
            candles_needed = CANDLES_TO_DOWNLOAD
            
            while candles_needed > 0:
                batch_size = min(candles_needed, 1000)
                req_id = next_id()
                
                await ws.send(json.dumps({
                    "name": "sendMessage",
                    "request_id": req_id,
                    "msg": {
                        "name": "get-candles",
                        "version": "2.0",
                        "body": {
                            "active_id": active_id,
                            "size": 60,
                            "to": to_timestamp,
                            "count": batch_size
                        }
                    }
                }))
                
                batch_received = False
                for _ in range(10):
                    try:
                        resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=3))
                        if resp.get("name") == "candles" and resp.get("request_id") == req_id:
                            candles = resp.get("msg", {}).get("candles", [])
                            if not candles:
                                print("   ⚠️ Histórico esgotado.")
                                candles_needed = 0
                                batch_received = True
                                break
                                
                            all_candles = candles + all_candles
                            candles_needed -= len(candles)
                            to_timestamp = candles[0]["from"] - 1
                            print(f"      Baixadas {len(candles)} velas. Faltam {candles_needed}...")
                            batch_received = True
                            break
                    except asyncio.TimeoutError:
                        continue
                        
                if not batch_received:
                    print("   ❌ Erro ao baixar lote. Pulando par.")
                    break
                    
                await asyncio.sleep(0.2)
                
            if all_candles:
                safe_ticker = ticker.replace("/", "_").replace("\\", "_")
                filename = BACKTEST_DIR / f"{safe_ticker}_M1_7days.csv"
                with open(filename, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["timestamp", "datetime", "open", "high", "low", "close", "volume"])
                    for c in all_candles:
                        ts = c.get("from", 0)
                        dt_str = datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                        writer.writerow([ts, dt_str, c.get("open",0), c.get("max",0), c.get("min",0), c.get("close",0), c.get("volume",0)])
                print(f"   💾 Salvo em: {filename.name} ({len(all_candles)} velas)")
                
    print("\n✅ PROCESSO FINALIZADO!")

if __name__ == "__main__":
    asyncio.run(main())
