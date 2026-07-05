import time
import json
from playwright.sync_api import sync_playwright

SITE_URL = "https://digestoaltagracia.com.ar"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    print("Navegando a la norma 8593...")
    page.goto(f"{SITE_URL}/#/detalles/8593", wait_until="networkidle")
    time.sleep(4)
    
    print("Inspeccionando el estado interno del componente de detalles...")
    
    # Extraer el objeto publicacion completo de Vue.js
    vue_state = page.evaluate("""
        () => {
            const app = document.getElementById('app');
            if (app && app.__vue__) {
                const vm = app.__vue__;
                
                // Buscar componente de detalle
                function findDetailComponent(comp, depth) {
                    if (depth > 10) return null;
                    
                    const data = comp.$data || {};
                    // Si el componente tiene la propiedad 'publicacion' o 'documento'
                    if (data.publicacion && typeof data.publicacion === 'object') {
                        return data.publicacion;
                    }
                    if (data.documento && typeof data.documento === 'object') {
                        return data.documento;
                    }
                    
                    if (comp.$children) {
                        for (const child of comp.$children) {
                            const found = findDetailComponent(child, depth + 1);
                            if (found) return found;
                        }
                    }
                    return null;
                }
                
                return findDetailComponent(vm, 0);
            }
            return null;
        }
    """)
    
    if vue_state:
        print("\nObjeto de publicacion/documento encontrado en Vue:")
        print(json.dumps(vue_state, indent=2, ensure_ascii=False))
    else:
        print("\nNo se pudo encontrar el estado del componente. Imprimiendo variables globales de window:")
        globals_list = page.evaluate("() => Object.keys(window)")
        print(globals_list[:30])
        
    browser.close()
