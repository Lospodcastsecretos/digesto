import { verifyAdminAuth } from './_lib/adminAuth.js';
import crypto from 'crypto';

export default async function handler(req, res) {
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

    // 5. REVISOR DE RELACIONES
    if (action === 'relaciones-pendientes') {
      if (req.method !== 'GET') return res.status(405).json({ error: "Method not allowed" });
      const limit = parseInt(req.query.limit) || 15;
      const rows = await query(`
        SELECT
          r.id,
          r.norma_origen_id,
          r.tipo_relacion,
          r.articulo_afectado,
          r.confianza,
          r.fragmento_original,
          r.justificacion,
          r.destino_numero_texto,
          r.destino_tipo_texto,
          o.numero as origen_numero,
          o.fecha as origen_fecha,
          o.tipo_nombre as origen_tipo,
          o.archivo_pdf as origen_pdf,
          COALESCE(d.numero, r.destino_numero_texto) as destino_numero,
          d.fecha as destino_fecha,
          COALESCE(d.tipo_nombre, r.destino_tipo_texto) as destino_tipo,
          d.archivo_pdf as destino_pdf
        FROM normas_relaciones r
        JOIN normas o ON r.norma_origen_id = o.id
        LEFT JOIN normas d ON r.norma_destino_id = d.id
        WHERE r.revisado_humano = 0 OR r.revisado_humano IS NULL
        ORDER BY r.confianza DESC
        LIMIT ?
      `, [limit]);
      res.status(200).json(rows);
      return;
    }

    if (action === 'relaciones-confirmar') {
      if (req.method !== 'POST') return res.status(405).json({ error: "Method not allowed" });
      const { id, tipo_relacion, articulo_afectado, destino_numero_texto, destino_tipo_texto } = body || {};
      if (!id) return res.status(400).json({ error: "Falta el parámetro id" });
      
      // Intentar re-resolver la norma destino si es que fue editada
      let dest_id = null;
      if (destino_numero_texto && destino_tipo_texto) {
        const resolvedDest = await query(
          "SELECT id FROM normas WHERE numero = ? AND tipo_nombre = ? LIMIT 1",
          [destino_numero_texto.toString().trim(), destino_tipo_texto.toString().trim()]
        );
        if (resolvedDest && resolvedDest.length > 0) {
          dest_id = resolvedDest[0].id;
        }
      }

      await query(
        `UPDATE normas_relaciones 
         SET tipo_relacion = ?, articulo_afectado = ?, destino_numero_texto = ?, destino_tipo_texto = ?, norma_destino_id = ?, revisado_humano = 1
         WHERE id = ?`,
        [
          tipo_relacion || '',
          articulo_afectado === undefined ? null : articulo_afectado,
          destino_numero_texto || '',
          destino_tipo_texto || '',
          dest_id,
          id
        ]
      );
      res.status(200).json({ success: true, resolvedDestId: dest_id });
      return;
    }

    if (action === 'relaciones-rechazar') {
      if (req.method !== 'POST') return res.status(405).json({ error: "Method not allowed" });
      const { id } = body || {};
      if (!id) return res.status(400).json({ error: "Falta el parámetro id" });
      await query("UPDATE normas_relaciones SET revisado_humano = -1 WHERE id = ?", [id]);
      res.status(200).json({ success: true });
      return;
    }

    if (action === 'norma-texto') {
      if (req.method !== 'GET') return res.status(405).json({ error: "Method not allowed" });
      const { id } = req.query;
      if (!id) return res.status(400).json({ error: "Falta el parámetro id" });
      const rows = await query("SELECT texto_completo FROM normas WHERE id = ?", [parseInt(id)]);
      res.status(200).json({ texto: rows[0]?.texto_completo || 'No se encontró el texto completo de esta norma.' });
      return;
    }

    // 6. EXPLORADOR DE DOCUMENTOS
    if (action === 'normas-metadata') {
      if (req.method !== 'GET') return res.status(405).json({ error: "Method not allowed" });
      const categorias = await query("SELECT DISTINCT categoria_nombre FROM normas WHERE categoria_nombre IS NOT NULL ORDER BY categoria_nombre");
      const tipos = await query("SELECT DISTINCT tipo_nombre FROM normas WHERE tipo_nombre IS NOT NULL ORDER BY tipo_nombre");
      res.status(200).json({ 
        categorias: categorias.map(c => c.categoria_nombre), 
        tipos: tipos.map(t => t.tipo_nombre) 
      });
      return;
    }

    if (action === 'normas-list') {
      if (req.method !== 'GET') return res.status(405).json({ error: "Method not allowed" });
      const page = parseInt(req.query.page) || 1;
      const pageSize = parseInt(req.query.pageSize) || 50;
      const offset = (page - 1) * pageSize;
      const { categoria, tipo, q } = req.query;

      let sql = "SELECT id, titulo, tipo_nombre, categoria_nombre FROM normas WHERE 1=1";
      const args = [];

      if (categoria) {
        sql += " AND categoria_nombre = ?";
        args.push(categoria);
      }
      if (tipo) {
        sql += " AND tipo_nombre = ?";
        args.push(tipo);
      }
      if (q) {
        sql += " AND titulo LIKE ?";
        args.push(`%${q}%`);
      }

      sql += " ORDER BY id DESC LIMIT ? OFFSET ?";
      args.push(pageSize, offset);

      const rows = await query(sql, args);
      
      // Get total count for pagination
      let countSql = "SELECT COUNT(*) as total FROM normas WHERE 1=1";
      const countArgs = [];
      if (categoria) { countSql += " AND categoria_nombre = ?"; countArgs.push(categoria); }
      if (tipo) { countSql += " AND tipo_nombre = ?"; countArgs.push(tipo); }
      if (q) { countSql += " AND titulo LIKE ?"; countArgs.push(`%${q}%`); }
      const countResult = await query(countSql, countArgs);
      const total = countResult[0]?.total || 0;

      res.status(200).json({ normas: rows, total, page, pageSize });
      return;
    }

    if (action === 'norma-detail') {
      if (req.method !== 'GET') return res.status(405).json({ error: "Method not allowed" });
      const { id } = req.query;
      if (!id) return res.status(400).json({ error: "Falta el parámetro id" });

      const rows = await query("SELECT id, numero, titulo, tipo_nombre, categoria_nombre, resumen, texto_completo, resumen_ia, resumen_ia_hash FROM normas WHERE id = ?", [parseInt(id)]);
      if (rows.length === 0) return res.status(404).json({ error: "Norma no encontrada." });

      const norma = rows[0];
      const textToSummarize = norma.texto_completo || norma.resumen || norma.titulo || "Sin texto disponible.";
      const computed_hash = crypto.createHash('md5').update(textToSummarize).digest('hex');

      res.status(200).json({ ...norma, computed_hash });
      return;
    }

    res.status(400).json({ error: "Acción no reconocida." });

  } catch (err) {
    console.error("Error en admin controller:", err);
    res.status(500).json({ error: "Error interno del servidor procesando la acción." });
  }
}
