export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS,POST');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  const url = process.env.TURSO_URL;
  const authToken = process.env.TURSO_TOKEN;

  if (!url || !authToken) {
    res.status(500).json({ error: "Faltan las variables de entorno de conexión a Turso." });
    return;
  }

  const cleanUrl = url.replace("libsql://", "https://").replace("http://", "https://");
  const pipelineUrl = `${cleanUrl}/v2/pipeline`;

  const { query, tipo, categoria, anio, vigencia } = req.query;

  const SINONIMOS = {
    'exencion': ['exencion', 'exenciones', 'eximicion', 'eximiciones', 'exento', 'exenta', 'exentos', 'eximir'],
    'tasa': ['tasa', 'tasas', 'tributo', 'tributos', 'gravamen', 'gravamenes', 'derecho', 'derechos'],
    'obra': ['obra', 'obras', 'construccion', 'construcciones', 'edificacion', 'edificaciones', 'refaccion'],
    'multa': ['multa', 'multas', 'sancion', 'sanciones', 'infraccion', 'infracciones', 'penalidad'],
    'poda': ['poda', 'podas', 'arbol', 'arboles', 'forestacion', 'desrame', 'tala', 'verde']
  };

  function expandirSinonimos(word) {
    const clean = word.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]/g, "");
    if (!clean) return `"${word}"*`;
    for (const [key, list] of Object.entries(SINONIMOS)) {
      if (clean === key || list.some(item => item.normalize("NFD").replace(/[\u0300-\u036f]/g, "") === clean)) {
        return `(${list.map(term => `"${term}"*`).join(' OR ')})`;
      }
    }
    return `"${word}"*`;
  }

  function parseFtsQuery(q) {
    if (!q) return "";
    const regex = /("[^"]+"|-\S+|\S+)/g;
    const tokens = q.match(regex) || [];
    const parsedTokens = tokens.map(token => {
      if (token.startsWith('-')) {
        const term = token.substring(1).replace(/[^a-zA-Z0-9áéíóúñü]/g, "");
        return term ? `NOT "${term}"*` : "";
      }
      if (token.startsWith('"') && token.endsWith('"')) {
        const cleanInner = token.slice(1, -1).replace(/["']/g, "");
        return cleanInner ? `"${cleanInner}"` : "";
      }
      const cleanWord = token.replace(/[^a-zA-Z0-9áéíóúñü]/g, "");
      if (!cleanWord || cleanWord.length < 3) return "";
      return expandirSinonimos(cleanWord);
    }).filter(Boolean);
    
    let result = "";
    for (let i = 0; i < parsedTokens.length; i++) {
      const t = parsedTokens[i];
      if (i > 0) {
        result += t.startsWith("NOT ") ? ` ${t}` : ` AND ${t}`;
      } else {
        result += t.startsWith("NOT ") ? `* ${t}` : t;
      }
    }
    return result;
  }

  try {
    let sql = "SELECT id, numero, titulo, resumen, tipo_nombre, categoria_nombre, vigente, fecha FROM normas WHERE 1=1";
    const params = [];

    if (query) {
      sql += " AND id IN (SELECT id FROM normas_fts WHERE normas_fts MATCH ?)";
      params.push(parseFtsQuery(query));
    }

    if (tipo && tipo !== 'todos') {
      sql += " AND tipo_nombre = ?";
      params.push(tipo);
    }

    if (categoria && categoria !== 'todas') {
      sql += " AND categoria_nombre = ?";
      params.push(categoria);
    }

    if (anio && anio !== 'todos') {
      sql += " AND fecha = ?";
      params.push(`Año ${anio}`);
    }

    if (vigencia && vigencia !== 'todos') {
      const isVigente = vigencia === 'si' ? 1 : 0;
      sql += " AND vigente = ?";
      params.push(isVigente);
    }

    // Ordenar por relevancia o por fecha (en lote, limitamos a 600 por estabilidad en plan Hobby)
    sql += " LIMIT 600";

    const formatArgs = (args) => args.map(arg => {
      if (typeof arg === 'number') return { type: 'integer', value: arg.toString() };
      return { type: 'text', value: arg.toString() };
    });

    const payload = {
      requests: [
        { type: "execute", stmt: { sql, args: formatArgs(params) } },
        { type: "close" }
      ]
    };

    const response = await fetch(pipelineUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${authToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const errTxt = await response.text();
      throw new Error(`Turso Error: ${errTxt}`);
    }

    const data = await response.json();
    const result = data.results[0];
    if (result.type === "error") {
      throw new Error(result.error.message);
    }

    const resVal = result.response.result;
    const cols = resVal.cols.map(c => c.name);
    const normas = resVal.rows.map(rVal => {
      const row = {};
      rVal.forEach((val, idx) => {
        row[cols[idx]] = val ? val.value : null;
      });
      // Convertir vigente a boolean
      if (row.hasOwnProperty('vigente')) {
        row.vigente = row.vigente === 1;
      }
      return row;
    });

    res.status(200).json({ normas });
  } catch (error) {
    console.error("Error en buscar-todo:", error);
    res.status(500).json({ error: error.message });
  }
}
