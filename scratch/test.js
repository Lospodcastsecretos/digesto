const token = 'process.env.TURSO_TOKEN';
const url = 'process.env.TURSO_URL/v2/pipeline';

const queries = [
  '"taxi"*',
  'taxi*',
  'taxi',
  '"becerra"*',
  'becerra'
];

async function run() {
  for (let q of queries) {
    const searchSql = 'SELECT id, numero, titulo FROM normas WHERE id IN (SELECT id FROM normas_fts WHERE normas_fts MATCH ?) LIMIT 4';
    
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        requests: [
          { type: 'execute', stmt: { sql: searchSql, args: [{ type: 'text', value: q }] } },
          { type: 'close' }
        ]
      })
    });
    const d = await resp.json();
    console.log("QUERY:", q);
    if(d.results[0].type === 'error') {
       console.log("ERROR:", d.results[0].error.message);
    } else {
       console.log("ROWS:", d.results[0].response.result.rows);
    }
  }
}
run();
