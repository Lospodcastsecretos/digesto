import time
import json
from playwright.sync_api import sync_playwright

SITE_URL = "https://digestoaltagracia.com.ar"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    
    page.goto(f"{SITE_URL}/#/detalles/8593", wait_until="networkidle")
    time.sleep(4)
    
    # Buscar recursivamente propiedades de forma segura
    scan_result = page.evaluate("""
        () => {
            const matches = [];
            const app = document.getElementById('app');
            
            function isTarget(obj) {
                if (!obj) return false;
                try {
                    // Buscar si tiene propiedades tipicas de la publicacion
                    if (obj.id === 8593 || String(obj.numero) === "86" || String(obj.archivo).includes("8593")) {
                        return true;
                    }
                } catch(e) {}
                return false;
            }
            
            function scan(comp, depth) {
                if (depth > 12) return;
                
                if (comp.$data) {
                    for (const k of Object.keys(comp.$data)) {
                        try {
                            const val = comp.$data[k];
                            if (val && typeof val === 'object') {
                                if (isTarget(val)) {
                                    matches.push({
                                        component: comp.$options ? comp.$options._componentTag || comp.$options.name : 'unknown',
                                        key: k,
                                        keys: Object.keys(val),
                                        id: val.id,
                                        numero: val.numero,
                                        titulo: val.titulo,
                                        archivo: val.archivo,
                                        // Ojo, si tiene array de archivos, buscar ahi
                                        archivos: val.archivos ? val.archivos.map(x => Object.keys(x)) : null
                                    });
                                }
                            }
                        } catch(e) {}
                    }
                }
                
                if (comp.$children) {
                    for (const child of comp.$children) {
                        scan(child, depth + 1);
                    }
                }
            }
            
            if (app && app.__vue__) {
                scan(app.__vue__, 0);
            }
            return matches;
        }
    """)
    
    print("\nCoincidencias encontradas en memoria de Vue (seguro):")
    print(json.dumps(scan_result, indent=2, ensure_ascii=False))
    
    browser.close()
