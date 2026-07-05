import json
import time
from playwright.sync_api import sync_playwright

SITE_URL = "https://digestoaltagracia.com.ar"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    # Capturar respuestas de red
    api_responses = []
    def interceptar(response):
        if "/api/" in response.url:
            try:
                api_responses.append({
                    "url": response.url,
                    "status": response.status,
                    "data": response.json()
                })
            except Exception:
                pass
                
    page.on("response", interceptar)
    
    # Ir al detalle del documento 14346
    print("Navegando al detalle del documento 14346...")
    page.goto(f"{SITE_URL}/#/detalles/14346", wait_until="networkidle")
    time.sleep(5)
    
    print("\nRespuestas de API capturadas:")
    for resp in api_responses:
        print(f"[{resp['status']}] {resp['url']}")
        # Imprimir parte de la respuesta
        print(json.dumps(resp['data'], indent=2)[:1000])
        print("-" * 50)
        
    browser.close()
