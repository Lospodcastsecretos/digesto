import mammoth
import re
import requests
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

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

def format_args(args):
    formatted = []
    for arg in args:
        if isinstance(arg, int):
            formatted.append({"type": "integer", "value": str(arg)})
        else:
            formatted.append({"type": "text", "value": str(arg)})
    return formatted

def run_turso_query(sql, params=[]):
    url = f"{TURSO_URL}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "requests": [
            {"type": "execute", "stmt": {"sql": sql, "args": format_args(params)}},
            {"type": "close"}
        ]
    }
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=60)
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
    # Buscar patrones como ORDENANZA N° 1234
    lines = [line.strip() for line in text.split("\n") if line.strip()][:10]
    
    tipo = None
    numero = None
    
    for line in lines:
        upper = line.upper()
        # Detectar Tipo
        if "ORDENANZA" in upper:
            tipo = "Ordenanza"
        elif "DECRETO" in upper:
            tipo = "Decreto"
        elif "RESOLUCI" in upper:
            tipo = "Resolución"
            
        # Detectar Número
        # Busca números de hasta 5 dígitos después de N°, N°, Nº, Nº o un espacio
        match = re.search(r'(?:N[°º]|\bNRO\.?|\bN|\bNMERO|\bN\b)\s*(\d+)', upper)
        if match:
            numero = match.group(1)
            
        if tipo and numero:
            return tipo, numero
            
    # Fallback si no lo encuentra en las primeras líneas normales
    # Intentar parsear el Heading original si está al principio (ej: 6847\-9786)
    match_fallback = re.search(r'^([A-Z0-9]+)\\\-(\d+)', text)
    if match_fallback:
        # Si era ORD6847, limpiar a 6847
        raw_num = match_fallback.group(1)
        num_clean = re.sub(r'\D', '', raw_num)
        if num_clean:
            return None, num_clean # Retornar número, el tipo se buscará en BD
            
    return tipo, numero

def main():
    print("1. Convirtiendo Word a Markdown (Mammoth)...")
    with open("output/digesto_consolidado_word.docx", "rb") as docx_file:
        result = mammoth.convert_to_markdown(docx_file)
        markdown = result.value
        
    print(f"Conversión completada. Tamaño: {len(markdown)} caracteres.")
    
    # Separar por Heading 1 (# )
    print("2. Segmentando documento en secciones...")
    segments = re.split(r'^#\s+', markdown, flags=re.MULTILINE)
    print(f"Total de segmentos detectados: {len(segments)}")
    
    normas_to_update = []
    
    for i, seg in enumerate(segments):
        if i == 0:
            # Encabezado inicial del documento, ignorar
            continue
            
        # Intentar extraer tipo y número de la norma
        tipo, numero = parse_norma_header(seg)
        if numero:
            # Limpiar texto del segmento (quitar el Heading 1 original de la primera línea)
            lines = seg.split("\n")
            # La primera línea contiene el header (ej: "6847\-9786"), la removemos del texto completo
            content = "\n".join(lines[1:]).strip()
            
            normas_to_update.append({
                "segment_index": i,
                "tipo_sugerido": tipo,
                "numero": numero,
                "texto": content
            })
            
    print(f"Normas parseadas exitosamente: {len(normas_to_update)}")
    
    # Procesar actualizaciones en la base de datos (con hilos concurrentes para mayor velocidad)
    print("3. Subiendo textos estructurados en Markdown a Turso...")
    
    stats = {"exitos": 0, "no_encontrados": 0, "errores": 0}
    
    def update_norma(norma):
        num = norma["numero"]
        tipo = norma["tipo_sugerido"]
        texto = norma["texto"]
        
        # Buscar el ID en Turso
        if tipo:
            sql_find = "SELECT id, titulo FROM normas WHERE numero = ? AND tipo_nombre = ?"
            params_find = [num, tipo]
        else:
            # Buscar por número y asumir que es Ordenanza o buscar qué coincide
            sql_find = "SELECT id, tipo_nombre, titulo FROM normas WHERE numero = ?"
            params_find = [num]
            
        res = run_turso_query(sql_find, params_find)
        
        if "error" in res:
            return {"status": "error", "msg": f"Error buscando {tipo} {num}: {res['error']}"}
            
        rows = res.get("rows", [])
        if not rows:
            return {"status": "no_encontrado", "msg": f"No se encontró norma número {num} (Tipo: {tipo}) en Turso"}
            
        # Si había varios, elegir el que coincida en tipo o el primero
        norma_id = rows[0]["id"]
        tipo_final = tipo or rows[0].get("tipo_nombre")
        
        # Hacer el UPDATE
        sql_up = "UPDATE normas SET texto_completo = ? WHERE id = ?"
        res_up = run_turso_query(sql_up, [texto, norma_id])
        
        if "error" in res_up:
            return {"status": "error", "msg": f"Error actualizando {tipo_final} {num} (ID: {norma_id}): {res_up['error']}"}
            
        return {"status": "exito", "msg": f"Actualizada con éxito {tipo_final} {num} (ID: {norma_id}) - {len(texto)} chars"}

    # Ejecutar en pool de 15 hilos paralelos
    total = len(normas_to_update)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(update_norma, n): n for n in normas_to_update}
        
        for idx, fut in enumerate(as_completed(futures)):
            res = fut.result()
            status = res["status"]
            if status == "exito":
                stats["exitos"] += 1
            elif status == "no_encontrado":
                stats["no_encontrados"] += 1
            else:
                stats["errores"] += 1
                
            # Log de progreso cada 50 normas
            if idx > 0 and idx % 50 == 0:
                print(f"Progreso: {idx}/{total} - Éxitos: {stats['exitos']}, No encontrados: {stats['no_encontrados']}, Errores: {stats['errores']}")
                
    print("\n--- RESUMEN FINAL ---")
    print(f"Total procesadas: {total}")
    print(f"Actualizadas con éxito (Markdown): {stats['exitos']}")
    print(f"Ignoradas (no en BD de Turso): {stats['no_encontrados']}")
    print(f"Fallidas (Errores de red/SQL): {stats['errores']}")

if __name__ == "__main__":
    main()