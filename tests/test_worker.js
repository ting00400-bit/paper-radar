const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadWorker({rows = [], papers = [], failActionLog = false} = {}) {
  const statements = [];
  const puts = [];
  const source = fs.readFileSync(path.join(__dirname, '..', 'site', '_worker.js'), 'utf8')
    .replace('export default {', 'globalThis.TEST_WORKER = {');
  const context = {
    URL,
    Response,
    Request,
    Date,
    console,
  };
  vm.createContext(context);
  vm.runInContext(source, context, {filename: 'site/_worker.js'});

  const env = {
    DB: {
      prepare(sql) {
        const call = {sql, args: []};
        statements.push(call);
        const statement = {
          bind(...args) { call.args = args; return statement; },
          async first() { return null; },
          async all() { return {results: rows}; },
          async run() {
            if (failActionLog && /INSERT(?: OR IGNORE)? INTO action_log/.test(sql)) {
              throw new Error('no such table: action_log');
            }
            return {success: true};
          },
        };
        return statement;
      },
    },
    PDFS: {
      async put(...args) { puts.push(args); },
      async get() { return null; },
    },
    ASSETS: {
      async fetch(request) {
        const url = String(request?.url || request);
        if (new URL(url).pathname === '/papers.json') {
          return new Response(JSON.stringify({papers}), {
            headers: {'Content-Type': 'application/json'},
          });
        }
        return new Response('asset');
      },
    },
  };
  return {worker: context.TEST_WORKER, env, statements, puts};
}

function request(url, method = 'GET', body = null) {
  return {
    url,
    method,
    body,
    headers: new Headers(body ? {
      'content-type': 'application/pdf',
      'content-length': '2048',
    } : {}),
  };
}

test('GET /api/sync-status joins action state with scoring and sanitizes output', async () => {
  const action = {
    item_id: 'doi:10.1234/example', doi: '10.1234/example', title: 'D1 title',
    content: 1, deepread: 0, star: 0, synced: 0,
    sync_status: 'blocked', pdf_status: 'identity_mismatch', pdf_source: 'r2',
    sync_error: 'R2 PDF belongs to another DOI at C:\\Users\\Ting\\My Project\\wrong.pdf https://resolver.test/x',
    sync_updated_at: '2026-07-15T10:00:00Z',
    pdf_key: 'pdf/secret.pdf',
  };
  const paper = {
    item_id: action.item_id, doi: action.doi, title: 'Generated title',
    score: 8, kw_score: 6, rank: 3, explore: true,
    why: [{label: 'implant', weight: 1.2}, 'recent'],
  };
  const {worker, env, statements} = loadWorker({rows: [action], papers: [paper]});

  const response = await worker.fetch(request('https://radar.test/api/sync-status'), env);
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.items.length, 1);
  assert.deepEqual(payload.items[0], {
    item_id: action.item_id,
    doi: action.doi,
    title: paper.title,
    content: true,
    deepread: false,
    star: false,
    synced: false,
    sync_status: 'blocked',
    note_status: null,
    note_verified: null,
    note_path: null,
    pdf_status: 'identity_mismatch',
    pdf_source: 'r2',
    sync_error: 'R2 PDF belongs to another DOI at [local path] [URL]',
    sync_updated_at: action.sync_updated_at,
    score: 8,
    kw_score: 6,
    rank: 3,
    explore: true,
    why: ['implant', 'recent'],
  });
  assert.equal('pdf_key' in payload.items[0], false);
  assert.doesNotMatch(payload.items[0].sync_error, /C:\\|https:\/\//);
  assert.match(statements[0].sql, /content=1 OR deepread=1 OR star=1 OR sync_status IS NOT NULL/);
});

test('manual PDF upload records uploaded and pending status in the D1 upsert', async () => {
  const {worker, env, statements, puts} = loadWorker();
  const response = await worker.fetch(request(
    'https://radar.test/api/upload?item_id=doi%3A10.1234%2Fexample&doi=10.1234%2Fexample&title=Example&content=1',
    'POST',
    {stream: true},
  ), env);

  assert.equal(response.status, 200);
  assert.equal(puts.length, 1);
  const upsert = statements.find(call => /INSERT INTO actions/.test(call.sql));
  assert.ok(upsert);
  assert.match(upsert.sql, /sync_status/);
  assert.match(upsert.sql, /pdf_status/);
  assert.match(upsert.sql, /pdf_source/);
  assert.match(upsert.sql, /sync_error/);
  assert.match(upsert.sql, /sync_updated_at/);
  assert.ok(upsert.args.includes('pending'));
  assert.ok(upsert.args.includes('uploaded'));
  assert.ok(upsert.args.includes('manual_upload'));
});

