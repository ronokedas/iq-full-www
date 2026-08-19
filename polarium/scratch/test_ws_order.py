"""Quick test with correct expiration timing."""
import time, sys, json, asyncio
sys.stdout.reconfigure(encoding="utf-8")
import websockets

WS_URL = "wss://ws.trade.polariumbroker.com:443/echo/websocket"
SSID = "c0953c8f14aeda34327bfbe8f6a7ebfc"

async def main():
    print("=== Teste BTCUSD-OTC com expiração correta ===\n")
    
    async with websockets.connect(WS_URL, max_size=20_000_000) as ws:
        # Authenticate
        await ws.send(json.dumps({
            "name": "authenticate", "request_id": "auth_1",
            "msg": {"ssid": SSID, "protocol": 3, "session_id": "", "client_session_id": ""}
        }))
        for _ in range(5):
            resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
            if resp.get("name") == "authenticated":
                print("✅ Autenticado!")
            if resp.get("name") == "front":
                break
        
        await ws.send(json.dumps({
            "name": "setOptions", "request_id": "opt_1",
            "msg": {"sendResults": True}
        }))
        
        # Drain
        for _ in range(3):
            try: await asyncio.wait_for(ws.recv(), timeout=1)
            except: break
        
        # Calculate expiration: next minute that is at least 30s away
        now_ts = int(time.time())
        next_min = now_ts + (60 - (now_ts % 60))
        if next_min - now_ts < 30:
            # Too close to the next minute, use the one after
            exp_ts = next_min + 60
        else:
            exp_ts = next_min
        
        secs_until = exp_ts - now_ts
        print(f"⏰ Agora: {now_ts} | Expiração: {exp_ts} | Faltam: {secs_until}s")
        
        order_msg = {
            "name": "sendMessage", "request_id": "order_btc",
            "msg": {
                "name": "binary-options.open-option", "version": "1.0",
                "body": {
                    "user_balance_id": 1249244479,  # DEMO
                    "active_id": 2270,  # BTCUSD-OTC
                    "option_type_id": 3,  # turbo
                    "direction": "call",  # COMPRAR
                    "expired": exp_ts,
                    "price": 2
                }
            }
        }
        
        print(f"🚀 Enviando COMPRA BTCUSD-OTC | $2 DEMO | exp em {secs_until}s")
        await ws.send(json.dumps(order_msg))
        
        # Monitor responses
        print("\nMonitorando respostas...\n")
        start = time.time()
        while time.time() - start < 15:
            try:
                resp_raw = await asyncio.wait_for(ws.recv(), timeout=2)
                resp = json.loads(resp_raw)
                name = resp.get("name", "")
                req_id = resp.get("request_id", "")
                
                if name in ("timeSync", "heartbeat") or "candle" in name.lower():
                    continue
                
                if req_id == "order_btc" or "option" in name.lower() or "order" in name.lower() or "position" in name.lower():
                    print(f"🔴 [{name}] req={req_id}:")
                    print(f"   {json.dumps(resp, indent=2, ensure_ascii=False)[:800]}")
                    
                    if name == "option":
                        msg = resp.get("msg", {})
                        if isinstance(msg, dict):
                            if "id" in msg:
                                print(f"\n   ✅✅✅ ORDEM ABERTA COM SUCESSO! ID: {msg['id']}")
                                print(f"   Detalhes: active_id={msg.get('act')}, direction={msg.get('dir')}, amount={msg.get('amount')}")
                            elif "message" in msg:
                                print(f"\n   ❌ REJEITADA: {msg['message']}")
                elif name == "result":
                    print(f"📋 result req={req_id}: {json.dumps(resp.get('msg',{}))[:200]}")
                    
            except asyncio.TimeoutError:
                continue
        
        print("\n=== Finalizado ===")

if __name__ == "__main__":
    asyncio.run(main())
