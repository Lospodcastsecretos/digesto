import os
import sys
import json
import time
import requests
from datetime import datetime

# ─── Cargar variables de entorno desde .env ───────────────────────────────────
if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key, val.strip('"\''))

TURSO_URL = os.environ.get("TURSO_URL")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

CHECKPOINT_FILE = "scratch/.checkpoint_relaciones"
ERROR_LOG = "scratch/errores_relaciones.log"

# Tipos de norma que pertenecen a la BD municipal (los demás se guardan sin ID de destino)
TIPOS_MUNICIPALES = {"Ordenanza", "Decreto", "Resolución"}

if not TURSO_URL or not TURSO_TOKEN:
    print("❌ Faltan variables de entorno TURSO_URL o TURSO_TOKEN.")
    sys.exit(1)

if not DEEPSEEK_API_KEY and not GROQ_API_KEY:
    print("❌ Se necesita al menos DEEPSEEK_API_KEY o GROQ_API_KEY.")
    sys.exit(1)

clean_url = TURSO_URL.replace("libsql://", "https://").replace("http://", "https://")
pipeline_url = f"{clean_url}/v2/pipeline"
turso_headers = {"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"}


# ─── Turso helpers ────────────────────────────────────────────────────────────
def turso_query(sql, params=None):
    args = []
    for p in (params or []):
        if p is None:
            args.append({"type": "null", "value": None})
        elif isinstance(p, int):
            args.append({"type": "integer", "value": str(p)})
        elif isinstance(p, float):
            args.append({"type": "float", "value": p})
        else:
            args.append({"type": "text", "value": str(p)})

    payload = {"requests": [{"type": "execute", "stmt": {"sql": sql, "args": args}}, {"type": "close"}]}
    resp = requests.post(pipeline_url, json=payload, headers=turso_headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    result = data["results"][0]
    if result["type"] == "error":
        raise Exception(f"Turso error: {result['error']['message']}")
    res = result["response"]["result"]
    cols = [c["name"] for c in res["cols"]]
    return [{cols[i]: (val["value"] if val else None) for i, val in enumerate(row)} for row in res["rows"]]


def turso_execute(sql, params=None):
    args = []
    for p in (params or []):
        if p is None:
            args.append({"type": "null", "value": None})
        elif isinstance(p, int):
            args.append({"type": "integer", "value": str(p)})
        elif isinstance(p, float):
            args.append({"type": "float", "value": p})
        else:
            args.append({"type": "text", "value": str(p)})

    payload = {"requests": [{"type": "execute", "stmt": {"sql": sql, "args": args}}, {"type": "close"}]}
    resp = requests.post(pipeline_url, json=payload, headers=turso_headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    result = data["results"][0]
    if result["type"] == "error":
        raise Exception(f"Turso error: {result['error']['message']}")
    return result["response"]["result"]["affected_row_count"]


# ─── Circuit breaker DeepSeek → Groq con retry + backoff ─────────────────────
ds_failures = 0
DS_FAILURE_THRESHOLD = 3
ds_tripped_until = 0


def llamar_llm(prompt_text, max_retries=2):
    global ds_failures, ds_tripped_until

    for intento in range(max_retries + 1):
        if intento > 0:
            wait = 3 * intento  # backoff: 3s, 6s...
            print(f"   🔄 Reintentando en {wait}s (intento {intento+1}/{max_retries+1})...")
            time.sleep(wait)

        # Intentar DeepSeek (si no está en circuit break)
        if DEEPSEEK_API_KEY and time.time() > ds_tripped_until:
            try:
                resp = requests.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt_text}],
                        "max_tokens": 2000,
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"}
                    },
                    timeout=60
                )
                if resp.status_code == 200:
                    ds_failures = 0
                    content = resp.json()["choices"][0]["message"]["content"]
                    return content, "deepseek"
                elif resp.status_code == 429:
                    print(f"   ⚠️ DeepSeek rate limit (429). Esperando 10s...")
                    time.sleep(10)
                    continue
                else:
                    ds_failures += 1
                    print(f"   ⚠️ DeepSeek HTTP {resp.status_code}")
                    if ds_failures >= DS_FAILURE_THRESHOLD:
                        ds_tripped_until = time.time() + 120
                        print(f"   ⚡ Circuit breaker abierto: DeepSeek pausado 120s")
            except requests.exceptions.Timeout:
                ds_failures += 1
                print(f"   ⚠️ DeepSeek timeout")
            except Exception as e:
                ds_failures += 1
                print(f"   ⚠️ Error DeepSeek: {e}")

        # Fallback a Groq
        if GROQ_API_KEY:
            try:
                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": "llama-3.1-8b-instant",
                        "messages": [{"role": "user", "content": prompt_text}],
                        "max_tokens": 2000,
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"}
                    },
                    timeout=45
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    return content, "groq"
                elif resp.status_code == 429:
                    print(f"   ⚠️ Groq rate limit (429). Esperando 30s...")
                    time.sleep(30)
                    continue
                else:
                    print(f"   ⚠️ Groq HTTP {resp.status_code}")
            except requests.exceptions.Timeout:
                print(f"   ⚠️ Groq timeout")
            except Exception as e:
                print(f"   ⚠️ Error Groq: {e}")

    return None, None


