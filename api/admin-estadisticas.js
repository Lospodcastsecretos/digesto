import { verifyAdminAuth } from './_lib/adminAuth.js';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Credentials', true);
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }
  
  if (req.method !== 'GET') {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  if (!verifyAdminAuth(req)) {
    res.status(401).json({ error: "No autorizado. Token inválido." });
    return;
  }

  const tursoUrl = (process.env.TURSO_URL || "").replace("libsql://", "https://") + "/v2/pipeline";
  const tursoToken = process.env.TURSO_TOKEN;

  async function query(sql) {
    const response = await fetch(tursoUrl, {
      method: "POST",
      headers: { "Authorization": `Bearer ${tursoToken}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        requests: [
          { type: "execute", stmt: { sql } },
          { type: "close" }
        ]
      })
    });
    
    if (!response.ok) return [];
    
    const data = await response.json();
    const result = data.results[0];
    if (result.type === 'error') return [];
    
    const cols = result.response.result.cols.map(c => c.name);
    return result.response.result.rows.map(row => {
      const obj = {};
      cols.forEach((col, i) => { obj[col] = row[i] ? row[i].value : null; });
      return obj;
    });
  }

  try {
    // Estadísticas generales
    const totalConsultasRow = await query("SELECT COUNT(*) as total FROM consultas_log");
    const totalConsultas = totalConsultasRow[0]?.total || 0;

    const cacheHitsRow = await query("SELECT COUNT(*) as hits FROM consultas_log WHERE cache_hit = 1");
    const cacheHits = cacheHitsRow[0]?.hits || 0;

    // Ahorro (asumimos ~$0.00005 por token o promedio fijo) - Simplificado
    const cacheHitRate = totalConsultas > 0 ? ((cacheHits / totalConsultas) * 100).toFixed(1) : 0;

    // Últimas 20 consultas (actividad reciente)
    const ultimasConsultas = await query("SELECT * FROM consultas_log ORDER BY timestamp DESC LIMIT 20");

    // Top 5 temas más buscados en Chat (agrupamiento simple por palabras clave)
    // Para SQLite, usamos LOWER y agrupamos por el contenido (idealmente se normaliza)
    const topTemas = await query(`
      SELECT LOWER(query_text) as tema, COUNT(*) as cantidad 
      FROM consultas_log 
      WHERE tipo_consulta = 'chat' 
      GROUP BY LOWER(query_text) 
      ORDER BY cantidad DESC 
      LIMIT 10
    `);

    // Consultas por tipo
    const porTipo = await query("SELECT tipo_consulta, COUNT(*) as cantidad FROM consultas_log GROUP BY tipo_consulta");

    // Últimas entradas de Caché Semántico (limitado a 50)
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
      cacheEntries
    });
  } catch (err) {
    console.error("Error en admin-estadisticas:", err);
    res.status(500).json({ error: "Error obteniendo estadísticas" });
  }
}
