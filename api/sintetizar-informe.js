import { registrarTelemetria } from './_lib/telemetria.js';
import { getQueryEmbedding } from './_lib/embeddings.js';
import { isRateLimited } from './_lib/rateLimit.js';

// Variables globales del Circuit Breaker (en memoria de Vercel)
let dsFailures = 0;
let dsTrippedUntil = 0; // Timestamp en ms

export default async function handler(req, res) {
  const startTime = Date.now();
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }

  const deepseekKey = process.env.DEEPSEEK_API_KEY;
  const groqKey = process.env.GROQ_API_KEY;
  const openAiApiKey = process.env.OPENAI_API_KEY;
  const cacheUrl = process.env.TURSO_CACHE_URL || process.env.TURSO_URL;
  const cacheAuthToken = process.env.TURSO_CACHE_TOKEN || process.env.TURSO_TOKEN;

  if (!deepseekKey && !groqKey) {
    res.status(500).json({ error: "Faltan variables de entorno esenciales para IA." });
    return;
  }

  let body = req.body;
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch(e) {}
  }

  // Aplicar Rate Limiting (Máximo 5 consultas de informe por minuto)
  const isLimited = await isRateLimited(req, 'sintetizar-informe', 5, 60, cacheUrl, cacheAuthToken);
  if (isLimited) {
    res.status(429).json({ error: "Demasiadas consultas de informe. Por favor, espera un minuto." });
    return;
  }

  const { extractos, query } = body || {};

  if (!extractos || !Array.isArray(extractos)) {
    res.status(400).json({ error: "Se requiere la lista de extractos para sintetizar." });
    return;
  }

  // Medidas de seguridad y límites de payload
  if (extractos.length > 100) {
    res.status(400).json({ error: "La cantidad de extractos a sintetizar excede el límite permitido (100)." });
    return;
  }
  if (query && query.length > 200) {
    res.status(400).json({ error: "La consulta del informe excede los 200 caracteres." });
    return;
  }

  // Filtrar solo las normas que aplican al tema
  const normasAplicables = extractos.filter(e => e.aplica === true);

  if (normasAplicables.length === 0) {
    res.status(200).json({ 
      informe: `# Informe Temático: ${query}\n\nNo se encontraron normas vigentes o aplicables que traten específicamente sobre este tema en el Digesto.`
    });
    await registrarTelemetria('informe', query, false, Date.now() - startTime, 0, 0);
    return;
  }

  // Helper para empaquetar el vector
  const packVector = (arr) => {
    const buffer = new ArrayBuffer(arr.length * 4);
    const view = new DataView(buffer);
    arr.forEach((val, i) => { view.setFloat32(i * 4, val, true); });
    return Buffer.from(buffer).toString('base64');
  };

  const formatArgs = (args) => args.map(arg => {
    if (typeof arg === 'number') return { type: 'integer', value: arg.toString() };
    if (arg && typeof arg === 'object' && arg.type === 'blob') return arg;
    return { type: 'text', value: arg.toString() };
  });

  // Lógica de caché semántica
  let queryVectorBlob = null;
  let cachePipelineUrl = "";
  if (cacheUrl) {
    const cleanCacheUrl = cacheUrl.replace("libsql://", "https://").replace("http://", "https://");
    cachePipelineUrl = `${cleanCacheUrl}/v2/pipeline`;
  }

  async function tursoCacheQuery(sql, params = []) {
    if (!cachePipelineUrl) return [];
    const requestBody = {
      requests: [
        { type: "execute", stmt: { sql, args: formatArgs(params) } },
        { type: "close" }
      ]
    };
    try {
      const cacheResp = await fetch(cachePipelineUrl, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${cacheAuthToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody)
      });
      if (!cacheResp.ok) return [];
      const data = await cacheResp.json();
      const result = data.results[0];
      if (result.type === 'error') return [];

      const cols = result.response.result.cols.map(c => c.name);
      return result.response.result.rows.map(row => {
        const obj = {};
        cols.forEach((col, i) => { obj[col] = row[i] ? row[i].value : null; });
        return obj;
      });
    } catch (e) {
      console.error("Fallo al conectar a Turso Cache:", e);
      return [];
    }
  }

  // 1. Obtener embedding de OpenAI para la consulta del informe
  if (query && query.trim() && openAiApiKey) {
    try {
      queryVectorBlob = await getQueryEmbedding(query, openAiApiKey, cacheUrl, cacheAuthToken);
      
      if (queryVectorBlob) {
        // 2. Buscar en la caché semántica
        const cacheRows = await tursoCacheQuery(
          "SELECT response_text FROM semantic_cache WHERE query_text LIKE 'report:%' AND (1.0 - vector_distance_cos(embedding, ?)) > 0.81 LIMIT 1",
          [queryVectorBlob]
        );
        if (cacheRows.length > 0) {
          console.log(`[CACHE HIT] Sirviendo informe tematico cacheado para: "${query}"`);
          res.status(200).json({ 
            informe: cacheRows[0].response_text, 
            modelo: "Caché Semántica (Turso)" 
          });
          await registrarTelemetria('informe', query, true, Date.now() - startTime, 0, 0);
          return;
        }
      }
    } catch (err) {
      console.error("Error en cache semantica de informes:", err);
    }
  }

  // Formatear los extractos para el contexto del LLM
  const contextText = normasAplicables.map(n => 
    `- Norma ID: ${n.id} (Vigente: ${n.vigente ? "Sí" : "No"})
  * Aplicación/Beneficiario: ${n.beneficiario || "General"}
  * Requisitos y condiciones: ${n.condiciones || "Sin condiciones explícitas."}`
  ).join("\n");

  const promptSintesis = `Eres un consultor jurídico experto de la Municipalidad de Alta Gracia, Córdoba.
Tu tarea es redactar un INFORME TEMÁTICO EJECUTIVO en formato Markdown sobre el tema: "${query}".

Basándote únicamente en la lista de normas analizadas que se presenta a continuación, estructurá un reporte profesional para el Intendente y el Concejo Deliberante:

${contextText}

ESTRUCTURA OBLIGATORIA DEL INFORME (Usa esta jerarquía Markdown):
# Informe Temático: ${query}

## 1. Resumen Ejecutivo
(Síntesis global de los hallazgos. Máximo 150 palabras, analizando tendencias y concentración de las normas).

## 2. Detalle de Normativas Aplicables
(Enumera y clasifica las normas de forma organizada. Destaca el número de ordenanza, quiénes son los beneficiarios o a quiénes aplica, y las condiciones de acceso. Usa viñetas estructuradas y negritas).

## 3. Conclusiones y Estado de Vigencia
(Analiza el balance general de las normas, cuántas siguen vigentes y recomendaciones legales rápidas).

REGLAS DE ESTILO Y DEEP LINKS:
- Mantén un tono formal y técnico pero de lectura ágil.
- Destaca con negritas los números de Ordenanza (ej. **Ordenanza N° 1234**) y beneficiarios clave.
- OBLIGATORIO: Cada vez que listes o menciones una norma en el reporte, debes incluir un enlace directo (Deep Link) en formato Markdown que apunte al fragmento exacto del texto del que obtuviste el dato utilizando la sintaxis de fragmento de texto (Scroll-to-text).
  * Formato: [Nombre de la Norma](https://digestoaltagracia.com.ar/#/detalles/{Norma_ID}:~:text={TEXT_FRAGMENT})
  * El {Norma_ID} lo obtienes de "Norma ID" en el contexto.
  * El {TEXT_FRAGMENT} debe ser una frase literal y corta (3-5 palabras) extraída de las condiciones o características de esa norma (ej: "eximicion%20del%20pago" o "tasa%20de%20servicios"). Codifica los espacios como %20.
  * Ejemplo: [Ordenanza N° 7939](https://digestoaltagracia.com.ar/#/detalles/7939:~:text=tasa%20tarifaria%20anual)
- Ve directo al grano sin introducciones del tipo "Aquí tienes tu informe...".`;

  let informeSintesis = '';
  let activeModel = 'DeepSeek (Principal)';
  const isDsTripped = Date.now() < dsTrippedUntil;

  try {
    if (isDsTripped) throw new Error();
    const dsResp = await fetch("https://api.deepseek.com/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${deepseekKey}` },
      body: JSON.stringify({
        model: "deepseek-chat",
        messages: [{ role: "user", content: promptSintesis }],
        temperature: 0.3,
        max_tokens: 3000
      })
    });
    if (dsResp.ok) {
      const data = await dsResp.json();
      informeSintesis = data.choices[0].message.content;
      dsFailures = 0;
    } else {
      throw new Error();
    }
  } catch {
    if (!isDsTripped) {
      dsFailures++;
      if (dsFailures >= 3) dsTrippedUntil = Date.now() + 5 * 60 * 1000;
    }
    activeModel = 'Groq (Respaldo)';
    const groqResp = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${groqKey}` },
      body: JSON.stringify({
            model: "llama-3.1-8b-instant",
            messages: [{ role: "user", content: promptSintesis }],
            temperature: 0.3,
            max_tokens: 3000
      })
    });
    if (!groqResp.ok) throw new Error("Ambas IAs fallaron al sintetizar el informe.");
    const data = await groqResp.json();
    informeSintesis = data.choices[0].message.content;
  }

  // Guardar en la caché semántica
  if (queryVectorBlob && informeSintesis) {
    try {
      await tursoCacheQuery(
        "INSERT OR IGNORE INTO semantic_cache (query_text, embedding, response_text) VALUES (?, ?, ?)",
        [`report:${query.trim()}`, queryVectorBlob, informeSintesis]
      );
      console.log(`[CACHE WRITE] Informe sintetizado guardado en cache semantica para: "${query}"`);
    } catch (cacheWriteErr) {
      console.error("Error al guardar informe en cache semantica:", cacheWriteErr);
    }
  }

  res.status(200).json({ informe: informeSintesis, modelo: activeModel });
  await registrarTelemetria('informe', query, false, Date.now() - startTime, 0, 0);
}
