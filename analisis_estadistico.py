import os
import json
import sys
from collections import Counter
import re

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DATA_FILE = r"output\digesto_completo_enriquecido.json"
REPORT_FILE = r"output\reporte_analisis.md"

if not os.path.exists(DATA_FILE):
    print("Error: No se encontro el archivo de datos JSON enriquecido.")
    sys.exit(1)

with open(DATA_FILE, "r", encoding="utf-8") as f:
    normas = json.load(f)

print(f"Iniciando analisis de {len(normas)} registros...")

# 1. Estadisticas basicas
total_normas = len(normas)
con_archivo = sum(1 for n in normas if n.get("archivo_pdf"))

# Conteo por tipo
tipos = Counter(n.get("tipo_nombre", "Desconocido") for n in normas)

# Conteo por categoria
categorias = Counter(n.get("categoria_nombre", "Sin Categorizar") for n in normas)

# Evolucion por año
anios_lista = []
for n in normas:
    fecha = n.get("fecha")
    if fecha:
        match = re.search(r'\b(19\d{2}|20\d{2})\b', fecha)
        if match:
            anios_lista.append(int(match.group(1)))
anios = Counter(anios_lista)

# 2. Procesamiento de Texto (Palabras clave mas frecuentes)
stopwords = {
    'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 'de', 'del', 'a', 'al', 'e', 'y', 'o', 'u',
    'en', 'para', 'por', 'con', 'sin', 'sobre', 'tras', 'este', 'esta', 'estos', 'estas', 'ese', 'esa',
    'que', 'se', 'su', 'sus', 'del', 'como', 'mas', 'pero', 'sus', 'como', 'para', 'mediante', 'entre',
    'desde', 'hasta', 'hacia', 'cada', 'todo', 'todos', 'toda', 'todas', 'muy', 'sanciona', 'aprueba',
    'declara', 'municipal', 'alta', 'gracia', 'ciudad', 'departamento', 'provincia', 'nro', 'numero',
    'articulo', 'ordenanza', 'decreto', 'resolucion', 'ano', 'fecha', 'registro', 'solicita', 'autoriza',
    'dispone'
}

palabras = []
for n in normas:
    titulo = n.get("titulo") or ""
    descripcion = n.get("descripcion") or ""
    texto = (titulo + " " + descripcion).lower()
    # Extraer palabras limpias
    tokens = re.findall(r'\b[a-z]{3,}\b', texto)
    for token in tokens:
        if token not in stopwords:
            palabras.append(token)

top_palabras = Counter(palabras).most_common(30)

# 3. Armar Reporte en Markdown
reporte = []
reporte.append("# Reporte de Análisis Estadístico del Digesto Municipal\n")
reporte.append(f"Este reporte fue generado de forma automatica analizando la totalidad de las **{total_normas}** normas extraidas del Digesto de Alta Gracia.\n")

reporte.append("## 1. Resumen de Cobertura de Archivos")
reporte.append(f"- **Total de Normas Registradas:** {total_normas}")
reporte.append(f"- **Normas con Archivos Descargables en Drive:** {con_archivo} ({con_archivo/total_normas*100:.1f}%)")
reporte.append(f"- **Normas sin Archivo Adjunto:** {total_normas - con_archivo} (historicos o no digitalizados)\n")

reporte.append("## 2. Normas por Tipo de Documento")
reporte.append("| Tipo de Norma | Cantidad | Porcentaje |")
reporte.append("| --- | --- | --- |")
for tipo, cant in tipos.most_common():
    reporte.append(f"| {tipo} | {cant} | {cant/total_normas*100:.1f}% |")
reporte.append("\n")

reporte.append("## 3. Normas por Categoría Municipal (Áreas Temáticas)")
reporte.append("| Área Temática | Cantidad | Porcentaje |")
reporte.append("| --- | --- | --- |")
for cat, cant in categorias.most_common(20):
    reporte.append(f"| {cat} | {cant} | {cant/total_normas*100:.1f}% |")
reporte.append("\n")

reporte.append("## 4. Evolución Histórica (Top 10 Años con Más Actividad Normativa)")
reporte.append("| Año | Cantidad de Normas Sancionadas |")
reporte.append("| --- | --- |")
for anio, cant in anios.most_common(10):
    reporte.append(f"| {anio} | {cant} |")
reporte.append("\n")

reporte.append("## 5. Análisis de Inteligencia Lingüística (Temas de los que más se habla)")
reporte.append("Las palabras mas recurrentes en los titulos y sumarios de las normas nos indican de que tratan principalmente las leyes de la ciudad:\n")
reporte.append("| Puesto | Palabra Clave | Frecuencia de Aparición | Tema Asociado Sugerido |")
reporte.append("| --- | --- | --- | --- |")

temas_sugeridos = {
    'lote': 'Propiedad y Loteos',
    'eximicion': 'Exenciones Impositivas',
    'personal': 'Empleados Publicos / Recursos Humanos',
    'adjudicacion': 'Entrega de Terrenos/Viviendas',
    'presupuesto': 'Hacienda y Finanzas Publicas',
    'contratacion': 'Compras y Licitaciones',
    'convenio': 'Acuerdos Institucionales',
    'subsidio': 'Ayuda Social / Fomento',
    'donacion': 'Donaciones Aceptadas/Otorgadas',
    'tasa': 'Impuestos Municipales',
    'obra': 'Obras Publicas e Infraestructura',
    'servicios': 'Concesiones y Servicios Municipales',
    'vecinal': 'Centros Vecinales y Participacion',
    'transito': 'Transporte y Seguridad Vial',
    'adhesion': 'Leyes Provinciales/Nacionales',
    'adjudicar': 'Tierras / Vivienda',
    'autorizar': 'Permisos Especiales',
    'tarifaria': 'Tasas e Impuestos Anuales'
}

for idx, (palabra, freq) in enumerate(top_palabras):
    sugerencia = temas_sugeridos.get(palabra, "Gestión Administrativa General")
    reporte.append(f"| #{idx+1} | **{palabra}** | {freq} veces | {sugerencia} |")

# Guardar reporte
with open(REPORT_FILE, "w", encoding="utf-8") as f_rep:
    f_rep.write("\n".join(reporte))

print(f"\n¡Reporte estadistico generado con exito en: {REPORT_FILE}!")
