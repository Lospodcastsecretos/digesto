export default async function handler(req, res) {
  // Habilitar CORS
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }

  const url = process.env.TURSO_URL;
  const authToken = process.env.TURSO_TOKEN;

  if (!url || !authToken) {
    res.status(500).json({ error: "Faltan variables de entorno TURSO_URL o TURSO_TOKEN." });
    return;
  }

  const cleanUrl = url.replace("libsql://", "https://").replace("http://", "https://");
  const pipelineUrl = `${cleanUrl}/v2/pipeline`;

  const { query, tipo, categoria, anio, vigencia } = req.query;

  const formatArgs = (args) => args.map(arg => {
    if (typeof arg === 'number') return { type: 'integer', value: arg.toString() };
    return { type: 'text', value: arg.toString() };
  });

  // Ejecutar una query a Turso via pipeline
  async function tursoQuery(sql, params = []) {
    const body = {
      requests: [
        { type: "execute", stmt: { sql, args: formatArgs(params) } },
        { type: "close" }
      ]
    };
    const resp = await fetch(pipelineUrl, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!resp.ok) throw new Error(`Turso error: ${resp.status}`);
    const data = await resp.json();
    const result = data.results[0];
    if (result.type === 'error') throw new Error(result.error.message);

    const cols = result.response.result.cols.map(c => c.name);
    return result.response.result.rows.map(row => {
      const obj = {};
      cols.forEach((col, i) => { obj[col] = row[i] ? row[i].value : null; });
      return obj;
    });
  }

  try {
    // ========== Construir WHERE compartido ==========
    let whereClauses = ["1=1"];
    const params = [];

    if (query) {
      whereClauses.push("(lower(numero) LIKE ? OR lower(titulo) LIKE ? OR lower(resumen) LIKE ?)");
      const lq = `%${query.toLowerCase()}%`;
      params.push(lq, lq, lq);
    }
    if (tipo && tipo !== 'todos') {
      whereClauses.push("tipo_nombre = ?");
      params.push(tipo);
    }
    if (categoria && categoria !== 'todas') {
      whereClauses.push("categoria_nombre = ?");
      params.push(categoria);
    }
    if (anio && anio !== 'todos') {
      whereClauses.push("fecha = ?");
      params.push(`Año ${anio}`);
    }
    if (vigencia && vigencia !== 'todos') {
      whereClauses.push("vigente = ?");
      params.push(vigencia === 'si' ? 1 : 0);
    }

    const whereStr = whereClauses.join(" AND ");

    // ========== 1. Frecuencia por tipo de norma ==========
    const frecuenciaRows = await tursoQuery(
      `SELECT tipo_nombre, COUNT(*) as cantidad FROM normas WHERE ${whereStr} GROUP BY tipo_nombre ORDER BY cantidad DESC`,
      params
    );
    const totalFrecuencia = frecuenciaRows.reduce((sum, r) => sum + parseInt(r.cantidad), 0);

    // ========== 2. Distribución por año (timeline) ==========
    const timelineRows = await tursoQuery(
      `SELECT fecha, COUNT(*) as cantidad FROM normas WHERE ${whereStr} GROUP BY fecha ORDER BY fecha`,
      params
    );

    // ========== 3. Normas relacionadas (misma categoría, distinto término) ==========
    let relacionadas = [];
    if (query) {
      // Obtener las categorías más frecuentes en la búsqueda actual
      const topCategorias = await tursoQuery(
        `SELECT categoria_nombre, COUNT(*) as cnt FROM normas WHERE ${whereStr} AND categoria_nombre IS NOT NULL GROUP BY categoria_nombre ORDER BY cnt DESC LIMIT 3`,
        params
      );

      if (topCategorias.length > 0) {
        const catPlaceholders = topCategorias.map(() => '?').join(',');
        const catParams = topCategorias.map(c => c.categoria_nombre);
        const excludeLike = `%${query.toLowerCase()}%`;

        relacionadas = await tursoQuery(
          `SELECT id, numero, titulo, resumen, tipo_nombre, categoria_nombre, fecha FROM normas 
           WHERE categoria_nombre IN (${catPlaceholders}) 
           AND lower(titulo) NOT LIKE ? 
           AND lower(resumen) NOT LIKE ?
           ORDER BY RANDOM() LIMIT 10`,
          [...catParams, excludeLike, excludeLike]
        );
      }
    }

    // ========== 4. Top keywords (palabras más frecuentes en títulos) ==========
    const titulosRows = await tursoQuery(
      `SELECT titulo FROM normas WHERE ${whereStr} LIMIT 100`,
      params
    );

    // Extraer y contar palabras significativas de los títulos
    const stopWords = new Set([
      'de', 'del', 'la', 'el', 'en', 'y', 'a', 'los', 'las', 'por', 'para', 'con', 'un', 'una',
      'que', 'se', 'al', 'es', 'lo', 'su', 'no', 'como', 'más', 'o', 'pero', 'sus', 'le', 'ya',
      'este', 'ha', 'me', 'mi', 'sin', 'sobre', 'entre', 'nos', 'ser', 'son', 'desde', 'está',
      'todo', 'esta', 'fue', 'hay', 'muy', 'dos', 'también', 'esa', 'ese', 'asi', 'cuando',
      'articulo', 'art', 'nro', 'num', 'decreto', 'ordenanza', 'resolución', 'resolucion',
      'municipal', 'municipalidad', 'alta', 'gracia', 'concejo', 'deliberante', 'departamento',
      'ejecutivo', 'nº', 'n°', 'año', 'inc', 'ley', 'provincia', 'cordoba', 'córdoba'
    ]);

    const wordCounts = {};
    titulosRows.forEach(row => {
      if (!row.titulo) return;
      const words = row.titulo.toLowerCase()
        .normalize('NFD').replace(/[\u0300-\u036f]/g, '') // quitar acentos
        .replace(/[^a-záéíóúñü\s]/gi, ' ')
        .split(/\s+/)
        .filter(w => w.length > 3 && !stopWords.has(w));
      words.forEach(w => { wordCounts[w] = (wordCounts[w] || 0) + 1; });
    });

    const keywords = Object.entries(wordCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 25)
      .map(([palabra, frecuencia]) => ({ palabra, frecuencia }));

    // ========== Respuesta final ==========
    res.status(200).json({
      frecuencia: {
        total: totalFrecuencia,
        por_tipo: frecuenciaRows.map(r => ({ tipo: r.tipo_nombre, cantidad: parseInt(r.cantidad) }))
      },
      timeline: timelineRows.map(r => ({ anio: r.fecha, cantidad: parseInt(r.cantidad) })),
      relacionadas: relacionadas.map(r => ({
        id: parseInt(r.id),
        numero: r.numero,
        tipo_nombre: r.tipo_nombre,
        titulo: r.titulo,
        resumen: r.resumen,
        categoria_nombre: r.categoria_nombre,
        fecha: r.fecha
      })),
      keywords
    });

  } catch (error) {
    console.error("Error en estadísticas:", error);
    res.status(500).json({ error: error.message });
  }
}
