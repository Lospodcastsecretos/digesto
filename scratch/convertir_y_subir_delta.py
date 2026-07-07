import mammoth
import re
import requests
import sys
import time

import os
# Cargar .env manualmente si existe
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                parts = line.strip().split("=", 1)
                if len(parts) == 2:
                    os.environ[parts[0].strip()] = parts[1].strip().replace('"', '').replace("'", "")


TURSO_URL = os.environ.get('TURSO_URL')
TURSO_TOKEN = os.environ.get('TURSO_TOKEN')

# Configurar encoding
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def run_turso_query(sql, params=[], timeout=60):
    url = f"{TURSO_URL}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json"
    }
    
    formatted_params = []
    for p in params:
        if isinstance(p, int):
            formatted_params.append({"type": "integer", "value": str(p)})
        else:
            formatted_params.append({"type": "text", "value": str(p)})
            
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": formatted_params}},
            {"type": "close"}
        ]
    }
    
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            result = data["results"][0]
            if result["type"] == "error":
                return {"error": result["error"]["message"]}
            
            res_val = result["response"]["result"]
            cols = [c["name"] for c in res_val["cols"]]
            rows = []
            for r_val in res_val["rows"]:
                row_vals = [val["value"] if val else None for val in r_val]
                rows.append(dict(zip(cols, row_vals)))
            return {"rows": rows}
        else:
            return {"error": f"HTTP {r.status_code}: {r.text}"}
    except Exception as e:
        return {"error": str(e)}

def parse_norma_header(text):
    lines = [line.strip() for line in text.split("\n") if line.strip()][:10]
    tipo = None
    numero = None
    
    for line in lines:
        upper = line.upper()
        if "ORDENANZA" in upper:
            tipo = "Ordenanza"
        elif "DECRETO" in upper:
            tipo = "Decreto"
        elif "RESOLUCI" in upper:
            tipo = "Resolución"
            
        match = re.search(r'(?:N[°º]|\bNRO\.?|\bN|\bNMERO|\bN\b)\s*(\d+)', upper)
        if match:
            numero = match.group(1)
            
        if tipo and numero:
            return tipo, numero
            
    match_fallback = re.search(r'^([A-Z0-9]+)\\\-(\d+)', text)
    if match_fallback:
        raw_num = match_fallback.group(1)
        num_clean = re.sub(r'\D', '', raw_num)
        if num_clean:
            return "Ordenanza", num_clean
            
    return tipo, numero

def main():
    print("1. Consultando estado de la base de datos para buscar normas pendientes (IS NULL)...")
    sql_check = "SELECT numero, tipo_nombre FROM normas WHERE texto_completo IS NULL"
    res_check = run_turso_query(sql_check, timeout=180)
    
    if "error" in res_check:
        print(f"Error consultando BD: {res_check['error']}")
        return
        
    pending_to_index = set()
    for row in res_check.get("rows", []):
        pending_to_index.add((row["numero"], row["tipo_nombre"]))
        
    print(f"Normas pendientes en la base de datos: {len(pending_to_index)}")

    print("2. Convirtiendo Word a Markdown (Mammoth)...")
    with open("output/digesto_consolidado_word.docx", "rb") as docx_file:
        result = mammoth.convert_to_markdown(docx_file)
        markdown = result.value
        
    print(f"Conversión completada. Tamaño: {len(markdown)} caracteres.")
    
    print("3. Segmentando documento en secciones...")
    segments = re.split(r'^#\s+', markdown, flags=re.MULTILINE)
    print(f"Total de segmentos detectados: {len(segments)}")
    
    updates_queue = []
    skipped_count = 0
    
    for i, seg in enumerate(segments):
        if i == 0:
            continue
            
        tipo, numero = parse_norma_header(seg)
        if numero:
            tipo_final = tipo or "Ordenanza"
            
            # FILTRAR: Solo agregar si está en la lista de PENDIENTES
            if (numero, tipo_final) not in pending_to_index:
                skipped_count += 1
                continue
                
            lines = seg.split("\n")
            content = "\n".join(lines[1:]).strip()
            
            updates_queue.append({
                "numero": numero,
                "tipo": tipo_final,
                "texto": content
            })
            
    print(f"Normas ya existentes (saltadas): {skipped_count}")
    print(f"Normas pendientes de indexar: {len(updates_queue)}")
    
    if len(updates_queue) == 0:
        print("¡Todo el digesto ya está 100% indexado en Markdown!")
        return
        
    # Procesar secuencialmente (uno por uno) para garantizar éxito sin bloqueos
    print("4. Iniciando indexación secuencial de las normas pendientes...")
    
    exitos = 0
    errores = 0
    total = len(updates_queue)
    
    for idx, up in enumerate(updates_queue):
        num = up["numero"]
        tipo = up["tipo"]
        texto = up["texto"]
        
        sql = "UPDATE normas SET texto_completo = ? WHERE numero = ? AND tipo_nombre = ?"
        res_up = run_turso_query(sql, [texto, num, tipo])
        
        if "error" in res_up:
            errores += 1
            print(f"[{idx+1}/{total}] FALLÓ {tipo} {num}: {res_up['error']}")
            # Dormir un segundo en caso de error de rate limit
            time.sleep(1)
        else:
            exitos += 1
            # Imprimir progreso cada 5 normas para no inundar el log, pero ver movimiento
            if (idx + 1) % 5 == 0 or idx == total - 1:
                print(f"[{idx+1}/{total}] ÉXITO: {tipo} {num} ({len(texto)} caracteres)")
                
    print("\n--- RESUMEN FINAL ---")
    print(f"Pendientes procesadas: {total}")
    print(f"Actualizadas con éxito: {exitos}")
    print(f"Fallidas: {errores}")

if __name__ == "__main__":
    main()