# ─── Extracción de relaciones ─────────────────────────────────────────────────
def construir_prompt(norma):
    texto = (norma.get("texto_completo") or "")[:12000]
    return f"""Eres un analista jurídico experto en legislación municipal argentina. Tu única tarea es identificar si el siguiente texto normativo MODIFICA, DEROGA, COMPLEMENTA o REGLAMENTA a otra norma.

Norma analizada: {norma['tipo_nombre']} N° {norma['numero']} ({norma['fecha']})
Texto:
{texto}

Responde ÚNICAMENTE con un objeto JSON con una clave "relaciones" que contenga un array (sin texto adicional, sin markdown). Cada elemento del array:
{{
  "tipo_relacion": "modifica" | "deroga" | "complementa" | "reglamenta",
  "norma_destino_tipo": "Ordenanza" | "Decreto" | "Resolución",
  "norma_destino_numero": "string, solo el número",
  "articulo_afectado": "string o null si es derogación/afectación total",
  "justificacion": "Cita textual del fragmento del texto original que demuestra esta relación (máx. 160 caracteres)",
  "fragmento_original": "la oración o párrafo exacto (máx. 300 caracteres) donde el texto dice 'Modifícase...' o 'Derógase...'",
  "confianza": número entre 0.0 y 1.0
}}

Si el texto NO modifica ninguna otra norma, responde exactamente: {{"relaciones": []}}

Reglas estrictas:
- Solo incluir normas de tipo Ordenanza, Decreto o Resolución (municipales). Ignorar Leyes provinciales/nacionales.
- No inventes números de norma que no estén explícitamente citados en el texto.
- Una simple mención o referencia ("de acuerdo a la Ordenanza X") NO es una modificación.
- Solo incluir relaciones donde el texto explícitamente dice "Modifícase", "Derógase", "Sustitúyese", "Incorpórase", "Reemplázase" o equivalente.
- Si una norma modifica varios artículos de otra, listarlos como entradas SEPARADAS (una por artículo).
- IMPORTANTE: No repetir la misma combinación (norma_destino_numero + articulo_afectado) más de una vez.
- Si tenés dudas, bajá el valor de "confianza" en lugar de omitir la relación."""


def buscar_norma_destino(numero, tipo):
    # Solo buscar en la BD si es tipo municipal
    if tipo not in TIPOS_MUNICIPALES:
        return None
    try:
        rows = turso_query(
            "SELECT id FROM normas WHERE numero = ? AND tipo_nombre = ? LIMIT 1",
            [str(numero), str(tipo)]
        )
        if rows:
            return int(rows[0]["id"])
    except Exception:
        pass
    return None


def log_error(norma_id, numero, error_msg):
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} | id={norma_id} | num={numero} | error={error_msg}\n")


