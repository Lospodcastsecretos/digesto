export async function isRateLimited(req, endpoint, limit = 10, windowSeconds = 60, cacheUrl, cacheAuthToken) {
  if (!cacheUrl || !cacheAuthToken) return false; // Si no hay BD de cache, no limitamos para evitar caídas

  // Obtener la IP del cliente (Vercel pasa la IP en x-forwarded-for)
  const ipRaw = req.headers['x-forwarded-for'] || req.headers['x-real-ip'] || req.socket.remoteAddress || 'unknown';
  // Quedarse con la primera IP de la lista en caso de proxies
  const ip = ipRaw.split(',')[0].trim();

  const now = Math.floor(Date.now() / 1000);
  const cutoff = now - windowSeconds;

  const cleanUrl = cacheUrl.replace("libsql://", "https://").replace("http://", "https://");
  const pipelineUrl = `${cleanUrl}/v2/pipeline`;

  try {
    const payload = {
      requests: [
        // 1. Limpiar registros antiguos de esta IP y endpoint para no acumular basura
        {
          type: "execute",
          stmt: {
            sql: "DELETE FROM rate_limits WHERE ip = ? AND endpoint = ? AND timestamp < ?",
            args: [
              { type: "text", value: ip },
              { type: "text", value: endpoint },
              { type: "integer", value: cutoff.toString() }
            ]
          }
        },
        // 2. Contar peticiones en la ventana de tiempo
        {
          type: "execute",
          stmt: {
            sql: "SELECT COUNT(*) as cnt FROM rate_limits WHERE ip = ? AND endpoint = ? AND timestamp >= ?",
            args: [
              { type: "text", value: ip },
              { type: "text", value: endpoint },
              { type: "integer", value: cutoff.toString() }
            ]
          }
        },
        { type: "close" }
      ]
    };

    const resp = await fetch(pipelineUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${cacheAuthToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (!resp.ok) {
      console.error("Error al consultar rate limit en Turso:", await resp.text());
      return false; // Fallback tolerante a fallos
    }

    const data = await resp.json();
    const countResult = data.results[1];
    
    if (countResult && countResult.type === "ok") {
      const cnt = parseInt(countResult.response.result.rows[0][0].value);
      if (cnt >= limit) {
        console.warn(`[RATE LIMIT EXCEEDED] IP: ${ip} | Endpoint: ${endpoint} | Peticiones: ${cnt}/${limit}`);
        return true;
      }
    }

    // 3. Registrar la petición actual
    const registerPayload = {
      requests: [
        {
          type: "execute",
          stmt: {
            sql: "INSERT OR IGNORE INTO rate_limits (ip, endpoint, timestamp) VALUES (?, ?, ?)",
            args: [
              { type: "text", value: ip },
              { type: "text", value: endpoint },
              { type: "integer", value: now.toString() }
            ]
          }
        },
        { type: "close" }
      ]
    };
    
    await fetch(pipelineUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${cacheAuthToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(registerPayload)
    });

    return false;
  } catch (err) {
    console.error("Excepción en rate limiter:", err);
    return false; // Fallback tolerante
  }
}
