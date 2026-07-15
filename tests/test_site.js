const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');

function loadApp({storage = {}, fetchImpl}) {
  const values = new Map(Object.entries(storage));
  const listeners = {};
  const syncStatus = {
    textContent: '',
    classList: {toggle() {}},
  };
  const context = {
    console,
    Date,
    JSON,
    Map,
    Set,
    Promise,
    URLSearchParams,
    setTimeout,
    clearTimeout,
    requestAnimationFrame: fn => fn(),
    navigator: {clipboard: {writeText: async () => {}}},
    window: {
      innerWidth: 1024,
      addEventListener: (name, fn) => { listeners[name] = fn; },
    },
    document: {
      getElementById: id => id === 'syncStatus' ? syncStatus : null,
      createElement: () => ({classList: {add() {}, toggle() {}}}),
    },
    localStorage: {
      getItem: key => values.has(key) ? values.get(key) : null,
      setItem: (key, value) => values.set(key, value),
    },
    fetch: fetchImpl,
  };
  context.globalThis = context;

  let source = fs.readFileSync(path.join(root, 'site', 'app.js'), 'utf8');
  source = source.replace(/\ninit\(\);\s*$/, '');
  source += `
    globalThis.TEST_API = {
      loadActionsFromServer,
      persist,
      retryPendingOps,
      pending: () => pendingOps,
      currentActions: () => actions,
      dateValue,
    };
  `;
  vm.createContext(context);
  new vm.Script(source, {filename: 'site/app.js'}).runInContext(context);
  return {api: context.TEST_API, syncStatus, listeners, values};
}

test('HTTP 500 keeps one pending operation and retry clears it', async () => {
  const responses = [{ok: false}, {ok: true}];
  const {api, syncStatus} = loadApp({
    fetchImpl: async () => responses.shift(),
  });
  const paper = {item_id: 'doi:one', doi: '10.1/one', title: 'One'};

  await api.persist(paper, 'content', true);

  assert.equal(Object.keys(api.pending()).length, 1);
  assert.equal(syncStatus.textContent, '尚有 1 筆未同步');

  await api.retryPendingOps();

  assert.equal(Object.keys(api.pending()).length, 0);
  assert.equal(syncStatus.textContent, '');
});

test('pending operation survives a fresh app instance and then retries', async () => {
  const paper = {item_id: 'doi:reload', doi: '10.1/reload', title: 'Reload'};
  const first = loadApp({
    storage: {pr_actions_v1: JSON.stringify({[paper.item_id]: {content: true}})},
    fetchImpl: async () => ({ok: false}),
  });
  await first.api.persist(paper, 'content', true);

  const second = loadApp({
    storage: Object.fromEntries(first.values),
    fetchImpl: async url => url.startsWith('/api/state') ? {ok: false} : {ok: true},
  });

  assert.equal(Object.keys(second.api.pending()).length, 1);
  assert.equal(second.api.currentActions()[paper.item_id].content, true);
  await second.api.retryPendingOps();
  assert.equal(Object.keys(second.api.pending()).length, 0);
});

test('D1 load overlays pending local values instead of discarding them', async () => {
  const op = {
    item_id: 'doi:two', doi: '10.1/two', title: 'Two',
    key: 'content', val: true, updated: '2026-07-15T01:02:03.000Z',
  };
  const queue = {[`${op.item_id}\u0000${op.key}`]: op};
  const {api} = loadApp({
    storage: {pr_pending_ops_v1: JSON.stringify(queue)},
    fetchImpl: async () => ({
      ok: true,
      json: async () => ({actions: [{item_id: op.item_id, content: 0}]})
    }),
  });

  await api.loadActionsFromServer();

  assert.equal(api.currentActions()[op.item_id].content, true);
  assert.equal(api.currentActions()[op.item_id].updated, op.updated);
});

test('same item and key are sent serially with the latest assignment last', async () => {
  let releaseFirst;
  const sent = [];
  const {api} = loadApp({
    fetchImpl: async (_url, options) => {
      sent.push(JSON.parse(options.body));
      if(sent.length === 1) {
        return new Promise(resolve => { releaseFirst = resolve; });
      }
      return {ok: true};
    },
  });
  const paper = {item_id: 'doi:three', doi: '10.1/three', title: 'Three'};

  const first = api.persist(paper, 'content', true);
  const second = api.persist(paper, 'content', false);

  assert.equal(Object.keys(api.pending()).length, 1);
  assert.equal(Object.values(api.pending())[0].val, false);
  assert.equal(sent.length, 1);

  releaseFirst({ok: true});
  await Promise.all([first, second]);

  assert.deepEqual(sent.map(op => op.val), [true, false]);
  assert.equal(Object.keys(api.pending()).length, 0);
});

test('dateValue prefers normalized publication date and falls back to first seen', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});

  assert.equal(
    api.dateValue({pub_date_sort: '2026-07-01', first_seen: '2026-01-01'}),
    '2026-07-01',
  );
  assert.equal(api.dateValue({first_seen: '2026-01-01'}), '2026-01-01');
});

test('header contains the unsynced operation indicator', () => {
  const html = fs.readFileSync(path.join(root, 'site', 'index.html'), 'utf8');
  assert.match(html, /id="syncStatus"/);
});
