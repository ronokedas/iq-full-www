import time
import sys
sys.stdout.reconfigure(encoding="utf-8")
from selenium import webdriver

options = webdriver.EdgeOptions()
options.add_argument("--start-maximized")
options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)

print("Starting driver...")
driver = webdriver.Edge(options=options)

driver.execute_cdp_cmd('Network.setUserAgentOverride', {"userAgent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

print("Navigating to traderoom...")
driver.get("https://trade.polariumbroker.com/traderoom")
time.sleep(5)

print("Current URL:", driver.current_url)

body = driver.execute_script("return document.body.innerText;")
print("BODY TEXT (first 500 chars):")
print(body[:500])

driver.quit()
