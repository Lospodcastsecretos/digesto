import os
import json
import re
import sys

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DATA_FILE = r"output\digesto_completo_enriquecido.json"

if not os.path.exists(DATA_FILE):
    print("Error: No se encontro el archivo de datos JSON enriquecido.")
    sys.exit(1)

with open(DATA_FILE, "r", encoding="utf-8") as f:
    normas = json.load(f)

print(f"Cargando {len(normas)} normas para clasificar tematicamente y vigencia...")

# Categorias con palabras clave asociadas
dicc_categorias = {
    "Hacienda y Finanzas": [
        "tasa", "tributaria", "presupuesto", "eximicion", "deuda", "eximir", "pago", "impositiva", "contable",
        "contribuyentes", "tributos", "tarifaria", "hacienda", "fiscal", "adicional", "valuacion", "tarifa"
    ],
    "Obras y Servicios Públicos": [
        "obra", "obras", "gas", "pavimento", "cordon", "cuneta", "alumbrado", "vivienda", "lote", "terreno",
        "adjudicacion", "loteo", "construccion", "calle", "infraestructura", "catastro", "plaza", "parque"
    ],
    "Salud y Medio Ambiente": [
        "salud", "dispensario", "medico", "ambiental", "residuos", "basura", "higiene", "bromatologia",
        "patogenos", "contaminacion", "perros", "animales", "vacunacion", "plagas", "sanitaria"
    ],
    "Tránsito y Transporte": [
        "transito", "transporte", "colectivo", "taxis", "remis", "remises", "vehiculo", "vehiculos", 
        "calzadas", "estacionamiento", "licencia", "conducir", "semaforo", "multa"
    ],
    "Recursos Humanos / Personal": [
        "personal", "sueldo", "escala", "salarial", "planta", "permanente", "contratacion", "bonificacion",
        "remuneracion", "paritaria", "sindicato", "ate", "adicionales", "jubilados"
    ],
    "Cultura, Deportes y Turismo": [
        "cultura", "deporte", "turismo", "colectividades", "fiesta", "festival", "museo", "monumento",
        "patrimonio", "historico", "biblioteca", "evento", "teatro", "recreacion"
    ],
    "Educación y Acción Social": [
        "educacion", "escuela", "colegio", "subsidio", "ayuda", "social", "beca", "becas", "alimentario",
        "genero", "niñez", "adolescencia", "discapacidad", "subsidios"
    ]
}

palabras_derogacion = [
    "derogada", "derogase", "no vigente", "derogar", "caduca", "abrogada", "suspendase", "quedando sin efecto",
    "dejese sin efecto", "derógase", "déjese sin efecto", "quedando sin efectos"
]

# Clasificar cada norma
for n in normas:
    titulo = (n.get("titulo") or "").lower()
    resumen = (n.get("resumen") or "").lower()
    archivo = (n.get("archivo_pdf") or "").lower()
    
    texto_completo = f"{titulo} {resumen} {archivo}"
    
    # 1. Resolver el Tipo de Norma
    tipo = "Ordenanza" # Por defecto
    if "resolucion" in texto_completo or " resol " in texto_completo or archivo.startswith("re "):
        tipo = "Resolución"
    elif "decreto" in texto_completo or " dec " in texto_completo or archivo.startswith("dec "):
        tipo = "Decreto"
    elif "ordenanza" in texto_completo or archivo.startswith("ord "):
        tipo = "Ordenanza"
    
    n["tipo_nombre"] = tipo
    
    # 2. Resolver Categoria Tematica
    categoria = "Administración General"
    max_coincidencias = 0
    
    for cat, palabras in dicc_categorias.items():
        coincidencias = sum(1 for p in palabras if p in texto_completo)
        if coincidencias > max_coincidencias:
            max_coincidencias = coincidencias
            categoria = cat
            
    n["categoria_nombre"] = categoria
    
    # 3. Resolver Vigencia (Buscar indicios de derogacion)
    es_vigente = True
    if any(p in texto_completo for p in palabras_derogacion):
        es_vigente = False
    
    n["vigente"] = es_vigente
    
    # 4. Resolver Año / Fecha
    anio = None
    match_file = re.search(r'[-_ ](\d{2})\b', archivo)
    if match_file:
        digitos = int(match_file.group(1))
        anio = 2000 + digitos if digitos < 26 else 1900 + digitos
        
    match_text = re.search(r'\b(19[7-9]\d|20[0-2]\d)\b', texto_completo)
    if match_text:
        anio = int(match_text.group(1))
        
    if anio:
        n["fecha"] = f"Año {anio}"
    else:
        n["fecha"] = "Histórico / Sin fecha"

# Guardar de nuevo los datos clasificados e inyectados
with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(normas, f, indent=2, ensure_ascii=False)

print(f"¡Se han clasificado, asignado vigencia y guardado con éxito las {len(normas)} normas en {DATA_FILE}!")
