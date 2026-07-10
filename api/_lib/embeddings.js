export function packVector(arr) {
  const buffer = new ArrayBuffer(arr.length * 4);
  const view = new DataView(buffer);
  arr.forEach((val, i) => {
    view.setFloat32(i * 4, val, true);
  });
  return Buffer.from(buffer).toString('base64');
}

export async function getQueryEmbedding(queryText, openAiApiKey, cacheUrl, cacheAuthToken) {
  if (!queryText || !queryText.trim()) return null;
  
  // Normalizar la query para que ignore puntuación, múltiples espacios y mayúsculas
  const normQuery = queryText
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "") // quitar acentos
    .replace(/[^a-z0-9]/g, " ")     // reemplazar puntuación por espacio
    .replace(/\s+/g, " ")            // unificar espacios
    .trim();

  if (!normQuery) return null;

  const cleanUrl = cacheUrl.replace("libsql://", "https://").replace("http://", "https://");
  const pipelineUrl = `${cleanUrl}/v2/pipeline`;

  // 1. Intentar leer de la caché en Turso
  try {
    const payloadLookup = {
      requests: [
        {
          type: "execute",
          stmt: {
            sql: "SELECT embedding FROM embeddings_cache WHERE query_text = ?",
            args: [{ type: "text", value: normQuery }]
          }
        },
        { type: "close" }
      ]
    };
    const lookupResp = await fetch(pipelineUrl, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${cacheAuthToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(payloadLookup)
    });
    if (lookupResp.ok) {
      const data = await lookupResp.json();
      const result = data.results[0];
      if (result.type === "ok" && result.response.result.rows.length > 0) {
        const base64Blob = result.response.result.rows[0][0].value;
        if (base64Blob) {
          console.log(`[EMBEDDING CACHE HIT] "${normQuery}"`);
          return { type: 'blob', base64: base64Blob };
        }
      }
    }
  } catch (err) {
    console.error("Error al buscar embedding en cache:", err);
  }

  // 2. Si no está en caché, llamar a OpenAI
  console.log(`[EMBEDDING CACHE MISS] Generando vector para: "${normQuery}"`);
  const openAiResp = await fetch("https://api.openai.com/v1/embeddings", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${openAiApiKey}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      input: queryText.trim(),
      model: "text-embedding-3-small"
    })
  });

  if (!openAiResp.ok) {
    throw new Error(`OpenAI Embeddings error: ${openAiResp.status} ${await openAiResp.text()}`);
  }

  const openAiData = await openAiResp.json();
  const vector = openAiData.data[0].embedding;
  const base64Vector = packVector(vector);

  // 3. Guardar en la caché de Turso
  try {
    const payloadWrite = {
      requests: [
        {
          type: "execute",
          stmt: {
            sql: "INSERT OR IGNORE INTO embeddings_cache (query_text, embedding) VALUES (?, ?)",
            args: [
              { type: "text", value: normQuery },
              { type: "blob", base64: base64Vector }
            ]
          }
        },
        { type: "close" }
      ]
    };
    await fetch(pipelineUrl, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${cacheAuthToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(payloadWrite)
    });
  } catch (err) {
    console.error("Error al guardar embedding en cache:", err);
  }

  return { type: 'blob', base64: base64Vector };
}
