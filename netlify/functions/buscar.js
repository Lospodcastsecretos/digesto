exports.handler = async function(event, context) {
  const headers = {
    'Access-Control-Allow-Credentials': 'true',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,OPTIONS,PATCH,DELETE,POST,PUT',
    'Access-Control-Allow-Headers': 'X-CSRF-Token, X-Requested-With, Accept, Accept-Version, Content-Length, Content-MD5, Content-Type, Date, X-Api-Version, Content-Type, Authorization'
  };

  if (event.httpMethod === 'OPTIONS') {
    return {
      statusCode: 200,
      headers,
      body: ''
    };
  }

  // Configuración de conexión de Turso
  const TURSO_URL = process.env.TURSO_URL || "https://digesto-lospodcastsecretos.aws-us-west-2.turso.io";
  const TURSO_TOKEN = process.env.TURSO_TOKEN || "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3ODMyODgxMjQsImlkIjoiMDE5ZjM0NDAtN2UwMS03OTljLWFlOTItODBiMDJmNmVhMjdlIiwia2lkIjoiZ0JFblIyNVR6dEEwaHVWWXljOS03cnRzYThUaGRnbmFEd1ZHSXJrR3FPYyIsInJpZCI6ImE1MGUwMDBmLTQ4ZTgtNDg1ZS04MmM0LTEzNGIxYTA4MmJhYSJ9.ev1b_OISV20t8e9brtO7O4oU9bGnrPYum1LTbBiVng-gaPC2YiUsHzFe-ok2aXmVePtRNYtAmKpb0ntWL6xSCA";

  // Capturar parámetros
  const params = event.queryStringParameters || {};
  const { query, tipo, categoria, anio, vigencia, page } = params;

  const itemsPerPage = 15;
  const currentPage = parseInt(page) || 1;
  const offset = (currentPage - 1) * itemsPerPage;

  // 1. Construir consulta SQL
  let sql = "SELECT * FROM normas WHERE 1=1";
  const sqlParams = [];

  if (query) {
    sql += " AND (lower(numero) LIKE ? OR lower(titulo) LIKE ? OR lower(resumen) LIKE ?)";
    const likeQ = `%${query.toLowerCase()}%`;
    sqlParams.push({"type": "text", "value": likeQ});
    sqlParams.push({"type": "text", "value": likeQ});
    sqlParams.push({"type": "text", "value": likeQ});
  }

  if (tipo && tipo !== 'todos') {
    sql += " AND tipo_nombre = ?";
    sqlParams.push({"type": "text", "value": tipo});
  }

  if (categoria && categoria !== 'todas') {
    sql += " AND categoria_nombre = ?";
    sqlParams.push({"type": "text", "value": categoria});
  }

  if (anio && anio !== 'todos') {
    sql += " AND fecha = ?";
    sqlParams.push({"type": "text", "value": `Año ${anio}`});
  }

  if (vigencia && vigencia !== 'todos') {
    const isVigente = vigencia === 'si' ? 1 : 0;
    sql += " AND vigente = ?";
    sqlParams.push({"type": "integer", "value": isVigente});
  }

  const countSql = sql.replace("SELECT *", "SELECT COUNT(*) as total");

  sql += " ORDER BY id DESC LIMIT ? OFFSET ?";
  const sqlParamsQuery = [...sqlParams];
  sqlParamsQuery.push({"type": "integer", "value": itemsPerPage});
  sqlParamsQuery.push({"type": "integer", "value": offset});

  // 2. Ejecutar la llamada REST Nativa de Turso usando fetch
  try {
    const payload = {
      requests: [
        {"type": "execute", "stmt": {"sql": countSql, "args": sqlParams}},
        {"type": "execute", "stmt": {"sql": sql, "args": sqlParamsQuery}}
      ]
    };

    const response = await fetch(`${TURSO_URL}/v2/pipeline`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${TURSO_TOKEN}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });

    if (response.ok) {
      const resData = await response.json();

      // Parsear total
      const countRows = resData.results[0].response.result.rows;
      const totalItems = countRows.length > 0 ? parseInt(countRows[0][0].value) : 0;

      // Parsear normas
      const rows = resData.results[1].response.result.rows;
      const cols = resData.results[1].response.result.cols.map(c => c.name);

      const normas = rows.map(r => {
        const rowVals = r.map(val => val.value);
        // Crear diccionario columna -> valor
        const rowDict = rowVals.reduce((acc, val, idx) => {
          acc[cols[idx]] = val;
          return acc;
        }, {});

        return {
          id: parseInt(rowDict.id || 0),
          numero: rowDict.numero,
          titulo: rowDict.titulo,
          resumen: rowDict.resumen,
          tipo_nombre: rowDict.tipo_nombre,
          categoria_nombre: rowDict.categoria_nombre,
          vigente: parseInt(rowDict.vigente || 1) === 1,
          fecha: rowDict.fecha,
          archivo_pdf: rowDict.archivo_pdf,
          url_detalle: rowDict.url_detalle
        };
      });

      return {
        statusCode: 200,
        headers,
        body: JSON.stringify({
          normas: normas,
          total: totalItems,
          page: currentPage,
          totalPages: Math.ceil(totalItems / itemsPerPage)
        })
      };
    } else {
      const errText = await response.text();
      return {
        statusCode: 500,
        headers,
        body: JSON.stringify({ error: `Error de Turso REST: ${errText}` })
      };
    }
  } catch (error) {
    console.error("Error en Serverless API fetch:", error);
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({ error: error.message })
    };
  }
};
