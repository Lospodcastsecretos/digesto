import { getQueryEmbedding } from './_lib/embeddings.js';

export default async function handler(req, res) {
  // Habilitar CORS
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
  const cacheUrl = process.env.TURSO_CACHE_URL || url;
  const cacheAuthToken = process.env.TURSO_CACHE_TOKEN || authToken;

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

    // Si hay una consulta de búsqueda, intentamos búsqueda híbrida Retrieve & Rank
    let queryVectorBlob = null;
    let candidateIds = [];

    if (query && query.trim() && openAiApiKey) {
      try {
        // 1. Obtener embedding (desde cache o generando uno nuevo)
        queryVectorBlob = await getQueryEmbedding(query, openAiApiKey, cacheUrl, cacheAuthToken);

        if (queryVectorBlob) {
          // 2. Recuperar candidatos broad (OR) de FTS5
          const ftsCandidatesQuery = parseFtsCandidatesQuery(query);
          if (ftsCandidatesQuery) {
            const candidatesResp = await fetch(pipelineUrl, {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${authToken}`,
                'Content-Type': 'application/json'
              },
              body: JSON.stringify({
                requests: [
                  {
                    type: "execute",
                    stmt: {
                      sql: "SELECT id FROM normas_fts WHERE normas_fts MATCH ? LIMIT 200",
                      args: [{ type: "text", value: ftsCandidatesQuery }]
                    }
                  },
                  { type: "close" }
                ]
              })
            });

            if (candidatesResp.ok) {
              const candidatesData = await candidatesResp.json();
              if (candidatesData.results && candidatesData.results[0] && candidatesData.results[0].response) {
                const rows = candidatesData.results[0].response.result.rows;
                candidateIds = rows.map(r => parseInt(r[0].value)).filter(id => !isNaN(id));
              }
            }
          }
        } else {
          console.warn("Fallo al obtener embeddings de OpenAI. Usando FTS sintáctico como fallback.");
        }
      } catch (err) {
        console.error("Error en Retrieve and Rank semántico:", err);
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

    if (queryVectorBlob && candidateIds.length > 0) {
      // BÚSQUEDA HÍBRIDA: RETRIEVE & RANK (Súper optimizada para evitar CPU/Timeouts en Turso)
      const idPlaceholders = candidateIds.map(() => "?").join(", ");
      
      sql = `
        SELECT id, numero, titulo, resumen, tipo_nombre, categoria_nombre, vigente, fecha, archivo_pdf, url_detalle,
               (1.0 - vector_distance_cos(embedding, ?)) AS vector_score,
               (CASE WHEN id IN (SELECT id FROM normas_fts WHERE normas_fts MATCH ?) THEN 1.0 ELSE 0.0 END) AS fts_score
        FROM normas
        WHERE id IN (${idPlaceholders}) ${filterSql}
        ORDER BY (fts_score * 0.6 + vector_score * 0.4) DESC
        LIMIT ? OFFSET ?
      `;
      
      params.push(
        queryVectorBlob, 
        parseFtsQuery(query),
        ...candidateIds, 
        ...filterParams, 
        itemsPerPage, 
        offset
      );

      // Conteo basado exclusivamente en los candidatos
      countSql = `SELECT COUNT(*) as total FROM normas WHERE id IN (${idPlaceholders}) ${filterSql}`;
      countParams.push(...candidateIds, ...filterParams);
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

// Función auxiliar para formatear una query amplia para la obtención de candidatos en Retrieve & Rank
function parseFtsCandidatesQuery(q) {
  if (!q) return "";
  const clean = q.replace(/[*\"'\-\+]/g, " ").trim();
  const words = clean.split(/\s+/).filter(w => w.length > 2);
  if (words.length === 0) return "";
  return words.map(w => `${w}*`).join(" OR ");
}
