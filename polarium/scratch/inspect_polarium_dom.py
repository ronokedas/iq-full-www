import time
import sys
sys.stdout.reconfigure(encoding="utf-8")
from polariumapi.client import PolariumClient

def main():
    print("Iniciando inspeção...")
    client = PolariumClient.from_saved_session(headless=False)
    client.connect()
    driver = client.driver
    print("Navegador conectado. Analisando DOM...")
    
    iframes = driver.find_elements(by="tag name", value="iframe")
    print(f"Iframes encontrados: {len(iframes)}")
    
    js_diagnostic = """
        return document.body.innerHTML.substring(0, 1500) + "\\n...\\n" + document.body.innerHTML.slice(-1500);
    """
    
    try:
        diag = driver.execute_script(js_diagnostic)
        print("--- BODY MAIN HTML ---")
        print(diag)
    except Exception as e:
        print(f"Erro JS: {e}")
    
    for idx, f in enumerate(iframes):
        print(f"\n--- Iframe {idx}: id={f.get_attribute('id')} src={f.get_attribute('src')} ---")
        try:
            driver.switch_to.frame(f)
            time.sleep(1)
            diag = driver.execute_script(js_diagnostic)
            print(f" Acima/Call/Green: {len(diag['acima'])}")
            for x in diag['acima'][:5]: print(f"   {x}")
            print(f" Abaixo/Put/Red: {len(diag['abaixo'])}")
            for x in diag['abaixo'][:5]: print(f"   {x}")
            print(f" Possíveis botões: {len(diag['btnClasses'])}")
            for x in diag['btnClasses'][:5]: print(f"   {x}")
            driver.switch_to.default_content()
        except Exception as e:
            print(f"Erro ao acessar iframe {idx}: {e}")
            driver.switch_to.default_content()
        
    driver.quit()

if __name__ == "__main__":
    main()