# ─── Checkpoint helpers ────────────────────────────────────────────────────────
def leer_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r") as f:
                return int(f.read().strip())
        except Exception:
            pass
    return 0


def guardar_checkpoint(last_id):
    os.makedirs("scratch", exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(str(last_id))


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    # Parsear argumentos CLI
    args = sys.argv[1:]
    sample_n = None
    categoria_filter = None
    dry_run = "--dry-run" in args

    for i, arg in enumerate(args):
        if arg == "--sample" and i + 1 < len(args):
            sample_n = int(args[i + 1])
        if arg == "--categoria" and i + 1 < len(args):
            categoria_filter = args[i + 1]

    if dry_run:
        print("🔍 MODO DRY RUN — No se guardarán cambios en Turso.")

    print(f"🚀 Extractor de Relaciones Legales — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   Checkpoint: {CHECKPOINT_FILE}")
    if sample_n:
        print(f"   Muestra limitada a {sample_n} normas")
    if categoria_filter:
        print(f"   Filtro categoría: '{categoria_filter}'")

    last_processed_id = leer_checkpoint()
    if last_processed_id > 0:
        print(f"   Reanudando desde id > {last_processed_id}")

    # 1. Traer IDs de normas que ya tienen relaciones registradas (para saltarlas)
    print("\n1️⃣ Cargando normas ya procesadas...")
    ya_procesadas = set()
    try:
        rows = turso_query("SELECT DISTINCT norma_origen_id FROM normas_relaciones")
        ya_procesadas = {int(r["norma_origen_id"]) for r in rows if r.get("norma_origen_id")}
        print(f"   -> {len(ya_procesadas)} normas ya tienen relaciones registradas (se saltarán)")
    except Exception as e:
        print(f"   ⚠️ No se pudo cargar normas procesadas: {e}")

    # 2. Traer normas con texto_completo
    print("\n2️⃣ Cargando normas con texto completo...")
    sql = "SELECT id, numero, tipo_nombre, fecha, categoria_nombre FROM normas WHERE texto_completo IS NOT NULL"
    params = []
    if categoria_filter:
        sql += " AND categoria_nombre LIKE ?"
        params.append(f"%{categoria_filter}%")
    sql += " ORDER BY fecha ASC, id ASC"

    normas = turso_query(sql, params)
    print(f"   -> {len(normas)} normas con texto disponibles")

    # Filtrar las ya procesadas y las anteriores al checkpoint
    normas = [n for n in normas if int(n["id"]) not in ya_procesadas]
    if last_processed_id > 0:
        normas = [n for n in normas if int(n["id"]) > last_processed_id]

    if sample_n:
        normas = normas[:sample_n]

    total = len(normas)
    print(f"   -> {total} normas por procesar")

    if total == 0:
        print("\n✅ ¡No hay normas nuevas por procesar! Todo está al día.")
        return

    print(f"\n3️⃣ Iniciando extracción de relaciones ({total} normas)...")

    ok_count = 0
    relaciones_count = 0
    error_count = 0

    for idx, norma in enumerate(normas, 1):
        norma_id = int(norma["id"])
        print(f"\n[{idx}/{total}] {norma['tipo_nombre']} N° {norma['numero']} (id={norma_id})...")

        try:
            # Traer el texto completo de esta norma
            texto_rows = turso_query(
                "SELECT texto_completo FROM normas WHERE id = ?", [norma_id]
            )
            if not texto_rows or not texto_rows[0].get("texto_completo"):
                print("   -> Sin texto, saltando.")
                guardar_checkpoint(norma_id)
                continue

            norma["texto_completo"] = texto_rows[0]["texto_completo"]
            prompt = construir_prompt(norma)

            # Llamar al LLM (con retry+backoff integrado)
            content, modelo_usado = llamar_llm(prompt)
            if not content:
                log_error(norma_id, norma["numero"], "LLM no respondió tras reintentos")
                error_count += 1
                guardar_checkpoint(norma_id)
                time.sleep(1.2)
                continue

            # Parsear JSON
            try:
                parsed = json.loads(content)
                relaciones = parsed.get("relaciones", parsed) if isinstance(parsed, dict) else parsed
                if not isinstance(relaciones, list):
                    relaciones = []
            except json.JSONDecodeError as je:
                log_error(norma_id, norma["numero"], f"JSON inválido: {je} | content: {content[:200]}")
                error_count += 1
                guardar_checkpoint(norma_id)
                time.sleep(1.2)
                continue

            if not relaciones:
                print(f"   -> Sin relaciones detectadas ({modelo_usado})")
                ok_count += 1
                guardar_checkpoint(norma_id)
                time.sleep(1.2)
                continue

            # ── Deduplicar y filtrar auto-referencias ─────────────────────────
            vistas = set()
            relaciones_unicas = []
            for rel in relaciones:
                tipo_rel = rel.get("tipo_relacion", "").lower()
                if tipo_rel not in ("modifica", "deroga", "complementa", "reglamenta"):
                    continue
                dest_tipo = rel.get("norma_destino_tipo", "Ordenanza")
                dest_num = str(rel.get("norma_destino_numero", "")).strip()
                art = str(rel.get("articulo_afectado") or "").strip()

                # Descartar si la norma se apunta a sí misma (hallucination del encabezado)
                if dest_num == str(norma["numero"]) and dest_tipo == norma["tipo_nombre"]:
                    print(f"   ⚠️ Auto-referencia descartada: {dest_tipo} N° {dest_num}")
                    continue

                clave = (dest_tipo, dest_num, art)
                if clave not in vistas:
                    vistas.add(clave)
                    relaciones_unicas.append(rel)

            print(f"   -> {len(relaciones_unicas)} relación(es) única(s) detectada(s) ({modelo_usado})")

            for rel in relaciones_unicas:
                tipo = rel.get("tipo_relacion", "").lower()
                dest_tipo = rel.get("norma_destino_tipo", "Ordenanza")
                dest_numero = str(rel.get("norma_destino_numero", "")).strip()
                articulo = rel.get("articulo_afectado") or None
                justificacion = rel.get("justificacion") or None
                fragmento_original = rel.get("fragmento_original") or None
                confianza = float(rel.get("confianza", 0.5))
                confianza = max(0.0, min(1.0, confianza))

                # Intentar resolver ID solo si es tipo municipal
                dest_id = buscar_norma_destino(dest_numero, dest_tipo)

                print(f"      [{tipo.upper()}] → {dest_tipo} N° {dest_numero} | art={articulo} | conf={confianza:.2f} | id_destino={dest_id or 'NULL'}")

                if not dry_run:
                    turso_execute(
                        """INSERT INTO normas_relaciones 
                           (norma_origen_id, norma_destino_id, destino_numero_texto, destino_tipo_texto,
                            tipo_relacion, articulo_afectado, texto_nuevo, confianza, revisado_humano, justificacion, fragmento_original)
                           VALUES (?, ?, ?, ?, ?, ?, NULL, ?, 0, ?, ?)""",
                        [norma_id, dest_id, dest_numero, dest_tipo, tipo, articulo, confianza, justificacion, fragmento_original]
                    )
                    relaciones_count += 1

            ok_count += 1

        except Exception as e:
            log_error(norma_id, norma["numero"], str(e))
            print(f"   ❌ Error: {e}")
            error_count += 1

        guardar_checkpoint(norma_id)
        time.sleep(1.2)  # Rate limiting: 1.2s entre normas

    print(f"\n{'─'*50}")
    print(f"✅ EXTRACCIÓN COMPLETADA")
    print(f"   Normas procesadas: {ok_count}/{total}")
    print(f"   Relaciones insertadas: {relaciones_count}")
    print(f"   Errores: {error_count} (ver {ERROR_LOG})")
    if dry_run:
        print("   ⚠️  Modo DRY RUN — ningún dato fue guardado en Turso.")


if __name__ == "__main__":
    main()
