"""Intercept WebSocket traffic from Polarium by monkey-patching WebSocket before page load."""
import time
import sys
import json
sys.stdout.reconfigure(encoding="utf-8")

from selenium import webdriver
from pathlib import Path
from app_runtime import data_path

def main():
    print("=== Interceptação WebSocket da Polarium Broker ===\n")
    
    profile_dir = data_path("polarium_edge_profile")
    
    options = webdriver.EdgeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(f"--user-data-dir={profile_dir.resolve()}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    print("Iniciando Edge...")
    driver = webdriver.Edge(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    # Inject WebSocket interceptor BEFORE the page loads
    print("Injetando interceptador de WebSocket...")
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': """
        (function() {
            window._wsConnections = [];
            window._wsFrames = [];
            
            const OriginalWebSocket = window.WebSocket;
            
            window.WebSocket = function(url, protocols) {
                console.log('[WS-INTERCEPT] New WebSocket:', url);
                window._wsConnections.push({url: url, time: Date.now()});
                
                let ws;
                if (protocols) {
                    ws = new OriginalWebSocket(url, protocols);
                } else {
                    ws = new OriginalWebSocket(url);
                }
                
                const connIdx = window._wsConnections.length - 1;
                
                ws.addEventListener('message', function(event) {
                    let data = event.data;
                    if (typeof data === 'string') {
                        window._wsFrames.push({
                            connIdx: connIdx,
                            direction: 'RECV',
                            data: data.substring(0, 1000),
                            time: Date.now()
                        });
                    }
                });
                
                const origSend = ws.send.bind(ws);
                ws.send = function(data) {
                    let str = typeof data === 'string' ? data : '[binary]';
                    window._wsFrames.push({
                        connIdx: connIdx,
                        direction: 'SENT',
                        data: str.substring(0, 1000),
                        time: Date.now()
                    });
                    return origSend(data);
                };
                
                return ws;
            };
            
            // Copy static properties
            window.WebSocket.CONNECTING = OriginalWebSocket.CONNECTING;
            window.WebSocket.OPEN = OriginalWebSocket.OPEN;
            window.WebSocket.CLOSING = OriginalWebSocket.CLOSING;
            window.WebSocket.CLOSED = OriginalWebSocket.CLOSED;
            window.WebSocket.prototype = OriginalWebSocket.prototype;
        })();
    """})
    
    print("Navegando para o traderoom...")
    driver.get("https://trade.polariumbroker.com/traderoom")
    
    print("Aguardando 20 segundos para a interface carregar e conexões WebSocket serem estabelecidas...")
    time.sleep(20)
    
    print(f"URL atual: {driver.current_url}\n")
    
    # Collect captured data
    connections = driver.execute_script("return window._wsConnections || [];")
    frames = driver.execute_script("return window._wsFrames || [];")
    
    print(f"=== WebSocket Connections: {len(connections)} ===")
    for idx, conn in enumerate(connections):
        print(f"  [{idx}] URL: {conn['url']}")
    
    print(f"\n=== WebSocket Frames capturados: {len(frames)} ===")
    
    # Group frames by connection
    for conn_idx in range(len(connections)):
        conn_frames = [f for f in frames if f['connIdx'] == conn_idx]
        sent_frames = [f for f in conn_frames if f['direction'] == 'SENT']
        recv_frames = [f for f in conn_frames if f['direction'] == 'RECV']
        print(f"\n--- Connection [{conn_idx}]: {connections[conn_idx]['url']} ---")
        print(f"    Enviados: {len(sent_frames)} | Recebidos: {len(recv_frames)}")
        
        print(f"\n  Primeiros 10 frames ENVIADOS:")
        for f in sent_frames[:10]:
            print(f"    SENT: {f['data'][:200]}")
            
        print(f"\n  Primeiros 10 frames RECEBIDOS:")
        for f in recv_frames[:10]:
            print(f"    RECV: {f['data'][:200]}")
    
    # Save full data to file for analysis
    output = {
        "connections": connections,
        "frames": frames[:200]  # first 200 frames
    }
    outfile = Path("scratch/ws_capture_data.json")
    outfile.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDados completos salvos em: {outfile}")
    
    driver.quit()
    print("\n=== Captura finalizada ===")

if __name__ == "__main__":
    main()
