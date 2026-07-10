import { registrarTelemetria } from './_lib/telemetria.js';
import { getQueryEmbedding } from './_lib/embeddings.js';

// Variables globales del Circuit Breaker (en memoria del contenedor warm de Vercel)
let dsFailures = 0;
let dsTrippedUntil = 0; // Timestamp en ms

// Diccionario de sinónimos jurídicos
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

export default async function handler(req, res) {
  const startTime = Date.now();
  // Habilitar CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }
  if (req.method !== 'POST') { res.status(405).json({ error: "Method not allowed" }); return; }

  const url = process.env.TURSO_URL;
  const authToken = process.env.TURSO_TOKEN;
  const deepseekKey = process.env.DEEPSEEK_API_KEY;
  const groqKey = process.env.GROQ_API_KEY;
  const openAiApiKey = process.env.OPENAI_API_KEY;
  
  // Base de datos de caché (con fallback si no está configurada)
  const cacheUrl = process.env.TURSO_CACHE_URL || url;
  const cacheAuthToken = process.env.TURSO_CACHE_TOKEN || authToken;

  if (!url || !authToken || (!deepseekKey && !groqKey)) {
    res.status(500).json({ error: "Faltan variables de entorno esenciales (TURSO_URL, TURSO_TOKEN, DEEPSEEK_API_KEY o GROQ_API_KEY)." });
    return;
  }

  const cleanUrl = url.replace("libsql://", "https://").replace("http://", "https://");
  const pipelineUrl = `${cleanUrl}/v2/pipeline`;
  
  const cleanCacheUrl = cacheUrl.replace("libsql://", "https://").replace("http://", "https://");
  const cachePipelineUrl = `${cleanCacheUrl}/v2/pipeline`;

  let body = req.body;
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch(e) {}
  }
  const { message, history, attachedNormIds, isTest } = body || {};
  if (!message) {
    res.status(400).json({ 
      error: `Mensaje vacío. Body: ${JSON.stringify(body)}. Typeof req.body: ${typeof req.body}. Content-Type: ${req.headers['content-type']}` 
    });
    return;
  }

  // Medidas de seguridad y límites de payload
  if (message.length > 1000) {
    res.status(400).json({ error: "El mensaje excede la longitud máxima permitida (1000 caracteres)." });
    return;
  }
  if (history && Array.isArray(history) && history.length > 15) {
    res.status(400).json({ error: "El historial de conversación es demasiado largo." });
    return;
  }
  if (attachedNormIds && Array.isArray(attachedNormIds) && attachedNormIds.length > 10) {
    res.status(400).json({ error: "No se pueden adjuntar más de 10 normas por consulta." });
    return;
  }

  // Helper para empaquetar el vector como Float32 Little-Endian en Base64
  const packVector = (arr) => {
    const buffer = new ArrayBuffer(arr.length * 4);
    const view = new DataView(buffer);
    arr.forEach((val, i) => {
      view.setFloat32(i * 4, val, true);
    });
    return Buffer.from(buffer).toString('base64');
  };

  const formatArgs = (args) => args.map(arg => {
    if (typeof arg === 'number') return { type: 'integer', value: arg.toString() };
    if (arg && typeof arg === 'object' && arg.type === 'blob') return arg;
    return { type: 'text', value: arg.toString() };
  });

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
    if (!resp.ok) return [];
    const data = await resp.json();
    const result = data.results[0];
    if (result.type === 'error') {
      console.error("Error en query de Turso Chat:", result.error.message);
      return [];
    }

    const cols = result.response.result.cols.map(c => c.name);
    return result.response.result.rows.map(row => {
      const obj = {};
      cols.forEach((col, i) => { obj[col] = row[i] ? row[i].value : null; });
      return obj;
    });
  }

  // Helper para interactuar con la base de datos de caché
  async function tursoCacheQuery(sql, params = []) {
    const body = {
      requests: [
        { type: "execute", stmt: { sql, args: formatArgs(params) } },
        { type: "close" }
      ]
    };
    const resp = await fetch(cachePipelineUrl, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${cacheAuthToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!resp.ok) return [];
    const data = await resp.json();
    const result = data.results[0];
    if (result.type === 'error') {
      console.error("Error en query de Turso Cache:", result.error.message);
      return [];
    }

    const cols = result.response.result.cols.map(c => c.name);
    return result.response.result.rows.map(row => {
      const obj = {};
      cols.forEach((col, i) => { obj[col] = row[i] ? row[i].value : null; });
      return obj;
    });
  }

  let contextText = "No se encontraron normas específicas relacionadas con la pregunta actual.";
  let suggestedNorms = [];
  let queryVectorBlob = null;
  let finalNormsRows = [];
  let isAttachedMode = false;

  // Modo 1: El usuario adjuntó normas específicas para hablar sobre ellas
  if (attachedNormIds && Array.isArray(attachedNormIds) && attachedNormIds.length > 0) {
    isAttachedMode = true;
    try {
      const placeholders = attachedNormIds.map(() => '?').join(',');
      const searchSql = `
        SELECT id, numero, titulo, resumen, tipo_nombre, fecha, texto_completo, vigente
        FROM normas 
        WHERE id IN (${placeholders})
      `;
      finalNormsRows = await tursoQuery(searchSql, attachedNormIds);
    } catch (e) {
      console.error("Error buscando normas adjuntas:", e);
    }
  } else {
    // Modo 2: Búsqueda RAG Semántica (Retrieve & Rank)
    const stopWords = new Set(['que', 'es', 'el', 'la', 'los', 'las', 'un', 'una', 'de', 'del', 'para', 'por', 'sobre', 'como', 'con', 'en', 'y', 'o', 'a', 'al', 'su', 'sus', 'te', 'tu', 'mi', 'se', 'lo', 'le']);
    const words = message.toLowerCase().replace(/[^a-záéíóúñü\s0-9]/g, '').split(/\s+/);
    const relevantWords = words.filter(w => w.length >= 3 && !stopWords.has(w));
    const keywords = relevantWords.map(w => expandirSinonimos(w)).join(' OR ');

    if (keywords.length > 0) {
      try {
        let candidateIds = [];

        // 2.1 Obtener embedding (desde cache o generando uno nuevo)
        if (openAiApiKey) {
          try {
            queryVectorBlob = await getQueryEmbedding(message, openAiApiKey, cacheUrl, cacheAuthToken);
          } catch (err) {
            console.error("Error al obtener embedding en Chat:", err);
          }
        }

        // 2.2 Obtener candidatos de FTS5
        const candidates = await tursoQuery("SELECT id FROM normas_fts WHERE normas_fts MATCH ? LIMIT 100", [keywords]);
        candidateIds = candidates.map(c => parseInt(c.id)).filter(id => !isNaN(id));

        let normasRows = [];

        if (queryVectorBlob && candidateIds.length > 0) {
          // Búsqueda Semántica Rankeada
          const placeholders = candidateIds.map(() => '?').join(',');
          const searchSql = `
            SELECT id, numero, titulo, resumen, tipo_nombre, fecha, texto_completo, vigente,
                   (1.0 - vector_distance_cos(embedding, ?)) AS vector_score
            FROM normas
            WHERE id IN (${placeholders})
            ORDER BY vector_score DESC LIMIT 5
          `;
          normasRows = await tursoQuery(searchSql, [queryVectorBlob, ...candidateIds]);
        } else if (candidateIds.length > 0) {
          // Fallback a sintáctico FTS5 tradicional
          const placeholders = candidateIds.map(() => '?').join(',');
          const searchSql = `
            SELECT id, numero, titulo, resumen, tipo_nombre, fecha, texto_completo, vigente
            FROM normas
            WHERE id IN (${placeholders}) LIMIT 5
          `;
          normasRows = await tursoQuery(searchSql, candidateIds);
        }

        finalNormsRows = normasRows;
      } catch (e) {
        console.error("Error buscando contexto RAG:", e);
      }
    }
  }

  // Ahora procesamos finalNormsRows para obtener relaciones y construir contextText
  if (finalNormsRows.length > 0) {
    try {
      const rowIds = finalNormsRows.map(n => n.id);
      const placeholders = rowIds.map(() => '?').join(',');
      const relacionesRows = await tursoQuery(`
        SELECT r.norma_origen_id, r.norma_destino_id, r.tipo_relacion, r.detalles,
               n_orig.numero as orig_numero, n_orig.tipo_nombre as orig_tipo,
               n_dest.numero as dest_numero, n_dest.tipo_nombre as dest_tipo
        FROM normas_relaciones r
        JOIN normas n_orig ON r.norma_origen_id = n_orig.id
        JOIN normas n_dest ON r.norma_destino_id = n_dest.id
        WHERE r.norma_origen_id IN (${placeholders}) OR r.norma_destino_id IN (${placeholders})
      `, [...rowIds, ...rowIds]);

      const relacionesPorNorma = {};
      relacionesRows.forEach(rel => {
        if (rowIds.includes(rel.norma_origen_id)) {
          if (!relacionesPorNorma[rel.norma_origen_id]) relacionesPorNorma[rel.norma_origen_id] = [];
          relacionesPorNorma[rel.norma_origen_id].push(
            `Esta norma ${rel.tipo_relacion.toUpperCase()} a la ${rel.dest_tipo} N° ${rel.dest_numero} (${rel.detalles || 'sin detalles'}).`
          );
        }
        if (rowIds.includes(rel.norma_destino_id)) {
          if (!relacionesPorNorma[rel.norma_destino_id]) relacionesPorNorma[rel.norma_destino_id] = [];
          relacionesPorNorma[rel.norma_destino_id].push(
            `Esta norma fue afectada por la ${rel.orig_tipo} N° ${rel.orig_numero} (Relación: ${rel.tipo_relacion.toUpperCase()}). Detalles: ${rel.detalles || 'sin detalles'}.`
          );
        }
      });

      const formatted = finalNormsRows.map(n => {
        const textoDetalle = (n.texto_completo || n.resumen || "").substring(0, 1500);
        const vigenciaStr = n.vigente ? "Vigente (Activa)" : "NO VIGENTE (Derogada, Modificada o Reemplazada)";
        const relacionesNorma = relacionesPorNorma[n.id] || [];
        const relacionesStr = relacionesNorma.length > 0 
          ? `\nRelaciones Históricas:\n- ${relacionesNorma.join('\n- ')}` 
          : '';
        return `Norma: ${n.tipo_nombre} ${n.numero}\nEstado: ${vigenciaStr}\nFecha: ${n.fecha}\nTítulo: ${n.titulo}${relacionesStr}\nTexto de la Norma (Fragmento amplio):\n${textoDetalle}...`;
      }).join("\n\n---\n\n");

      if (isAttachedMode) {
        contextText = "[NIVEL DE ATENCIÓN MÁXIMO] El ciudadano ha adjuntado las siguientes normas específicas para conversar sobre ellas:\n\n" + formatted;
      } else {
        contextText = formatted;
      }
      suggestedNorms = finalNormsRows.map(n => ({ id: n.id, numero: n.numero, tipo_nombre: n.tipo_nombre, titulo: n.titulo }));
    } catch (err) {
      console.error("Error al dar formato y resolver relaciones en Chat:", err);
      // Fallback básico en caso de error en relaciones
      contextText = finalNormsRows.map(n => {
        const textoDetalle = (n.texto_completo || n.resumen || "").substring(0, 1500);
        return `Norma: ${n.tipo_nombre} ${n.numero}\nFecha: ${n.fecha}\nTítulo: ${n.titulo}\nTexto de la Norma (Fragmento amplio):\n${textoDetalle}...`;
      }).join("\n\n---\n\n");
      suggestedNorms = finalNormsRows.map(n => ({ id: n.id, numero: n.numero, tipo_nombre: n.tipo_nombre, titulo: n.titulo }));
    }
  }

  // 3. Preparar el Prompt para Gemini
  let promptHistory = "";
  if (history && Array.isArray(history)) {
    // Tomar solo los últimos 6 mensajes para no sobrecargar
    const recentHistory = history.slice(-6);
    promptHistory = recentHistory.map(msg => `${msg.role === 'user' ? 'Ciudadano' : 'Asistente'}: ${msg.content}`).join('\n');
  }

  const systemPrompt = `Eres Burocracio, un asistente jurídico virtual amigable, claro y resolutivo para el Digesto Municipal (un buscador de leyes y ordenanzas locales). Tu objetivo es ayudar a los ciudadanos y funcionarios a entender normativas basándote en la base de datos oficial.

REGLAS DE COMPORTAMIENTO:
1. Sé amable, directo y evita lenguaje excesivamente técnico si no es necesario.
2. Si la base de datos te provee contexto (normas encontradas), basa tu respuesta ESTRICTAMENTE en esa información. Cita el número de norma (ej. "Según la Ordenanza 1234...").
3. Si la base de datos NO provee información sobre la pregunta, indica amablemente que no tienes información exacta sobre ese tema en el digesto actual, pero ofrece ayuda con otros temas. No inventes leyes.
4. Usa formato Markdown (negritas para destacar cosas importantes, viñetas para listas) para que sea fácil de leer.
5. Mantén tus respuestas relativamente cortas (máximo 2-3 párrafos cortos). No te presentes con tu nombre a menos que el usuario te pregunte quién eres.`;

CONTEXTO DE NORMAS ENCONTRADAS PARA LA PREGUNTA ACTUAL:
${contextText}

HISTORIAL DE LA CONVERSACIÓN RECIENTE:
${promptHistory}

PREGUNTA ACTUAL DEL CIUDADANO:
${message}

Tu respuesta (como asistente jurídico del municipio):`;

  // 4. Configurar headers para Streaming SSE
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache, no-transform',
    'Connection': 'keep-alive',
    'Access-Control-Allow-Origin': '*'
  });

  // 5. Verificar caché semántica antes de llamar al LLM
  if (queryVectorBlob && !attachedNormIds?.length) {
    try {
      const cacheRows = await tursoCacheQuery(
        "SELECT response_text FROM semantic_cache WHERE query_text LIKE 'chat:%' AND (1.0 - vector_distance_cos(embedding, ?)) > 0.81 LIMIT 1",
        [queryVectorBlob]
      );
      if (cacheRows.length > 0) {
        const cachedResponse = cacheRows[0].response_text;
        console.log(`[CACHE HIT] Respondiendo desde la cache semantica de Turso.`);
        
        // Simular un ligero streaming para una experiencia de usuario natural
        const words = cachedResponse.split(" ");
        for (let i = 0; i < words.length; i++) {
          const chunk = words[i] + (i < words.length - 1 ? " " : "");
          res.write(`data: ${JSON.stringify({ text: chunk })}\n\n`);
          // Pequeña pausa cada 4 palabras
          if (i % 4 === 0) {
            await new Promise(r => setTimeout(r, 20));
          }
        }
        
        res.write(`data: ${JSON.stringify({ suggestedNorms, provider: "Caché Semántica (Turso)" })}\n\n`);
        res.end();
        
        if (!isTest) {
          await registrarTelemetria('chat', message, true, Date.now() - startTime, 0, 0);
        }
        return;
      }
    } catch (cacheErr) {
      console.error("Error leyendo cache semantica:", cacheErr);
    }
  }

  async function streamOpenAI(url, apiKey, bodyData) {
    const resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        ...bodyData,
        stream: true
      })
    });

    if (!resp.ok) {
      const errText = await resp.text();
      throw new Error(`Status ${resp.status}: ${errText}`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let fullText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        const cleanLine = line.trim();
        if (!cleanLine) continue;
        if (cleanLine === 'data: [DONE]') continue;
        if (cleanLine.startsWith('data: ')) {
          try {
            const jsonStr = cleanLine.substring(6);
            const parsed = JSON.parse(jsonStr);
            const delta = parsed.choices[0].delta?.content || '';
            if (delta) {
              fullText += delta;
              res.write(`data: ${JSON.stringify({ text: delta })}\n\n`);
            }
          } catch (err) {
            // Ignorar
          }
        }
      }
    }
    return fullText;
  }

  let activeProvider = 'DeepSeek (Principal)';
  const isDsTripped = Date.now() < dsTrippedUntil;
  let llmResponse = "";

  try {
    if (isDsTripped) {
      console.warn("Circuit Breaker activado para DeepSeek. Saltando directo a Groq...");
      throw new Error("DeepSeek Circuit Breaker activado");
    }

    // Intento 1: DeepSeek Streaming
    llmResponse = await streamOpenAI("https://api.deepseek.com/chat/completions", deepseekKey, {
      model: "deepseek-chat",
      messages: [
        { role: "system", content: systemPrompt },
        { role: "user", content: message }
      ],
      temperature: 0.2,
      max_tokens: 1500
    });
    
    // Si tiene éxito, resetear contador de fallos
    dsFailures = 0;
  } catch (errDeepSeek) {
    if (!isDsTripped) {
      dsFailures++;
      console.warn(`Fallo DeepSeek Stream (${dsFailures}/3). Error:`, errDeepSeek.message);
      if (dsFailures >= 3) {
        // Activar disyuntor por 5 minutos
        dsTrippedUntil = Date.now() + 5 * 60 * 1000;
        console.error("-> CIRCUIT BREAKER ACTIVADO: DeepSeek falló 3 veces. Se usará Groq por los próximos 5 minutos.");
      }
    }
    
    activeProvider = 'Groq (Respaldo)';
    
    try {
      // Intento 2: Fallback Groq Streaming
      llmResponse = await streamOpenAI("https://api.groq.com/openai/v1/chat/completions", groqKey, {
        model: "llama-3.1-8b-instant",
        messages: [
          { role: "system", content: systemPrompt },
          { role: "user", content: message }
        ],
        temperature: 0.2,
        max_tokens: 1500
      });
    } catch (errGroq) {
      console.error("Error en API de Chat Multi-IA (Groq falló también):", errGroq);
      res.write(`data: ${JSON.stringify({ error: "No se pudo conectar con los proveedores de IA: " + errGroq.message })}\n\n`);
      activeProvider = 'Ninguno (Fallo)';
    }
  }

  // Guardar en caché semántica si obtuvimos respuesta exitosa
  if (queryVectorBlob && llmResponse && !attachedNormIds?.length) {
    try {
      await tursoCacheQuery(
        "INSERT OR IGNORE INTO semantic_cache (query_text, embedding, response_text) VALUES (?, ?, ?)",
        [`chat:${message.trim()}`, queryVectorBlob, llmResponse]
      );
      console.log("[CACHE WRITE] Respuesta guardada en cache semantica de Turso.");
    } catch (cacheWriteErr) {
      console.error("Error al guardar en cache semantica:", cacheWriteErr);
    }
  }

  // Enviar las sugerencias de normas, el proveedor y finalizar la conexión
  res.write(`data: ${JSON.stringify({ suggestedNorms, provider: activeProvider })}\n\n`);
  res.end();
  
  if (!isTest) {
    await registrarTelemetria('chat', message, false, Date.now() - startTime, 0, 0);
  }
}
