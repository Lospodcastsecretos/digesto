import { verifyAdminAuth } from './_lib/adminAuth.js';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }

  if (!verifyAdminAuth(req)) {
    res.status(401).json({ error: 'No autorizado.' });
    return;
  }

  const url = process.env.TURSO_URL;
  const authToken = process.env.TURSO_TOKEN;

  if (!url || !authToken) {
    res.status(500).json({ error: 'Faltan variables de entorno TURSO_URL o TURSO_TOKEN.' });
    return;
  }

  const cleanUrl = url.replace('libsql://', 'https://').replace('http://', 'https://');
  const pipelineUrl = `${cleanUrl}/v2/pipeline`;

  const formatArgs = (args) => args.map(arg => {
    if (arg === null || arg === undefined) return { type: 'null', value: null };
    if (typeof arg === 'number') return { type: 'integer', value: arg.toString() };
    return { type: 'text', value: arg.toString() };
  });

  async function tursoQuery(sql, params = []) {
    const payload = {
      requests: [
        { type: 'execute', stmt: { sql, args: formatArgs(params) } },
        { type: 'close' }
      ]
    };
    const r = await fetch(pipelineUrl, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!r.ok) throw new Error(`Turso Error: ${await r.text()}`);
    const data = await r.json();
    const result = data.results[0];
    if (result.type === 'error') throw new Error(result.error.message);
    const resVal = result.response.result;
    const cols = resVal.cols.map(c => c.name);
    return resVal.rows.map(rVal => {
      const row = {};
      rVal.forEach((val, idx) => { row[cols[idx]] = val ? val.value : null; });
      return row;
    });
  }

  async function tursoExecute(sql, params = []) {
    const payload = {
      requests: [
        { type: 'execute', stmt: { sql, args: formatArgs(params) } },
        { type: 'close' }
      ]
    };
    const r = await fetch(pipelineUrl, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${authToken}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!r.ok) throw new Error(`Turso Error: ${await r.text()}`);
    const data = await r.json();
    const result = data.results[0];
    if (result.type === 'error') throw new Error(result.error.message);
    return result.response.result.affected_row_count;
  }

  try {
    // ─── GET: Listar relaciones ────────────────────────────────────────────────
    if (req.method === 'GET') {
      const estado = req.query.estado || 'pendiente';
      const page = parseInt(req.query.page || '1');
      const limit = 25;
      const offset = (page - 1) * limit;

      let revisado_humano_val;
      if (estado === 'pendiente') revisado_humano_val = 0;
      else if (estado === 'confirmado') revisado_humano_val = 1;
      else if (estado === 'rechazado') revisado_humano_val = -1;
      else {
        res.status(400).json({ error: "Estado inválido. Usar 'pendiente', 'confirmado' o 'rechazado'." });
        return;
      }

      const orderBy = estado === 'pendiente' ? 'r.confianza ASC' : 'r.creado_en DESC';

      const [relaciones, totales] = await Promise.all([
        tursoQuery(`
          SELECT 
            r.id, r.tipo_relacion, r.articulo_afectado, r.confianza, r.revisado_humano,
            r.destino_numero_texto, r.destino_tipo_texto, r.creado_en, r.justificacion,
            n_orig.numero as origen_numero, n_orig.tipo_nombre as origen_tipo, n_orig.fecha as origen_fecha, n_orig.archivo_pdf as origen_pdf,
            n_dest.numero as destino_numero, n_dest.tipo_nombre as destino_tipo, n_dest.fecha as destino_fecha,
            n_dest.id as destino_id
          FROM normas_relaciones r
          JOIN normas n_orig ON r.norma_origen_id = n_orig.id
          LEFT JOIN normas n_dest ON r.norma_destino_id = n_dest.id
          WHERE r.revisado_humano = ?
          ORDER BY ${orderBy}
          LIMIT ? OFFSET ?
        `, [revisado_humano_val, limit, offset]),
        tursoQuery(
          'SELECT COUNT(*) as total FROM normas_relaciones WHERE revisado_humano = ?',
          [revisado_humano_val]
        )
      ]);

      const total = parseInt(totales[0]?.total || 0);

      return res.status(200).json({
        relaciones,
        pagination: {
          page,
          limit,
          total,
          pages: Math.ceil(total / limit)
        }
      });
    }

    // ─── POST: Confirmar o rechazar una relación ───────────────────────────────
    if (req.method === 'POST') {
      let body = req.body;
      if (typeof body === 'string') {
        try { body = JSON.parse(body); } catch(e) {}
      }
      const { id, accion } = body || {};

      if (!id || !accion) {
        res.status(400).json({ error: "Se requiere 'id' y 'accion' (confirmar|rechazar)." });
        return;
      }

      if (!['confirmar', 'rechazar'].includes(accion)) {
        res.status(400).json({ error: "Acción inválida. Usar 'confirmar' o 'rechazar'." });
        return;
      }

      const nuevoValor = accion === 'confirmar' ? 1 : -1;
      await tursoExecute(
        'UPDATE normas_relaciones SET revisado_humano = ? WHERE id = ?',
        [nuevoValor, id]
      );

      // Si se confirma, invalidar el cache de texto consolidado de la norma destino
      if (accion === 'confirmar') {
        const rel = await tursoQuery(
          'SELECT norma_destino_id FROM normas_relaciones WHERE id = ?',
          [id]
        );
        if (rel.length > 0 && rel[0].norma_destino_id) {
          await tursoExecute(
            'UPDATE normas SET texto_consolidado = NULL, texto_consolidado_generado_en = NULL WHERE id = ?',
            [rel[0].norma_destino_id]
          );
        }
      }

      return res.status(200).json({ success: true, accion, id });
    }

    res.status(405).json({ error: 'Método no permitido.' });

  } catch (err) {
    console.error('Error en admin-relaciones:', err);
    res.status(500).json({ error: err.message });
  }
}
