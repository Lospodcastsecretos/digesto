import mammoth
import re
import requests
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

TURSO_URL = "https://digesto-lospodcastsecretos.aws-us-west-2.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODMyODgxMjQsImlkIjoiMDE5ZjM0NDAtN2UwMS03OTljLWFlOTItODBiMDJmNmVhMjdlIiwia2lkIjoiZ0JFblIyNVR6dEEwaHVWWXljOS03cnRzYThUaGRnbmFEd1ZHSXJrR3FPYyIsInJpZCI6ImE1MGUwMDBmLTQ4ZTgtNDg1ZS04MmM0LTEzNGIxYTA4MmJhYSJ9.ev1b_OISV20t8e9brtO7O4oU9bGnrPYum1LTbBiVng-gaPC2YiUsHzFe-ok2aXmVePtRNYtAmKpb0ntWL6xSCA"

# Configurar encoding
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def format_args(args):
    formatted = []
    for arg in args:
        if isinstance(arg, int):
            formatted.append({"type": "integer", "value": str(arg)})
        else:
            formatted.append({"type": "text", "value": str(arg)})
    return formatted

def send_bulk_updates(updates_list):
    # updates_list es una lista de dicts: {"sql": sql, "params": params}
    url = f"{TURSO_URL}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json"
    }
    
    requests_payload = []
    for up in updates_list:
        requests_payload.append({
            "type": "execute",
            "stmt": {
                "sql": up["sql"],
                "args": format_args(up["params"])
            }
        })
    requests_payload.append({"type": "close"})
    
    payload = {
        "requests": requests_payload
    }
    
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        if r.status_code == 200:
            data = r.json()
            # Validar si hubo errores en algún execute
            success_count = 0
            error_count = 0
            for i, res in enumerate(data.get("results", [])):
                if i == len(data["results"]) - 1:
                    break # close statement
                if res["type"] == "error":
                    error_count += 1
                else:
                    # En UPDATE, verificar cuántas filas se afectaron
                    affected = res["response"]["result"].get("affected_row_count", 0)
                    if affected > 0:
                        success_count += affected
                    else:
                        # Si no afectó filas, probablemente no se encontró la norma en Turso
                        error_count += 1
            return {"success": success_count, "errors": error_count}
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
            
    # Fallback Heading
    match_fallback = re.search(r'^([A-Z0-9]+)\\\-(\d+)', text)
    if match_fallback:
        raw_num = match_fallback.group(1)
        num_clean = re.sub(r'\D', '', raw_num)
        if num_clean:
            return "Ordenanza", num_clean # Default a Ordenanza si viene de cabecera sin tipo
            
    return tipo, numero

def main():
    print("1. Convirtiendo Word a Markdown (Mammoth)...")
    with open("output/digesto_consolidado_word.docx", "rb") as docx_file:
        result = mammoth.convert_to_markdown(docx_file)
        markdown = result.value
        
    print(f"Conversión completada. Tamaño: {len(markdown)} caracteres.")
    
    print("2. Segmentando documento en secciones...")
    segments = re.split(r'^#\s+', markdown, flags=re.MULTILINE)
    print(f"Total de segmentos detectados: {len(segments)}")
    
    updates_queue = []
    
    for i, seg in enumerate(segments):
        if i == 0:
            continue
            
        tipo, numero = parse_norma_header(seg)
        if numero:
            lines = seg.split("\n")
            content = "\n".join(lines[1:]).strip()
            
            tipo_final = tipo or "Ordenanza" # Default a Ordenanza
            
            # Crear la sentencia de UPDATE directo sin hacer SELECT previo
            sql = "UPDATE normas SET texto_completo = ? WHERE numero = ? AND tipo_nombre = ?"
            params = [content, numero, tipo_final]
            
            updates_queue.append({"sql": sql, "params": params, "numero": numero, "tipo": tipo_final})
            
    total_normas = len(updates_queue)
    print(f"Normas preparadas para actualizar: {total_normas}")
    
    # Agrupar en lotes de 20 consultas por request
    batch_size = 20
    batches = [updates_queue[i:i + batch_size] for i in range(0, len(updates_queue), batch_size)]
    total_batches = len(batches)
    print(f"Total de lotes (batches) creados: {total_batches}")
    
    stats = {"exitos": 0, "no_encontrados_o_errores": 0, "fallos_red": 0}
    
    print("3. Ejecutando actualizaciones en lotes (Bulk Pipeline) a Turso...")
    
    # Procesar lotes usando 1 solo hilo para evitar bloqueos de base de datos en SQLite
    with ThreadPoolExecutor(max_workers=1) as executor:
        futures = {executor.submit(send_bulk_updates, b): idx for idx, b in enumerate(batches)}
        
        for idx, fut in enumerate(as_completed(futures)):
            batch_idx = futures[fut]
            try:
                res = fut.result()
                if "error" in res:
                    stats["fallos_red"] += 1
                    print(f"Lote {batch_idx + 1}/{total_batches} falló por red/servidor: {res['error']}")
                else:
                    stats["exitos"] += res["success"]
                    stats["no_encontrados_o_errores"] += res["errors"]
            except Exception as e:
                stats["fallos_red"] += 1
                print(f"Excepción en lote {batch_idx + 1}: {str(e)}")
                
            if idx > 0 and idx % 10 == 0:
                print(f"Lotes completados: {idx}/{total_batches} - Normas actualizadas con éxito: {stats['exitos']}, Fallidas/No encontradas: {stats['no_encontrados_o_errores']}")
                
    print("\n--- RESUMEN FINAL ---")
    print(f"Total normas procesadas: {total_normas}")
    print(f"Actualizadas con éxito (Markdown): {stats['exitos']}")
    print(f"Ignoradas/No encontradas/Errores: {stats['no_encontrados_o_errores']}")
    print(f"Lotes fallidos por red: {stats['fallos_red']}")

if __name__ == "__main__":
    main()
