import time
import json
from playwright.sync_api import sync_playwright

SITE_URL = "https://digestoaltagracia.com.ar"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    print("Navegando y buscando...")
    page.goto(f"{SITE_URL}/#/Index", wait_until="networkidle")
    time.sleep(2)
    
    # Hacer una busqueda para poblar localStorage
    search_input = page.wait_for_selector('input[type="text"]')
    search_input.fill("a")
    buscar_btn = page.wait_for_selector('button:has-text("BUSCAR"), .v-btn:has-text("BUSCAR")')
    buscar_btn.click()
    time.sleep(6) # esperar que cargue todo
    
    # Consultar localStorage y las variables globales de window
    result = page.evaluate("""
        () => {
            const keys = [];
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                keys.push({
                    key: k,
                    value_preview: localStorage.getItem(k).substring(0, 1000)
                });
            }
            return keys;
        }
    """)
    
    print("\nContenido de localStorage:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    browser.close()
