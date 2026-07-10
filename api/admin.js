import { verifyAdminAuth } from './_lib/adminAuth.js';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }

  let body = req.body;
  if (typeof body === 'string') {
    try { body = JSON.parse(body); } catch(e) {}
  }

  // Obtener la acción desde query o body
  const action = req.query.action || (body && body.action);

  if (!action) {
    res.status(400).json({ error: "Falta el parámetro 'action'." });
    return;
  }

  // --- RUTA PÚBLICA DE LOGIN ---
  if (action === 'login') {
    if (req.method !== 'POST') {
      res.status(405).json({ error: "Method not allowed" });
      return;
    }
    const { password } = body || {};
    const adminPassword = process.env.ADMIN_PASSWORD;

    if (!adminPassword) {
      res.status(500).json({ error: "Panel de administración no configurado en el servidor." });
      return;
    }

    if (password === adminPassword) {
      res.status(200).json({ success: true, token: adminPassword });
    } else {
      res.status(401).json({ success: false, error: "Contraseña incorrecta." });
    }
    return;
  }

  // --- RUTAS PROTEGIDAS (Requieren autenticación) ---
  if (!verifyAdminAuth(req)) {
    res.status(401).json({ error: "No autorizado. Token inválido o expirado." });
    return;
  }

  const tursoUrl = (process.env.TURSO_CACHE_URL || process.env.TURSO_URL || "").replace("libsql://", "https://") + "/v2/pipeline";
  const tursoToken = process.env.TURSO_CACHE_TOKEN || process.env.TURSO_TOKEN;

  async function query(sql, args = []) {
    const formattedArgs = args.map(arg => {
      if (typeof arg === 'number') return { type: 'integer', value: arg.toString() };
      return { type: 'text', value: arg.toString() };
    });

    const response = await fetch(tursoUrl, {
      method: "POST",
      headers: { "Authorization": `Bearer ${tursoToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        requests: [
          { type: "execute", stmt: { sql, args: formattedArgs } },
          { type: "close" }
        ]
      })
    });
    
    if (!response.ok) return [];
    
    const data = await response.json();
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
    // 1. OBTENER ESTADÍSTICAS
    if (action === 'stats') {
      if (req.method !== 'GET') return res.status(405).json({ error: "Method not allowed" });
      
      const totalConsultasRow = await query("SELECT COUNT(*) as total FROM consultas_log");
      const totalConsultas = totalConsultasRow[0]?.total || 0;

      const cacheHitsRow = await query("SELECT COUNT(*) as hits FROM consultas_log WHERE cache_hit = 1");
      const cacheHits = cacheHitsRow[0]?.hits || 0;

      const cacheHitRate = totalConsultas > 0 ? ((cacheHits / totalConsultas) * 100).toFixed(1) : 0;

      const ultimasConsultas = await query("SELECT * FROM consultas_log ORDER BY timestamp DESC LIMIT 20");

      const topTemas = await query(`
        SELECT LOWER(query_text) as tema, COUNT(*) as cantidad 
        FROM consultas_log 
        WHERE tipo_consulta = 'chat' 
        GROUP BY LOWER(query_text) 
        ORDER BY cantidad DESC 
        LIMIT 10
      `);

      const porTipo = await query("SELECT tipo_consulta, COUNT(*) as cantidad FROM consultas_log GROUP BY tipo_consulta");

      const dbStatsRow = await query("SELECT COUNT(*) as total, SUM(CASE WHEN texto_completo IS NULL OR texto_completo = '' THEN 1 ELSE 0 END) as sin_pdf, SUM(CASE WHEN resumen IS NULL OR resumen = '' THEN 1 ELSE 0 END) as sin_resumen FROM normas");
      const dbStats = dbStatsRow[0] || { total: 0, sin_pdf: 0, sin_resumen: 0 };

      let cacheEntries = [];
      try {
        cacheEntries = await query("SELECT rowid, query_text, response_text FROM semantic_cache LIMIT 50");
      } catch (e) {
        console.warn("La tabla semantic_cache no pudo ser consultada o no existe:", e);
      }

      res.status(200).json({
        totalConsultas,
        cacheHits,
        cacheMisses: totalConsultas - cacheHits,
        cacheHitRate,
        actividadReciente: ultimasConsultas,
        topTemas,
        porTipo,
        cacheEntries,
        dbStats
      });
      return;
    }

    // 2. ELIMINAR REGISTRO INDIVIDUAL DE CACHÉ
    if (action === 'cache-delete') {
      if (req.method !== 'POST') return res.status(405).json({ error: "Method not allowed" });
      const { rowid } = body || {};
      if (!rowid) return res.status(400).json({ error: "Falta el parámetro rowid." });

      await query("DELETE FROM semantic_cache WHERE rowid = ?", [rowid]);
      res.status(200).json({ success: true, message: "Registro eliminado exitosamente." });
      return;
    }

    // 3. VACIAR CACHÉ SEMÁNTICO
    if (action === 'cache-clear') {
      if (req.method !== 'POST') return res.status(405).json({ error: "Method not allowed" });

      await query("DELETE FROM semantic_cache");
      res.status(200).json({ success: true, message: "Caché limpiado exitosamente." });
      return;
    }

    // 4. EXPORTAR CONSULTAS A CSV/EXCEL
    if (action === 'export-csv') {
      if (req.method !== 'GET') return res.status(405).json({ error: "Method not allowed" });

      const logs = await query("SELECT timestamp, tipo_consulta, query_text, cache_hit, duracion_ms FROM consultas_log ORDER BY timestamp DESC");
      
      let csvContent = "\uFEFF";
      csvContent += "Fecha y Hora (UTC),Tipo de Consulta,Pregunta del Usuario,Cache Hit (Ahorro),Latencia (Segundos)\n";
      
      logs.forEach(log => {
        const fecha = log.timestamp || "";
        const tipo = log.tipo_consulta === 'chat' ? 'Chatbot (Burocracio)' : 'Informe Temático';
        const pregunta = `"${(log.query_text || "").replace(/"/g, '""').replace(/\n/g, ' ')}"`;
        const hit = log.cache_hit === 1 ? 'Sí' : 'No';
        const latencia = log.duracion_ms ? (log.duracion_ms / 1000).toFixed(2) : "0.00";
        
        csvContent += `${fecha},${tipo},${pregunta},${hit},${latencia}\n`;
      });
      
      res.setHeader('Content-Type', 'text/csv; charset=utf-8');
      res.setHeader('Content-Disposition', 'attachment; filename=consultas_digesto.csv');
      res.status(200).send(csvContent);
      return;
    }

    res.status(400).json({ error: "Acción no reconocida." });

  } catch (err) {
    console.error("Error en admin controller:", err);
    res.status(500).json({ error: "Error interno del servidor procesando la acción." });
  }
}
