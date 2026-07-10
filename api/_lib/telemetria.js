export async function registrarTelemetria(tipoConsulta, queryText, cacheHit, duracionMs, tokensPrompt = 0, tokensRespuesta = 0) {
  const tursoUrl = (process.env.TURSO_URL || "").replace("libsql://", "https://") + "/v2/pipeline";
  const tursoToken = process.env.TURSO_TOKEN;

  if (!tursoUrl || !tursoToken) {
    console.error("[Telemetria] Falta TURSO_URL o TURSO_TOKEN");
    return;
  }

  // Prevenir que queries muy largos o vacíos rompan el log
  const safeQuery = typeof queryText === 'string' ? queryText.substring(0, 1000) : "";

  const sql = `
    INSERT INTO consultas_log (tipo_consulta, query_text, cache_hit, duracion_ms, tokens_prompt, tokens_respuesta)
    VALUES (?, ?, ?, ?, ?, ?)
  `;
  
  const args = [
    { type: "text", value: tipoConsulta },
    { type: "text", value: safeQuery },
    { type: "integer", value: cacheHit ? 1 : 0 },
    { type: "integer", value: duracionMs },
    { type: "integer", value: tokensPrompt },
    { type: "integer", value: tokensRespuesta }
  ];

  try {
    const response = await fetch(tursoUrl, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${tursoToken}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        requests: [
          { type: "execute", stmt: { sql, args } },
          { type: "close" }
        ]
      })
    });
    
    if (!response.ok) {
      console.error("[Telemetria] Error al registrar:", await response.text());
    }
  } catch (error) {
    console.error("[Telemetria] Excepción al registrar:", error);
  }
}
