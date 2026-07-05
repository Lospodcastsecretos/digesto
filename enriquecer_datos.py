import json
import os
import sys

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

OUTPUT_DIR = "output"

# 1. Buscar el JSON de publicaciones mas reciente
json_files = [f for f in os.listdir(OUTPUT_DIR) if f.startswith("digesto_completo_") and f.endswith(".json")]
if not json_files:
    print("Error: No se encontro ningun archivo 'digesto_completo_*.json'")
    sys.exit(1)

json_files.sort(reverse=True)
latest_json = os.path.join(OUTPUT_DIR, json_files[0])
print(f"Cargando base de datos desde: {latest_json}")

with open(latest_json, "r", encoding="utf-8") as f:
    normas = json.load(f)

# Catálogos obtenidos del análisis de la SPA
CATALOGO_TIPOS = {
    1: "Ordenanza",
    2: "Resolución",
    3: "Decreto CD",
    4: "Decreto PE"
}

CATALOGO_CATEGORIAS = {
    1: "Cultura y Turismo",
    2: "Educación y Deporte",
    3: "Desarrollo Social",
    4: "Economía y Finanzas",
    5: "Gobierno",
    6: "Obras y Servicios Públicos",
    7: "Organización Institucional",
    8: "Salud y Medio Ambiente",
    9: "Seguridad y Tránsito",
    10: "Urbanismo y Vivienda"
}

# 2. Enriquecer los datos reemplazando IDs con nombres legibles
print("Enriqueciendo registros con tipos y categorías legibles...")
modificados = 0
for norma in normas:
    # Obtener tipo
    t_id = norma.get("tipo_id")
    if t_id and t_id in CATALOGO_TIPOS:
        norma["tipo"] = CATALOGO_TIPOS[t_id]
        modificados += 1
    elif not norma.get("tipo"):
        # Intento de fallback usando otros nombres de campo si existen
        raw_tipo_id = norma.get("id_tipo")
        if raw_tipo_id and raw_tipo_id in CATALOGO_TIPOS:
            norma["tipo"] = CATALOGO_TIPOS[raw_tipo_id]
            norma["tipo_id"] = raw_tipo_id
            modificados += 1

    # Obtener categoría
    c_id = norma.get("categoria_id")
    if c_id and c_id in CATALOGO_CATEGORIAS:
        norma["categoria"] = CATALOGO_CATEGORIAS[c_id]
    elif not norma.get("categoria"):
        raw_cat_id = norma.get("id_categoria")
        if raw_cat_id and raw_cat_id in CATALOGO_CATEGORIAS:
            norma["categoria"] = CATALOGO_CATEGORIAS[raw_cat_id]
            norma["categoria_id"] = raw_cat_id

# 3. Exportar JSON enriquecido
enriquecido_json_path = os.path.join(OUTPUT_DIR, "digesto_completo_enriquecido.json")
with open(enriquecido_json_path, "w", encoding="utf-8") as f:
    json.dump(normas, f, ensure_ascii=False, indent=2)
print(f"JSON enriquecido guardado en: {enriquecido_json_path}")

# 4. Exportar CSV enriquecido listo para Excel
enriquecido_csv_path = os.path.join(OUTPUT_DIR, "digesto_tabla_enriquecida.csv")
try:
    import csv
    campos = ["id", "numero", "tipo", "titulo", "categoria", "fecha_sancion",
               "vigente", "descriptores", "resumen", "archivo_pdf", "url_detalle"]
    
    with open(enriquecido_csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        writer.writeheader()
        for doc in normas:
            row = dict(doc)
            # Normalizar descriptores a string
            if isinstance(row.get("descriptores"), list):
                row["descriptores"] = "; ".join(row["descriptores"])
            writer.writerow(row)
    print(f"CSV enriquecido listo para Excel guardado en: {enriquecido_csv_path}")
except Exception as e:
    print(f"Error exportando CSV: {e}")
