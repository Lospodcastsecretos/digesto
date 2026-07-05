import json
import time
from playwright.sync_api import sync_playwright

SITE_URL = "https://digestoaltagracia.com.ar"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
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
    
    print("Abriendo el index...")
    page.goto(f"{SITE_URL}/#/Index", wait_until="networkidle")
    time.sleep(2)
    
    # Escribir 'a' y hacer clic en buscar para tener resultados
    print("Buscando...")
    search_input = page.wait_for_selector('input[type="text"]')
    search_input.fill("a")
    time.sleep(0.5)
    buscar_btn = page.wait_for_selector('button:has-text("BUSCAR"), .v-btn:has-text("BUSCAR")')
    buscar_btn.click()
    
    time.sleep(5) # esperar que cargue la lista
    
    # Hacer clic en la primera tarjeta o su enlace de detalle
    print("Haciendo clic en el primer resultado...")
    card_links = page.query_selector_all("a[href*='detalles']")
    if card_links:
        print(f"Encontrados {len(card_links)} enlaces de detalle. Click en el primero.")
        card_links[0].click()
        time.sleep(5) # esperar que cargue el detalle
    else:
        print("No se encontraron enlaces de detalle. Intentando clickear v-card.")
        first_card = page.query_selector(".v-card")
        if first_card:
            first_card.click()
            time.sleep(5)
            
    print("\nLlamadas de red de la API capturadas:")
    for resp in api_responses:
        if "categorias" not in resp["url"] and "tipos" not in resp["url"] and "descriptores" not in resp["url"]:
            print(f"[{resp['status']}] {resp['url']}")
            print(json.dumps(resp['data'], indent=2)[:800])
            print("-" * 60)
            
    browser.close()
