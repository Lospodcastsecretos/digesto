import { verifyAdminAuth } from './_lib/adminAuth.js';
import crypto from 'crypto';

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

    // Hash en SHA-256 para igualar longitudes y comparar de forma segura (Timing-Safe)
    const inputHash = crypto.createHash('sha256').update(password || '').digest();
    const targetHash = crypto.createHash('sha256').update(adminPassword).digest();

    let isMatch = false;
    try {
      isMatch = crypto.timingSafeEqual(inputHash, targetHash);
    } catch (e) {
      isMatch = false;
    }

    if (isMatch) {
      res.status(200).json({ success: true, token: adminPassword });
    } else {
      // Retraso artificial de 1.2 segundos para mitigar ataques de fuerza bruta
      await new Promise(resolve => setTimeout(resolve, 1200));
      res.status(401).json({ success: false, error: "Contraseña incorrecta." });
    }
    return;
  }

  // RUTAS PROTEGIDAS (Requieren autenticación)
  if (!verifyAdminAuth(req)) {
    res.status(401).json({ error: "No autorizado. Token inválido o expirado." });
    return;
  }

  const mainTursoUrl = (process.env.TURSO_URL || "").replace("libsql://", "https://").replace("http://", "https://") + "/v2/pipeline";
  const mainTursoToken = process.env.TURSO_TOKEN;

  const cacheTursoUrl = (process.env.TURSO_CACHE_URL || process.env.TURSO_URL || "").replace("libsql://", "https://").replace("http://", "https://") + "/v2/pipeline";
  const cacheTursoToken = process.env.TURSO_CACHE_TOKEN || process.env.TURSO_TOKEN;

  async function query(sql, args = [], target = 'main') {
    const url = target === 'cache' ? cacheTursoUrl : mainTursoUrl;
    const token = target === 'cache' ? cacheTursoToken : mainTursoToken;

    const formattedArgs = args.map(arg => {
      if (typeof arg === 'number') return { type: 'integer', value: arg.toString() };
      return { type: 'text', value: arg.toString() };
    });

    const response = await fetch(url, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
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

  async function multiQuery(stmts, target = 'main') {
    const url = target === 'cache' ? cacheTursoUrl : mainTursoUrl;
    const token = target === 'cache' ? cacheTursoToken : mainTursoToken;

    const requests = stmts.map(stmt => ({
      type: "execute",
      stmt: { 
        sql: stmt.sql, 
        args: (stmt.args || []).map(arg => {
          if (typeof arg === 'number') return { type: 'integer', value: arg.toString() };
          return { type: 'text', value: arg.toString() };
        })
      }
    }));
    requests.push({ type: "close" });

    const response = await fetch(url, {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ requests })
    });
    
    if (!response.ok) throw new Error(`Turso error: ${response.status}`);
    
    const data = await response.json();
    
    return data.results.slice(0, stmts.length).map(result => {
      if (result.type === 'error') throw new Error(result.error.message);
      const cols = result.response.result.cols.map(c => c.name);
      return result.response.result.rows.map(row => {
        const obj = {};
        cols.forEach((col, i) => { obj[col] = row[i] ? row[i].value : null; });
        return obj;
      });
    });
  }

  try {
    // 1. OBTENER ESTADÍSTICAS (Rápido)
    if (action === 'stats') {
      if (req.method !== 'GET') return res.status(405).json({ error: "Method not allowed" });
      
      const mainStmts = [
        { sql: "SELECT COUNT(*) as total FROM consultas_log" },
        { sql: "SELECT COUNT(*) as hits FROM consultas_log WHERE cache_hit = 1" },
        { sql: "SELECT * FROM consultas_log ORDER BY timestamp DESC LIMIT 20" },
        { sql: `
          SELECT LOWER(query_text) as tema, COUNT(*) as cantidad 
          FROM consultas_log 
          WHERE tipo_consulta = 'chat' 
          GROUP BY LOWER(query_text) 
          ORDER BY cantidad DESC 
          LIMIT 10
        ` },
        { sql: "SELECT tipo_consulta, COUNT(*) as cantidad FROM consultas_log GROUP BY tipo_consulta" }
      ];

      // Ejecutar consultas de la base principal y la de cache en paralelo
      const [mainResults, cacheEntries] = await Promise.all([
        multiQuery(mainStmts, 'main'),
        query("SELECT rowid, query_text, response_text FROM semantic_cache LIMIT 50", [], 'cache').catch(e => {
          console.warn("La tabla semantic_cache no pudo ser consultada:", e);
          return [];
        })
      ]);

      const totalConsultas = mainResults[0][0]?.total || 0;
      const cacheHits = mainResults[1][0]?.hits || 0;
      const cacheHitRate = totalConsultas > 0 ? ((cacheHits / totalConsultas) * 100).toFixed(1) : 0;
      const ultimasConsultas = mainResults[2] || [];
      const topTemas = mainResults[3] || [];
      const porTipo = mainResults[4] || [];

      res.status(200).json({
        totalConsultas,
        cacheHits,
        cacheMisses: totalConsultas - cacheHits,
        cacheHitRate,
        actividadReciente: ultimasConsultas,
        topTemas,
        porTipo,
        cacheEntries
      });
      return;
    }

    // 1b. DIAGNÓSTICO DEL DIGESTO (Consulta pesada optimizada)
    if (action === 'diagnose') {
      if (req.method !== 'GET') return res.status(405).json({ error: "Method not allowed" });
      
      const rows = await query(`
        SELECT 
          COUNT(*) as total, 
          SUM(CASE WHEN archivo_pdf IS NULL OR archivo_pdf = '' OR archivo_pdf = 'sin_archivo_fisico' THEN 1 ELSE 0 END) as sin_pdf, 
          SUM(CASE WHEN resumen IS NULL OR resumen = '' THEN 1 ELSE 0 END) as sin_resumen 
        FROM normas
      `);
      
      const dbStats = rows[0] || { total: 0, sin_pdf: 0, sin_resumen: 0 };
      res.status(200).json({ dbStats });
      return;
    }

    // 2. ELIMINAR REGISTRO INDIVIDUAL DE CACHÉ
    if (action === 'cache-delete') {
      if (req.method !== 'POST') return res.status(405).json({ error: "Method not allowed" });
      const { rowid } = body || {};
      if (!rowid) return res.status(400).json({ error: "Falta el parámetro rowid." });

      await query("DELETE FROM semantic_cache WHERE rowid = ?", [rowid], 'cache');
      res.status(200).json({ success: true, message: "Registro eliminado exitosamente." });
      return;
    }

    // 3. VACIAR CACHÉ SEMÁNTICO
    if (action === 'cache-clear') {
      if (req.method !== 'POST') return res.status(405).json({ error: "Method not allowed" });

      await query("DELETE FROM semantic_cache", [], 'cache');
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
