export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') { res.status(200).end(); return; }
  if (req.method !== 'GET') { res.status(405).json({ error: 'Método no permitido.' }); return; }

  const url = process.env.TURSO_URL;
  const authToken = process.env.TURSO_TOKEN;

  if (!url || !authToken) {
    res.status(500).json({ error: 'Faltan variables de entorno.' });
    return;
  }

  const normaId = parseInt(req.query.normaId);
  if (!normaId || isNaN(normaId)) {
    res.status(400).json({ error: 'Se requiere el parámetro normaId.' });
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
  }

  try {
    // 1. Traer la norma base
    const normaRows = await tursoQuery(
      'SELECT id, numero, tipo_nombre, fecha, texto_completo, texto_consolidado, texto_consolidado_generado_en, vigente FROM normas WHERE id = ?',
      [normaId]
    );

    if (!normaRows.length) {
      return res.status(404).json({ error: 'Norma no encontrada.' });
    }

    const norma = normaRows[0];

    // 2. Verificar si hay cache válido
    if (norma.texto_consolidado && norma.texto_consolidado_generado_en) {
      return res.status(200).json({
        normaId,
        estado: 'consolidado',
        desde_cache: true,
        texto_consolidado: norma.texto_consolidado,
        generado_en: norma.texto_consolidado_generado_en,
        modificaciones: []
      });
    }

    if (!norma.texto_completo) {
      return res.status(200).json({
        normaId,
        estado: 'sin_texto',
        mensaje: 'Esta norma no tiene texto completo disponible para consolidar.'
      });
    }

    // 3. Traer relaciones confirmadas (revisado_humano = 1) que afectan a esta norma
    const relaciones = await tursoQuery(`
      SELECT 
        r.id, r.tipo_relacion, r.articulo_afectado, r.texto_nuevo, r.confianza,
        n_orig.id as origen_id, n_orig.numero as origen_numero, 
        n_orig.tipo_nombre as origen_tipo, n_orig.fecha as origen_fecha
      FROM normas_relaciones r
      JOIN normas n_orig ON r.norma_origen_id = n_orig.id
      WHERE r.norma_destino_id = ? AND r.revisado_humano = 1
      ORDER BY n_orig.fecha ASC, r.id ASC
    `, [normaId]);

    // 4. Si no hay relaciones confirmadas, devolver texto original como referencia
    if (!relaciones.length) {
      return res.status(200).json({
        normaId,
        estado: 'sin_modificaciones_confirmadas',
        mensaje: 'No hay modificaciones confirmadas para esta norma.',
        texto_base: norma.texto_completo
      });
    }

    // 5. Verificar derogación total (tipo=deroga sin articulo_afectado)
    const derogacionTotal = relaciones.find(
      r => r.tipo_relacion === 'deroga' && !r.articulo_afectado
    );
    if (derogacionTotal) {
      return res.status(200).json({
        normaId,
        estado: 'derogada',
        derogado_por: {
          id: derogacionTotal.origen_id,
          numero: derogacionTotal.origen_numero,
          tipo: derogacionTotal.origen_tipo,
          fecha: derogacionTotal.origen_fecha
        }
      });
    }

    // 6. Aplicar modificaciones de artículos sobre texto base
    let textoConsolidado = norma.texto_completo;
    const modificacionesAplicadas = [];
    const modificacionesFallidas = [];

    for (const rel of relaciones) {
      if (rel.tipo_relacion !== 'modifica') continue;
      if (!rel.articulo_afectado || !rel.texto_nuevo) {
        modificacionesAplicadas.push({
          articulo: rel.articulo_afectado || '(total)',
          norma_origen: { id: rel.origen_id, numero: rel.origen_numero, tipo: rel.origen_tipo, fecha: rel.origen_fecha },
          aplicado: false,
          motivo: 'Sin texto de reemplazo disponible'
        });
        continue;
      }

      // Intentar matching flexible del encabezado del artículo
      const articuloBase = rel.articulo_afectado
        .replace(/\./g, '\\.?')
        .replace(/°/g, '[°º]?')
        .replace(/\s+/g, '\\s+');

      // Patrón: desde el artículo hasta el próximo artículo o fin del texto
      const patronArticulo = new RegExp(
        `(${articuloBase}[^:]*:?[\\s\\S]*?)(?=\\n\\s*(?:Art[íi]culo|Art\\.|ARTICULO)\\s+\\d|$)`,
        'i'
      );

      if (patronArticulo.test(textoConsolidado)) {
        textoConsolidado = textoConsolidado.replace(patronArticulo, rel.texto_nuevo);
        modificacionesAplicadas.push({
          articulo: rel.articulo_afectado,
          norma_origen: { id: rel.origen_id, numero: rel.origen_numero, tipo: rel.origen_tipo, fecha: rel.origen_fecha },
          aplicado: true
        });
      } else {
        modificacionesFallidas.push({
          articulo: rel.articulo_afectado,
          norma_origen: { id: rel.origen_id, numero: rel.origen_numero, tipo: rel.origen_tipo, fecha: rel.origen_fecha },
          aplicado: false,
          motivo: 'No se encontró el artículo en el texto'
        });
      }
    }

    // Agregar relaciones de otros tipos (complementa, reglamenta) como anotaciones
    for (const rel of relaciones) {
      if (rel.tipo_relacion === 'modifica') continue;
      modificacionesAplicadas.push({
        articulo: rel.articulo_afectado || '(norma completa)',
        tipo: rel.tipo_relacion,
        norma_origen: { id: rel.origen_id, numero: rel.origen_numero, tipo: rel.origen_tipo, fecha: rel.origen_fecha },
        aplicado: false,
        motivo: `Relación de tipo '${rel.tipo_relacion}' — solo informativa`
      });
    }

    // 7. Guardar en caché si se aplicaron modificaciones
    const ahora = new Date().toISOString();
    if (modificacionesAplicadas.some(m => m.aplicado)) {
      await tursoExecute(
        'UPDATE normas SET texto_consolidado = ?, texto_consolidado_generado_en = ? WHERE id = ?',
        [textoConsolidado, ahora, normaId]
      );
    }

    return res.status(200).json({
      normaId,
      estado: 'consolidado',
      desde_cache: false,
      texto_consolidado: textoConsolidado,
      generado_en: ahora,
      modificaciones: modificacionesAplicadas,
      modificaciones_fallidas: modificacionesFallidas
    });

  } catch (err) {
    console.error('Error en consolidar:', err);
    res.status(500).json({ error: err.message });
  }
}
