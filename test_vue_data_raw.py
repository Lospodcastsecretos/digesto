import time
import json
from playwright.sync_api import sync_playwright

SITE_URL = "https://digestoaltagracia.com.ar"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    print("Cargando el index...")
    page.goto(f"{SITE_URL}/#/Index", wait_until="networkidle")
    time.sleep(2)
    
    print("Buscando...")
    search_input = page.wait_for_selector('input[type="text"]')
    search_input.fill("a")
    buscar_btn = page.wait_for_selector('button:has-text("BUSCAR"), .v-btn:has-text("BUSCAR")')
    buscar_btn.click()
    time.sleep(6) # esperar que cargue todo
    
    # Extraer el array completo de resultados desde el localStorage o desde el objeto Vue
    print("Extrayendo resultados desde el navegador...")
    results = page.evaluate("""
        () => {
            // Intentar leer de localStorage primero
            const local = localStorage.getItem('data');
            if (local) {
                try { return JSON.parse(local); } catch(e) {}
            }
            
            // Si no, buscar en el componente Vue
            const app = document.getElementById('app');
            if (app && app.__vue__) {
                const vm = app.__vue__;
                function findData(comp, depth) {
                    if (depth > 10) return null;
                    const d = comp.$data || {};
                    if (d.resultados && Array.isArray(d.resultados) && d.resultados.length > 0) return d.resultados;
                    if (d.normas && Array.isArray(d.normas) && d.normas.length > 0) return d.normas;
                    if (comp.$children) {
                        for (const child of comp.$children) {
                            const res = findData(child, depth + 1);
                            if (res) return res;
                        }
                    }
                    return null;
                }
                return findData(vm, 0);
            }
            return null;
        }
    """)
    
    if results:
        print(f"¡Éxito! Se obtuvieron {len(results)} registros.")
        print("\nPrimer registro en crudo:")
        print(json.dumps(results[0], indent=2, ensure_ascii=False))
        
        # Buscar uno con PDF
        print("\nBuscando uno que contenga archivo PDF...")
        for item in results:
            archivo = str(item.get("archivo", ""))
            if "pdf" in archivo.lower():
                print(json.dumps(item, indent=2, ensure_ascii=False))
                break
    else:
        print("No se encontraron resultados en el cliente.")
        
    browser.close()
