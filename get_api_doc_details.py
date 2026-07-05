import re

content_path = r"C:\Users\Fedeparisi\.gemini\antigravity\brain\25cb2825-fab3-4e23-89b5-2cc5da115a9f\.system_generated\steps\28\content.md"

with open(content_path, "r", encoding="utf-8") as f:
    content = f.read()

# Buscar el patron
pattern = r'e\.b=i,e\.a=r;var o="https://digestoaltagracia\.com\.ar/api/documentos"'
matches = list(re.finditer(pattern, content))

if matches:
    print(f"Encontradas {len(matches)} coincidencias")
    for m in matches:
        start = max(0, m.start() - 600)
        end = min(len(content), m.end() + 200)
        print("\n--- Fragmento del JS bundle ---")
        print(content[start:end])
else:
    print("No se encontro el patron especificado")