test('work actions become pending but seen-only actions do not', async () => {
  const work = loadWorker();
  const workResponse = await work.worker.fetch({
    ...request('https://radar.test/api/action', 'POST'),
    async json() { return {item_id: 'doi:10.1234/example', key: 'content', val: true}; },
  }, work.env);
  assert.equal(workResponse.status, 200);
  assert.match(work.statements[0].sql, /sync_status/);
  assert.ok(work.statements[0].args.includes('pending'));

  const seen = loadWorker();
  const seenResponse = await seen.worker.fetch({
    ...request('https://radar.test/api/action', 'POST'),
    async json() { return {item_id: 'doi:10.1234/example', key: 'seen', val: true}; },
  }, seen.env);
  assert.equal(seenResponse.status, 200);
  assert.doesNotMatch(seen.statements[0].sql, /sync_status/);
  assert.doesNotMatch(seen.statements[0].sql, /synced=0/);
});

test('disabling a work action clears ghost status only when no work remains', async () => {
  const disabled = loadWorker();
  const response = await disabled.worker.fetch({
    ...request('https://radar.test/api/action', 'POST'),
    async json() { return {item_id: 'doi:10.1234/example', key: 'content', val: false}; },
  }, disabled.env);

  assert.equal(response.status, 200);
  const sql = disabled.statements[0].sql;
  assert.match(sql, /CASE WHEN/);
  assert.match(sql, /(?:deepread=1 OR star=1|star=1 OR deepread=1)/);
  assert.match(sql, /ELSE NULL END/);
  assert.match(sql, /synced=0/);
});

test('content and vote actions append mapped events after current state succeeds', async () => {
  const content = loadWorker();
  const contentResponse = await content.worker.fetch({
    ...request('https://radar.test/api/action', 'POST'),
    async json() {
      return {item_id: 'doi:10.1234/example', key: 'content', val: true, event_id: 'evt-one'};
    },
  }, content.env);
  assert.equal(contentResponse.status, 200);
  const contentLog = content.statements.find(call => /INSERT(?: OR IGNORE)? INTO action_log/.test(call.sql));
  assert.ok(contentLog);
  assert.match(contentLog.sql, /INSERT OR IGNORE INTO action_log/);
  assert.ok(contentLog.args.includes('content_on'));
  assert.equal(contentLog.args[2], 'evt-one');
  assert.equal(contentLog.args[3], null);

  const vote = loadWorker();
  await vote.worker.fetch({
    ...request('https://radar.test/api/action', 'POST'),
    async json() { return {item_id: 'doi:10.1234/example', key: 'vote', val: 'down'}; },
  }, vote.env);
  const voteLog = vote.statements.find(call => /INSERT(?: OR IGNORE)? INTO action_log/.test(call.sql));
  assert.ok(voteLog.args.includes('vote_down'));
});

test('missing action_log is non-fatal and returns a rollout warning', async () => {
  const {worker, env} = loadWorker({failActionLog: true});
  const response = await worker.fetch({
    ...request('https://radar.test/api/action', 'POST'),
    async json() { return {item_id: 'doi:10.1234/example', key: 'deepread', val: true}; },
  }, env);

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {ok: true, warning: 'event_log_unavailable'});
});

test('retrying the same action payload reuses its event identity', async () => {
  const {worker, env, statements} = loadWorker();
  const payload = {
    item_id: 'doi:10.1234/retry', key: 'content', val: true,
    event_id: 'evt-retry-one', updated: '2026-07-15T00:00:00.000Z',
  };
  for (let i = 0; i < 2; i++) {
    await worker.fetch({
      ...request('https://radar.test/api/action', 'POST'),
      async json() { return payload; },
    }, env);
  }

  const inserts = statements.filter(call => /INSERT OR IGNORE INTO action_log/.test(call.sql));
  assert.equal(inserts.length, 2);
  assert.deepEqual(inserts.map(call => call.args[2]), ['evt-retry-one', 'evt-retry-one']);
});

test('only an explicit seen action emits seen_only', async () => {
  const explicit = loadWorker();
  await explicit.worker.fetch({
    ...request('https://radar.test/api/action', 'POST'),
    async json() { return {item_id: 'doi:10.1234/example', key: 'seen', val: true}; },
  }, explicit.env);
  assert.ok(explicit.statements.some(call => call.args.includes('seen_only')));

  const implicit = loadWorker();
  await implicit.worker.fetch({
    ...request('https://radar.test/api/action', 'POST'),
    async json() {
      return {item_id: 'doi:10.1234/example', key: 'seen', val: true, ctx: {implicit: true}};
    },
  }, implicit.env);
  assert.equal(implicit.statements.some(call => /INSERT(?: OR IGNORE)? INTO action_log/.test(call.sql)), false);
});

test('successful upload appends pdf_upload event', async () => {
  const {worker, env, statements} = loadWorker();
  const response = await worker.fetch(request(
    'https://radar.test/api/upload?item_id=doi%3A10.1234%2Fexample&doi=10.1234%2Fexample&title=Example&content=1&rank=6&score=5.3&explore=1&badge=NEW',
    'POST', {stream: true}), env);

  assert.equal(response.status, 200);
  const event = statements.find(call => /INSERT(?: OR IGNORE)? INTO action_log/.test(call.sql));
  assert.ok(event);
  assert.ok(event.args.includes('pdf_upload'));
  assert.equal(event.args[2], null);
  assert.deepEqual(JSON.parse(event.args[3]), {
    rank: 6, score: 5.3, explore: true, badge: 'NEW',
    manual: false, content: true, deepread: false,
  });
});
