import sys
from pathlib import Path
sys.path.append(str(Path(r"c:\iq-full-www\polarium").resolve()))

def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
configure_console()

import time
from polariumapi.client import PolariumClient

def main():
    print("Iniciando headless=True...")
    try:
        client = PolariumClient.from_saved_session(headless=True)
        print("Conectando...")
        client.connect()
        print("Selecionando conta DEMO...")
        client.select_account("DEMO")
        print("Tentando abrir ordem em BTCUSD_otc...")
        response = client.open_operation(
            symbol="BTCUSD_otc", 
            amount=2.0, 
            direction="UP", 
            expiration_ts=int(time.time()) + 60, 
            expiration_tf_sec=60, 
            client_request_id="teste_headless_1"
        )
        print(f"Resultado: {response}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"ERRO: {e}")
    finally:
        if 'client' in locals() and hasattr(client, 'driver') and client.driver:
            client.driver.quit()

if __name__ == "__main__":
    main()
