import time
import json
from playwright.sync_api import sync_playwright

SITE_URL = "https://digestoaltagracia.com.ar"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    # Capturar la respuesta JSON cruda de publicaciones (HTTP 200 o 201)
    api_data = []
    def interceptar(response):
        if "publicaciones" in response.url and response.status in (200, 201):
            try:
                api_data.append(response.json())
            except Exception:
                pass
                
    page.on("response", interceptar)
    
    print("Navegando y buscando...")
    page.goto(f"{SITE_URL}/#/Index", wait_until="networkidle")
    time.sleep(2)
    
    search_input = page.wait_for_selector('input[type="text"]')
    search_input.fill("a")
    buscar_btn = page.wait_for_selector('button:has-text("BUSCAR"), .v-btn:has-text("BUSCAR")')
    buscar_btn.click()
    
    # Esperar a que cargue
    time.sleep(5)
    
    if api_data:
        print("\n¡Datos de publicaciones capturados!")
        data_list = api_data[0]
        results = data_list.get("data", data_list) if isinstance(data_list, dict) else data_list
        if isinstance(results, list) and len(results) > 0:
            print("Campos del primer documento en crudo:")
            print(json.dumps(results[0], indent=2, ensure_ascii=False))
            print("\nCampos de otro documento con PDF si es posible:")
            for item in results:
                archivo_val = str(item.get("archivo", ""))
                if "pdf" in archivo_val.lower():
                    print(json.dumps(item, indent=2, ensure_ascii=False))
                    break
    else:
        print("No se capturo la respuesta de la API de publicaciones")
        
    browser.close()
