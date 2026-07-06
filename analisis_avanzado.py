import os
import json
import sys
import re
from collections import Counter
import matplotlib.pyplot as plt

# Configurar encoding para consola Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DATA_FILE = r"output\digesto_completo_enriquecido.json"
REPORT_FILE = r"output\reporte_avanzado.md"
GRAPH_FILE = r"output\reporte_grafico.png"

if not os.path.exists(DATA_FILE):
    print("Error: No se encontro el archivo de datos JSON enriquecido.")
    sys.exit(1)

with open(DATA_FILE, "r", encoding="utf-8") as f:
    normas = json.load(f)

print(f"Cargando {len(normas)} normas para analisis e IA avanzada...")

# 1. Deteccion de Normas Criticas / Auditoria
# Definimos palabras que implican decisiones criticas
criticas_keywords = {
    "expropiacion": "Expropiación de tierras o bienes",
    "expropiase": "Expropiación de tierras o bienes",
    "donacion": "Donación de inmuebles o fondos públicos",
    "donar": "Donación de inmuebles o fondos públicos",
    "contratacion directa": "Contratación Directa excepcional",
    "licitacion publica": "Licitaciones de gran envergadura",
    "excepcion": "Excepciones a normativas urbanas o de edificación",
    "exceptuase": "Excepciones a normativas urbanas o de edificación",
    "codigo de edificacion": "Modificaciones al desarrollo urbano",
    "terrenos": "Cesión o adjudicación de tierras fiscales",
    "loteo": "Aprobación de loteos especiales"
}

normas_criticas = []
for n in normas:
    titulo = (n.get("titulo") or "").lower()
    resumen = (n.get("resumen") or "").lower()
    texto = f"{titulo} {resumen}"
    
    # Extraer año
    match_anio = re.search(r'\b(20\d{2})\b', texto)
    anio = int(match_anio.group(1)) if match_anio else 0
    
    # Evaluar palabras clave
    for kw, tipo_critica in criticas_keywords.items():
        if kw in texto:
            normas_criticas.append({
                "numero": n.get("numero", "S/N"),
                "tipo_norma": n.get("tipo_nombre", "Ordenanza"),
                "titulo": n.get("titulo", "Sin título"),
                "categoria": n.get("categoria_nombre", "General"),
                "tipo_critica": tipo_critica,
                "anio": anio if anio > 0 else "Histórico",
                "url": n.get("url_detalle", "#")
            })
            break # Evitamos duplicados por tarjeta

# Ordenar las criticas por año (las mas recientes primero)
normas_criticas.sort(key=lambda x: str(x["anio"]), reverse=True)

# 2. Analisis por Periodo Historico (Matriz de Tendencias)
periodos = {
    "Años 90 (1990-1999)": [],
    "Años 2000 (2000-2009)": [],
    "Años 2010 (2010-2019)": [],
    "Años 2020 (2020-2026)": []
}

for n in normas:
    fecha = n.get("fecha")
    if fecha and "Año" in fecha:
        try:
            anio = int(fecha.replace("Año ", ""))
            cat = n.get("categoria_nombre", "Administración General")
            if 1990 <= anio <= 1999:
                periodos["Años 90 (1990-1999)"].append(cat)
            elif 2000 <= anio <= 2009:
                periodos["Años 2000 (2000-2009)"].append(cat)
            elif 2010 <= anio <= 2019:
                periodos["Años 2010 (2010-2019)"].append(cat)
            elif 2020 <= anio <= 2026:
                periodos["Años 2020 (2020-2026)"].append(cat)
        except Exception:
            pass

# 3. Generar Grafico Elegant circular de Categorias
categorias = [n.get("categoria_nombre", "Administración General") for n in normas]
cat_counts = Counter(categorias)

labels = list(cat_counts.keys())
sizes = list(cat_counts.values())

# Estilo premium oscuro
plt.style.use('dark_background')
fig, ax = plt.subplots(figsize=(10, 6), subplot_kw=dict(aspect="equal"))

# Paleta HSL
colors = ['#8b5cf6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#6366f1', '#ec4899', '#9ca3af']

wedges, texts, autotexts = ax.pie(sizes, autopct='%1.1f%%',
                                  textprops=dict(color="w"),
                                  colors=colors[:len(labels)],
                                  startangle=140,
                                  wedgeprops=dict(width=0.4, edgecolor='none'))

ax.legend(wedges, labels,
          title="Áreas Municipales",
          loc="center left",
          bbox_to_anchor=(1, 0, 0.5, 1))

plt.setp(autotexts, size=9, weight="bold")
ax.set_title("Distribución Temática General del Digesto", fontsize=14, weight="bold", pad=20)

plt.tight_layout()
plt.savefig(GRAPH_FILE, dpi=300, transparent=True)
plt.close()

# 4. Generar reporte Markdown
reporte = []
reporte.append("# Reporte Avanzado de Auditoría e Inteligencia del Digesto\n")
reporte.append("Este analisis avanzado procesa linguisticamente las tematicas y filtra anomalias criticas en la base de datos municipal.\n")

reporte.append("## 1. Visualización de Distribución de Áreas")
reporte.append(f"El grafico de distribucion sectorial ha sido guardado exitosamente en tu carpeta de trabajo local en: [reporte_grafico.png](file:///{GRAPH_FILE.replace(chr(92), '/')})\n")

reporte.append("## 2. Matriz de Tendencias Legislativas por Década")
reporte.append("Muestra en que areas se concentraba la gestion publica segun el periodo historico de la ciudad:\n")
reporte.append("| Período Histórico | Área Líder | Segunda Área | Tercera Área | Total de Normas en Periodo |")
reporte.append("| --- | --- | --- | --- | --- |")

for per, cats in periodos.items():
    if cats:
        counts = Counter(cats)
        top3 = counts.most_common(3)
        lider = f"{top3[0][0]} ({top3[0][1]} normas)" if len(top3) > 0 else "N/D"
        segunda = f"{top3[1][0]} ({top3[1][1]} normas)" if len(top3) > 1 else "N/D"
        tercera = f"{top3[2][0]} ({top3[2][1]} normas)" if len(top3) > 2 else "N/D"
        reporte.append(f"| {per} | {lider} | {segunda} | {tercera} | {len(cats)} |")
    else:
        reporte.append(f"| {per} | Sin registros suficientes | - | - | 0 |")

reporte.append("\n")

reporte.append("## 3. Listado de Alertas / Auditoría de Normas Críticas")
reporte.append("Las siguientes normas han sido detectadas automaticamente por contener palabras clave sensibles referidas a expropiaciones, donacion de tierras o licitaciones especiales:\n")
reporte.append("| N° Norma | Tipo | Año | Alerta / Temática Crítica | Título / Detalle | Enlace |")
reporte.append("| --- | --- | --- | --- | --- | --- |")

# Listar las 30 normas criticas mas recientes
for nc in normas_criticas[:30]:
    reporte.append(f"| {nc['numero']} | {nc['tipo_norma']} | {nc['anio']} | **{nc['tipo_critica']}** | {nc['titulo']} | [Ver en Web]({nc['url']}) |")

with open(REPORT_FILE, "w", encoding="utf-8") as f_rep:
    f_rep.write("\n".join(reporte))

print(f"¡Reporte avanzado e imagen generados con exito!")
