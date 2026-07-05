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
    
    # Extraer la estructura de datos sanitizada sin JSON.stringify circular
    vue_data_dump = page.evaluate("""
        () => {
            const dump = [];
            const app = document.getElementById('app');
            if (app && app.__vue__) {
                function traverse(comp, depth) {
                    const data_keys = comp.$data ? Object.keys(comp.$data) : [];
                    
                    const info = {
                        depth: depth,
                        name: comp.$options ? comp.$options._componentTag || comp.$options.name : 'unknown',
                        data_values: {}
                    };
                    
                    if (comp.$data) {
                        for (const k of data_keys) {
                            try {
                                const val = comp.$data[k];
                                if (val === null || val === undefined) {
                                    info.data_values[k] = val;
                                } else if (typeof val === 'object') {
                                    if (Array.isArray(val)) {
                                        info.data_values[k] = {
                                            type: 'array',
                                            length: val.length,
                                            keys: val.length > 0 ? Object.keys(val[0]) : []
                                        };
                                    } else {
                                        info.data_values[k] = { 
                                            type: 'object', 
                                            keys: Object.keys(val).filter(x => !x.startsWith('$') && !x.startsWith('_'))
                                        };
                                    }
                                } else if (typeof val !== 'function') {
                                    info.data_values[k] = val;
                                }
                            } catch(e) {
                                info.data_values[k] = 'error_evaluating';
                            }
                        }
                    }
                    
                    if (data_keys.length > 0) {
                        dump.push(info);
                    }
                    
                    if (comp.$children) {
                        for (const child of comp.$children) {
                            traverse(child, depth + 1);
                        }
                    }
                }
                traverse(app.__vue__, 0);
            }
            return dump;
        }
    """)
    
    print("\nEstructura de Componentes Vue.js y sus datos:")
    print(json.dumps(vue_data_dump, indent=2, ensure_ascii=False))
    
    browser.close()
