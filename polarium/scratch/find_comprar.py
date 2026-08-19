import time
import sys
sys.stdout.reconfigure(encoding="utf-8")
from polariumapi.client import PolariumClient

def main():
    print("Iniciando busca do botão COMPRAR...")
    client = PolariumClient.from_saved_session(headless=False)
    client.connect()
    driver = client.driver
    
    print("Conectado. Aguardando 10 segundos para carregar a interface...")
    time.sleep(10)
    
    js = """
        let all = document.querySelectorAll('*');
        let found = [];
        for (let el of all) {
            if (el.innerText && (el.innerText.includes('COMPRAR') || el.innerText.includes('Comprar') || el.innerText.includes('comprar'))) {
                found.push({
                    tag: el.tagName,
                    className: el.className,
                    id: el.id,
                    testId: el.getAttribute('data-test-id'),
                    outerHTML: el.outerHTML.substring(0, 300)
                });
            }
        }
        return found;
    """
    try:
        results = driver.execute_script(js)
        print(f"Encontrados {len(results)} elementos com 'COMPRAR':")
        for idx, res in enumerate(results):
            print(f"\n--- Elemento {idx} ---")
            print(f"TAG: {res['tag']}")
            print(f"CLASS: {res['className']}")
            print(f"TEST-ID: {res['testId']}")
            print(f"HTML: {res['outerHTML']}")
    except Exception as e:
        print(f"Erro: {e}")
        
    driver.quit()

if __name__ == "__main__":
    main()
