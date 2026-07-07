export default async function handler(req, res) {
  // Habilitar CORS
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS,PATCH,DELETE,POST,PUT');
  res.setHeader(
    'Access-Control-Allow-Headers',
    'X-CSRF-Token, X-Requested-With, Accept, Accept-Version, Content-Length, Content-MD5, Content-Type, Date, X-Api-Version'
  );

  if (req.method === 'OPTIONS') {
    res.status(200).end();
    return;
  }

  // Leer tokens desde las variables de entorno de Vercel
  const url = process.env.TURSO_URL;
  const authToken = process.env.TURSO_TOKEN;

  if (!url || !authToken) {
    res.status(500).json({ error: "Faltan las variables de entorno de conexión a Turso (TURSO_URL o TURSO_TOKEN)." });
    return;
  }

  // Limpiar URL para usar la REST API de Turso (/v2/pipeline)
  const cleanUrl = url.replace("libsql://", "https://").replace("http://", "https://");
  const pipelineUrl = `${cleanUrl}/v2/pipeline`;

  const { query, tipo, categoria, anio, vigencia, page } = req.query;

  const itemsPerPage = 15;
  const currentPage = parseInt(page) || 1;
  const offset = (currentPage - 1) * itemsPerPage;

  try {
    let sql = "SELECT id, numero, titulo, resumen, tipo_nombre, categoria_nombre, vigente, fecha, archivo_pdf, url_detalle FROM normas WHERE 1=1";
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

    // Clonar sql y params para el conteo total
    let countSql = sql.replace("SELECT id, numero, titulo, resumen, tipo_nombre, categoria_nombre, vigente, fecha, archivo_pdf, url_detalle FROM normas", "SELECT COUNT(*) as total FROM normas");

    // Construir la consulta paginada
    let paginatedSql = sql + " ORDER BY id DESC LIMIT ? OFFSET ?";
    const paginatedParams = [...params, itemsPerPage, offset];

    // Helper para formatear argumentos para el endpoint pipeline de Turso
    const formatArgs = (args) => {
      return args.map(arg => {
        if (typeof arg === 'number') {
          return { type: 'integer', value: arg.toString() };
        }
        return { type: 'text', value: arg.toString() };
      });
    };

    // Ejecutar ambas consultas en un batch (pipeline) de Turso para máxima velocidad
    const requestBody = {
      requests: [
        {
          type: "execute",
          stmt: {
            sql: countSql,
            args: formatArgs(params)
          }
        },
        {
          type: "execute",
          stmt: {
            sql: paginatedSql,
            args: formatArgs(paginatedParams)
          }
        },
        {
          type: "close"
        }
      ]
    };

    const response = await fetch(pipelineUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${authToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(requestBody)
    });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`Error en API de Turso: ${response.status} - ${errText}`);
    }

    const responseData = await response.json();

    // Validar respuestas del pipeline
    const countResponse = responseData.results[0];
    const selectResponse = responseData.results[1];

    if (countResponse.type === 'error') {
      throw new Error(`Error en conteo: ${countResponse.error.message}`);
    }
    if (selectResponse.type === 'error') {
      throw new Error(`Error en consulta: ${selectResponse.error.message}`);
    }

    // Extraer total de items
    const countRows = countResponse.response.result.rows;
    const totalItems = countRows.length > 0 ? parseInt(countRows[0][0].value) : 0;

    // Extraer filas de las normas
    const selectResult = selectResponse.response.result;
    const cols = selectResult.cols.map(c => c.name);
    const selectRows = selectResult.rows;

    const normas = selectRows.map(rowValues => {
      const item = {};
      cols.forEach((colName, index) => {
        const valObj = rowValues[index];
        item[colName] = valObj ? valObj.value : null;
      });

      return {
        id: item.id ? parseInt(item.id) : null,
        numero: item.numero,
        titulo: item.titulo,
        resumen: item.resumen,
        tipo_nombre: item.tipo_nombre,
        categoria_nombre: item.categoria_nombre,
        vigente: item.vigente === '1' || item.vigente === 1,
        fecha: item.fecha,
        archivo_pdf: item.archivo_pdf,
        url_detalle: item.url_detalle
      };
    });

    res.status(200).json({
      normas: normas,
      total: totalItems,
      page: currentPage,
      totalPages: Math.ceil(totalItems / itemsPerPage)
    });

  } catch (error) {
    console.error("Error en la consulta de Turso:", error);
    res.status(500).json({ error: error.message });
  }
}

// Diccionario de sinónimos jurídicos y términos frecuentes en el Digesto de Alta Gracia
const SINONIMOS = {
  'exencion': ['exencion', 'exenciones', 'eximicion', 'eximiciones', 'exento', 'exenta', 'exentos', 'eximir'],
  'tasa': ['tasa', 'tasas', 'tributo', 'tributos', 'gravamen', 'gravamenes', 'derecho', 'derechos'],
  'obra': ['obra', 'obras', 'construccion', 'construcciones', 'edificacion', 'edificaciones', 'refaccion'],
  'multa': ['multa', 'multas', 'sancion', 'sanciones', 'infraccion', 'infracciones', 'penalidad'],
  'poda': ['poda', 'podas', 'arbol', 'arboles', 'forestacion', 'desrame', 'tala', 'verde']
};

function expandirSinonimos(word) {
  // Limpiar acentos y pasar a minúsculas
  const clean = word.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]/g, "");
  if (!clean) return `"${word}"*`;

  for (const [key, list] of Object.entries(SINONIMOS)) {
    if (clean === key || list.some(item => item.normalize("NFD").replace(/[\u0300-\u036f]/g, "") === clean)) {
      return `(${list.map(term => `"${term}"*`).join(' OR ')})`;
    }
  }
  return `"${word}"*`;
}

// Función auxiliar para formatear la query a la sintaxis MATCH de SQLite FTS5
function parseFtsQuery(q) {
  if (!q) return "";
  
  // Buscar frases exactas, términos excluidos y palabras comunes
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
      if (t.startsWith("NOT ")) {
        result += ` ${t}`;
      } else {
        result += ` AND ${t}`;
      }
    } else {
      if (t.startsWith("NOT ")) {
        result += `* ${t}`;
      } else {
        result += t;
      }
    }
  }
  return result;
}
