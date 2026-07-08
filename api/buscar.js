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
  const openAiApiKey = process.env.OPENAI_API_KEY;

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
    let sql = "";
    const params = [];
    let countSql = "";
    const countParams = [];

    // Helper para formatear argumentos para el endpoint pipeline de Turso
    const formatArgs = (args) => {
      return args.map(arg => {
        if (typeof arg === 'number') {
          return { type: 'integer', value: arg.toString() };
        }
        if (arg && typeof arg === 'object' && arg.type === 'blob') {
          return arg; // Pasar blob directamente
        }
        return { type: 'text', value: arg ? arg.toString() : '' };
      });
    };

    // Helper para empaquetar el vector como Float32 Little-Endian en Base64
    const packVector = (arr) => {
      const buffer = new ArrayBuffer(arr.length * 4);
      const view = new DataView(buffer);
      arr.forEach((val, i) => {
        view.setFloat32(i * 4, val, true); // true = little endian
      });
      // En Node.js podemos convertir un ArrayBuffer a Buffer y luego a base64
      return Buffer.from(buffer).toString('base64');
    };

    // Si hay una consulta de búsqueda, intentamos búsqueda híbrida
    let queryVectorBlob = null; // Desactivado temporalmente para liberar la CPU de Turso
    if (false && query && query.trim() && openAiApiKey) {
      try {
        // Llamada directa a los embeddings de OpenAI
        const openAiResp = await fetch("https://api.openai.com/v1/embeddings", {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${openAiApiKey}`,
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            input: query.trim(),
            model: "text-embedding-3-small"
          })
        });

        if (openAiResp.ok) {
          const openAiData = await openAiResp.json();
          const vector = openAiData.data[0].embedding;
          queryVectorBlob = { type: 'blob', base64: packVector(vector) };
        } else {
          console.warn("Fallo al obtener embeddings de OpenAI. Usando FTS sintáctico como fallback.");
        }
      } catch (err) {
        console.error("Error obteniendo embeddings de OpenAI:", err);
      }
    }

    // Filtros de metadatos comunes
    let filterSql = "";
    const filterParams = [];

    if (tipo && tipo !== 'todos') {
      filterSql += " AND tipo_nombre = ?";
      filterParams.push(tipo);
    }
    if (categoria && categoria !== 'todas') {
      filterSql += " AND categoria_nombre = ?";
      filterParams.push(categoria);
    }
    if (anio && anio !== 'todos') {
      filterSql += " AND fecha = ?";
      filterParams.push(`Año ${anio}`);
    }
    if (vigencia && vigencia !== 'todos') {
      const isVigente = vigencia === 'si' ? 1 : 0;
      filterSql += " AND vigente = ?";
      filterParams.push(isVigente);
    }

    if (queryVectorBlob) {
      // BÚSQUEDA HÍBRIDA (FTS5 + Vectorial)
      // fts_score: 1.0 si coincide exactamente con FTS, 0.0 si no.
      // vector_score: similitud de cosenos normalizada (1.0 - distancia)
      sql = `
        SELECT id, numero, titulo, resumen, tipo_nombre, categoria_nombre, vigente, fecha, archivo_pdf, url_detalle,
               (1.0 - vector_distance_cos(embedding, ?)) AS vector_score,
               (CASE WHEN id IN (SELECT id FROM normas_fts WHERE normas_fts MATCH ?) THEN 1.0 ELSE 0.0 END) AS fts_score
        FROM normas
        WHERE embedding IS NOT NULL ${filterSql}
        ORDER BY (fts_score * 0.6 + vector_score * 0.4) DESC
        LIMIT ? OFFSET ?
      `;
      params.push(queryVectorBlob, parseFtsQuery(query), ...filterParams, itemsPerPage, offset);

      // Consulta de conteo para búsqueda vectorial
      countSql = `SELECT COUNT(*) as total FROM normas WHERE embedding IS NOT NULL ${filterSql}`;
      countParams.push(...filterParams);
    } else if (query) {
      // FALLBACK: Búsqueda sintáctica FTS5 tradicional
      sql = `
        SELECT id, numero, titulo, resumen, tipo_nombre, categoria_nombre, vigente, fecha, archivo_pdf, url_detalle,
               0.0 AS vector_score, 1.0 AS fts_score
        FROM normas
        WHERE id IN (SELECT id FROM normas_fts WHERE normas_fts MATCH ?) ${filterSql}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
      `;
      params.push(parseFtsQuery(query), ...filterParams, itemsPerPage, offset);

      countSql = `SELECT COUNT(*) as total FROM normas WHERE id IN (SELECT id FROM normas_fts WHERE normas_fts MATCH ?) ${filterSql}`;
      countParams.push(parseFtsQuery(query), ...filterParams);
    } else {
      // SIN CONSULTA: Listar de forma tradicional
      sql = `
        SELECT id, numero, titulo, resumen, tipo_nombre, categoria_nombre, vigente, fecha, archivo_pdf, url_detalle,
               0.0 AS vector_score, 0.0 AS fts_score
        FROM normas
        WHERE 1=1 ${filterSql}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
      `;
      params.push(...filterParams, itemsPerPage, offset);

      countSql = `SELECT COUNT(*) as total FROM normas WHERE 1=1 ${filterSql}`;
      countParams.push(...filterParams);
    }

    // Ejecutar ambas consultas en un batch (pipeline) de Turso para máxima velocidad
    const requestBody = {
      requests: [
        {
          type: "execute",
          stmt: {
            sql: countSql,
            args: formatArgs(countParams)
          }
        },
        {
          type: "execute",
          stmt: {
            sql: sql,
            args: formatArgs(params)
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

      // Calcular porcentaje de relevancia
      let relevancia = null;
      if (queryVectorBlob) {
        const vScore = parseFloat(item.vector_score) || 0;
        const fScore = parseFloat(item.fts_score) || 0;
        // Ajustamos la relevancia para que se vea amigable en la interfaz (escala 0-100)
        // La similitud de coseno en text-embedding-3-small suele rondar entre 0.1 y 0.7 para textos legales
        const normalizedVector = Math.min(Math.max((vScore - 0.15) / 0.55, 0), 1);
        relevancia = Math.round((fScore * 0.5 + normalizedVector * 0.5) * 100);
      }

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
        url_detalle: item.url_detalle,
        relevancia: relevancia
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
