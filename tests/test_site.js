const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const pendingStorageKey = (itemId, key) =>
  `pr_pending_op_v1:${encodeURIComponent(`${itemId}\u0000${key}`)}`;

function loadApp({storage = {}, sharedValues, fetchImpl, locks, innerWidth = 1024}) {
  const values = sharedValues || new Map(Object.entries(storage));
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
    navigator: {clipboard: {writeText: async () => {}}, ...(locks ? {locks} : {})},
    window: {
      innerWidth,
      addEventListener: (name, fn) => { listeners[name] = fn; },
    },
    document: {
      getElementById: id => id === 'syncStatus' ? syncStatus : null,
      createElement: () => ({classList: {add() {}, toggle() {}}}),
    },
    localStorage: {
      get length() { return values.size; },
      key: index => [...values.keys()][index] ?? null,
      getItem: key => values.has(key) ? values.get(key) : null,
      setItem: (key, value) => values.set(key, value),
      removeItem: key => values.delete(key),
    },
    fetch: fetchImpl,
  };
  context.globalThis = context;

  let source = fs.readFileSync(path.join(root, 'site', 'app.js'), 'utf8');
  source = source.replace(/\ninit\(\);\s*$/, '');
  source += `
    globalThis.TEST_API = {
      loadActionsFromServer,
      syncActionsOnLoad,
      persist,
      markSeen,
      retryPendingOps,
      pending: () => pendingOps,
      currentActions: () => actions,
      dateValue,
      syncStatusLabel,
      passSyncFilter,
      syncScoreText,
      syncApiError,
      syncCardHtml,
      paperTitleHtml,
      whyEntries,
      whyHtml,
      prpmBadgesHtml,
      paperOrder,
      profileSummaryHtml,
      addPrpmQuery,
      initialFilter,
      paperInTab,
      pageSlice,
      nextPageCount,
      pageSize: () => PAGE_SIZE,
      shouldFadeSeenCard,
    };
  `;
  vm.createContext(context);
  new vm.Script(source, {filename: 'site/app.js'}).runInContext(context);
  return {api: context.TEST_API, syncStatus, listeners, values};
}

function makeLocks() {
  const tails = new Map();
  return {
    request(name, callback) {
      const run = (tails.get(name) || Promise.resolve()).then(callback, callback);
      tails.set(name, run.catch(() => {}));
      return run;
    },
  };
}

test('HTTP 500 keeps one pending operation and retry clears it', async () => {
  const responses = [{ok: false}, {ok: true}];
  const sent = [];
  const {api, syncStatus} = loadApp({
    fetchImpl: async (_url, options) => {
      sent.push(JSON.parse(options.body));
      return responses.shift();
    },
  });
  const paper = {item_id: 'doi:one', doi: '10.1/one', title: 'One'};

  await api.persist(paper, 'content', true);

  assert.equal(Object.keys(api.pending()).length, 1);
  assert.equal(syncStatus.textContent, '尚有 1 筆未同步');

  await api.retryPendingOps();

  assert.equal(Object.keys(api.pending()).length, 0);
  assert.equal(syncStatus.textContent, '');
  assert.ok(sent[0].event_id);
  assert.equal(sent[0].event_id, sent[1].event_id);
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
  const newer = {
    item_id: 'doi:two', doi: '10.1/two', title: 'Two',
    key: 'content', val: true, updated: '2026-07-15T01:02:03.000Z',
  };
  const older = {...newer, key: 'seen', updated: '2026-07-15T01:01:00.000Z'};
  const {api} = loadApp({
    storage: {
      [pendingStorageKey(newer.item_id, newer.key)]: JSON.stringify(newer),
      [pendingStorageKey(older.item_id, older.key)]: JSON.stringify(older),
    },
    fetchImpl: async () => ({
      ok: true,
      json: async () => ({actions: [{item_id: newer.item_id, content: 0}]})
    }),
  });

  await api.loadActionsFromServer();

  assert.equal(api.currentActions()[newer.item_id].content, true);
  assert.equal(api.currentActions()[newer.item_id].updated, newer.updated);
});

test('initial state load finishes before online retry can clear its overlay', async () => {
  const op = {
    item_id: 'doi:init-race', doi: '10.1/init-race', title: 'Init race',
    key: 'content', val: true, updated: '2026-07-15T02:00:00.000Z',
  };
  let releaseState;
  let posts = 0;
  const {api, listeners} = loadApp({
    storage: {[pendingStorageKey(op.item_id, op.key)]: JSON.stringify(op)},
    fetchImpl: async url => {
      if(url.startsWith('/api/state')) {
        return new Promise(resolve => { releaseState = resolve; });
      }
      posts++;
      return {ok: true};
    },
  });

  const syncing = api.syncActionsOnLoad();
  assert.equal(listeners.online, undefined);
  releaseState({ok: true, json: async () => ({actions: [{item_id: op.item_id, content: 0}]})});
  await syncing;

  assert.equal(api.currentActions()[op.item_id].content, true);
  assert.equal(Object.keys(api.pending()).length, 0);
  assert.equal(posts, 1);
  assert.equal(typeof listeners.online, 'function');
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

test('two tabs keep different pending keys without overwriting each other', async () => {
  const sharedValues = new Map();
  const locks = makeLocks();
  const failedFetch = async () => ({ok: false});
  const first = loadApp({sharedValues, locks, fetchImpl: failedFetch});
  const second = loadApp({sharedValues, locks, fetchImpl: failedFetch});
  const paper = {item_id: 'doi:tabs', doi: '10.1/tabs', title: 'Tabs'};

  await Promise.all([
    first.api.persist(paper, 'content', true),
    second.api.persist(paper, 'vote', 'up'),
  ]);

  const reloaded = loadApp({sharedValues, locks, fetchImpl: failedFetch});
  assert.equal(Object.keys(reloaded.api.pending()).length, 2);
});

test('two tabs serialize the same key so the latest assignment reaches D1 last', async () => {
  const sharedValues = new Map();
  const locks = makeLocks();
  const applied = [];
  let releaseFirst;
  let calls = 0;
  const first = loadApp({
    sharedValues,
    locks,
    fetchImpl: async (_url, options) => {
      const val = JSON.parse(options.body).val;
      calls++;
      if(calls === 1) {
        await new Promise(resolve => { releaseFirst = resolve; });
      }
      applied.push(val);
      return {ok: true};
    },
  });
  const second = loadApp({
    sharedValues,
    locks,
    fetchImpl: async (_url, options) => {
      applied.push(JSON.parse(options.body).val);
      return {ok: true};
    },
  });
  const paper = {item_id: 'doi:same-key', doi: '10.1/same-key', title: 'Same key'};

  const oldRequest = first.api.persist(paper, 'content', true);
  await new Promise(resolve => setImmediate(resolve));
  const newRequest = second.api.persist(paper, 'content', false);
  releaseFirst();
  await Promise.all([oldRequest, newRequest]);

  assert.equal(applied.at(-1), false);
  assert.equal(Object.keys(first.api.pending()).length, 0);
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

test('form controls have accessible names and styles expose focus state', () => {
  const html = fs.readFileSync(path.join(root, 'site', 'index.html'), 'utf8');
  const css = fs.readFileSync(path.join(root, 'site', 'style.css'), 'utf8');

  for(const id of ['search', 'upFile', 'upTitle', 'upDoi', 'sort']){
    assert.match(html, new RegExp(`id="${id}"[^>]*aria-label="[^"]+"`));
  }
  assert.match(css, /:focus-visible/);
  assert.match(css, /min-height:\s*44px/);
});

test('mobile touch targets include buttons and native summaries', () => {
  const css = fs.readFileSync(path.join(root, 'site', 'style.css'), 'utf8');
  const rule = css.match(/@media \(max-width:599px\)\{\s*([^{}]+)\{min-height:\s*44px\}/);
  assert.ok(rule);

  const selectors = rule[1].split(',').map(selector => selector.trim());
  assert.ok(selectors.includes('button'), 'mobile touch targets must include buttons');
  assert.ok(selectors.includes('summary'), 'mobile touch targets must include native summaries');
});

test('topic toggles are native pressed buttons', () => {
  const source = fs.readFileSync(path.join(root, 'site', 'app.js'), 'utf8');

  assert.match(source, /document\.createElement\('button'\)/);
  assert.match(source, /setAttribute\('aria-pressed'/);
});

test('sync dashboard labels expose actionable Traditional Chinese states', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});

  assert.equal(api.syncStatusLabel('sync', 'blocked'), '阻塞');
  assert.equal(api.syncStatusLabel('pdf', 'missing'), '缺全文');
  assert.equal(api.syncStatusLabel('pdf', 'identity_mismatch'), '全文抓錯');
  assert.equal(api.syncStatusLabel('pdf', 'uploaded'), '手動上傳，待核對');
});

test('sync dashboard filters pending, missing, mismatch, synced, and explore', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});
  const pending = {sync_status: 'pending', pdf_status: 'missing', explore: false};
  const mismatch = {sync_status: 'blocked', pdf_status: 'identity_mismatch', explore: false};
  const synced = {sync_status: 'synced', pdf_status: 'verified', explore: true};

  assert.equal(api.passSyncFilter(pending, 'pending'), true);
  assert.equal(api.passSyncFilter(pending, 'missing'), true);
  assert.equal(api.passSyncFilter(mismatch, 'mismatch'), true);
  assert.equal(api.passSyncFilter(synced, 'synced'), true);
  assert.equal(api.passSyncFilter(synced, 'explore'), true);
  assert.equal(api.passSyncFilter(mismatch, 'synced'), false);
});

test('sync dashboard score and card automatically include optional PRPM fields', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});
  const item = {
    item_id: 'doi:10.1/example', title: '<Example>', content: true, deepread: true, star: true,
    sync_status: 'blocked', pdf_status: 'identity_mismatch', pdf_source: 'r2',
    sync_error: '<wrong PDF>', sync_updated_at: '2026-07-15T10:00:00Z',
    score: 8, kw_score: 6, rank: 3, explore: true, why: ['implant', 'recent'],
  };

  assert.equal(api.syncScoreText(item), 'Score 8 · Keyword 6 · Rank 3 · 探索');
  const html = api.syncCardHtml(item);
  assert.match(html, /&lt;Example&gt;/);
  assert.match(html, /內容/);
  assert.match(html, /品質/);
  assert.match(html, /筆記/);
  assert.match(html, /全文抓錯/);
  assert.match(html, /implant/);
  assert.doesNotMatch(html, /<wrong PDF>/);
});

test('sync API failures have a readable dashboard message and tab entry', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});
  const html = fs.readFileSync(path.join(root, 'site', 'index.html'), 'utf8');

  assert.equal(api.syncApiError(503), '同步狀態暫時無法載入（HTTP 503），請稍後重試。');
  assert.match(html, /data-tab="sync"[^>]*>同步狀態</);
});

test('automatic seen persistence carries implicit context', async () => {
  const sent = [];
  const {api} = loadApp({
    fetchImpl: async (_url, options) => { sent.push(JSON.parse(options.body)); return {ok: true}; },
  });
  const paper = {item_id: 'doi:implicit', doi: '10.1/implicit', title: 'Implicit'};

  await api.markSeen(paper);

  assert.equal(sent[0].key, 'seen');
  assert.deepEqual(sent[0].ctx, {implicit: true});
});

test('PRPM helpers support object and legacy string reasons', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});
  const paper = {
    kw_score: 5, explore: true,
    why: [{label: 'peri-implantitis', weight: 1.25}, 'legacy reason'],
  };

  assert.deepEqual(JSON.parse(JSON.stringify(api.whyEntries(paper))), [
    {label: 'peri-implantitis', weight: 1.25},
    {label: 'legacy reason', weight: null},
  ]);
  assert.match(api.whyHtml(paper), /peri-implantitis/);
  assert.match(api.prpmBadgesHtml(paper), /探索/);
  assert.match(api.prpmBadgesHtml(paper), /Keyword 5/);
});

test('paper title links to source and falls back to text', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});

  assert.match(
    api.paperTitleHtml({title: '<RCT>', url: 'https://pubmed.ncbi.nlm.nih.gov/1/'}),
    /<a class="c-title-link"[^>]*target="_blank"[^>]*>&lt;RCT&gt;<\/a>/,
  );
  assert.equal(
    api.paperTitleHtml({title: '<No URL>'}),
    '<span class="c-title-text">&lt;No URL&gt;</span>',
  );
});

test('paper title rejects unsafe URL protocols', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});

  assert.equal(
    api.paperTitleHtml({title: '<Unsafe>', url: 'javascript:alert(1)'}),
    '<span class="c-title-text">&lt;Unsafe&gt;</span>',
  );
});

test('recommendation reasons are compact and limited to three', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});
  const html = api.whyHtml({why: [
    {label: 'implant', weight: 2},
    {label: 'GBR', weight: 1.5},
    {label: 'RCT', weight: 1},
    {label: 'fourth', weight: 0.5},
  ]});

  assert.match(html, /class="recommendation"/);
  assert.match(html, /implant \+2/);
  assert.doesNotMatch(html, /<details/);
  assert.doesNotMatch(html, /fourth/);
});

test('paper card source keeps primary and secondary action groups', () => {
  const source = fs.readFileSync(path.join(root, 'site', 'app.js'), 'utf8');

  assert.match(source, /acts-primary/);
  assert.match(source, /整理筆記/);
  assert.match(source, /上傳 PDF/);
  assert.match(source, /acts-votes/);
  assert.match(source, /more-actions/);
  assert.match(source, /品質評讀/);
  assert.match(source, /內容整理/);
  assert.match(source, /aria-expanded/);
  assert.match(source, /aria-controls/);
});

test('paper card score header does not interpolate raw score into HTML', () => {
  const source = fs.readFileSync(path.join(root, 'site', 'app.js'), 'utf8');

  assert.match(source, /paperScoreText/);
  assert.doesNotMatch(source, /推薦分數 \$\{p\.score\}/);
  assert.doesNotMatch(source, />\$\{p\.score\}<\/span>/);
});

test('site assets use the round 4 cache key', () => {
  const html = fs.readFileSync(path.join(root, 'site', 'index.html'), 'utf8');
  assert.match(html, /style\.css\?v=20260715d/);
  assert.match(html, /app\.js\?v=20260715d/);
});

test('default PRPM ordering prefers rank and profile summary is public-safe', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});
  const papers = [{rank: 2, score: 10}, {rank: 1, score: 5}];
  papers.sort(api.paperOrder);
  assert.equal(papers[0].rank, 1);

  const html = api.profileSummaryHtml({
    events: {total: 12, positive: 8, negative: 4},
    top_liked: [{feature: '<implant>', weight: 2.1}],
    top_avoided: [{feature: 'narrative review', weight: -1.2}],
  });
  assert.match(html, /12/);
  assert.match(html, /&lt;implant&gt;/);
  assert.doesNotMatch(html, /<implant>/);
  const index = fs.readFileSync(path.join(root, 'site', 'index.html'), 'utf8');
  assert.match(index, /id="profileSummary"/);
});

test('partial rank ordering stays transitive and upload carries PRPM context', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});
  const papers = [{rank: 2, score: 2}, {score: 12}, {rank: 1, score: 1}];
  papers.sort(api.paperOrder);
  assert.deepEqual(papers.map(p => p.rank || null), [1, 2, null]);

  const qs = api.addPrpmQuery(new URLSearchParams(), {
    rank: 6, score: 5.3, explore: true, isNew: true,
  });
  assert.equal(qs.get('rank'), '6');
  assert.equal(qs.get('score'), '5.3');
  assert.equal(qs.get('explore'), '1');
  assert.equal(qs.get('badge'), 'NEW');
});

test('first visit defaults to weekly on mobile and unseen on desktop', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});

  assert.equal(api.initialFilter(null, 390).tab, 'weekly');
  assert.equal(api.initialFilter(null, 1024).tab, 'unseen');
});

test('saved tab is not overwritten by viewport width', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});
  const saved = {badge: 'oa', sort: 'date', search: 'implant', tab: 'seen'};

  assert.deepEqual(
    JSON.parse(JSON.stringify(api.initialFilter(saved, 390))),
    saved,
  );
  const legacy = api.initialFilter({badge: 'all', sort: 'score', search: '', showSeen: true}, 390);
  assert.equal(legacy.tab, 'seen');
  assert.equal('showSeen' in legacy, false);
});

test('weekly tab includes only new papers that are not already seen', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});
  const fresh = {item_id: 'doi:fresh', isNew: true};
  const old = {item_id: 'doi:old', isNew: false};

  assert.equal(api.paperInTab(fresh, 'weekly', {}, false), true);
  assert.equal(api.paperInTab(old, 'weekly', {}, false), false);
  assert.equal(api.paperInTab(fresh, 'weekly', {seen: true}, true), false);
  assert.equal(api.paperInTab(fresh, 'weekly', {seen: true}, false), true);
  assert.equal(api.paperInTab(fresh, 'seen', {seen: true}, true), true);
});

test('weekly seen cards start the same fade transition as unseen cards', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});
  const seen = {seen: true};

  assert.equal(api.shouldFadeSeenCard('weekly', seen, false), true);
  assert.equal(api.shouldFadeSeenCard('unseen', seen, false), true);
  assert.equal(api.shouldFadeSeenCard('weekly', seen, true), false);
  assert.equal(api.shouldFadeSeenCard('seen', seen, false), false);
});

test('paper batches are limited to 25 and grow by 25', () => {
  const {api} = loadApp({fetchImpl: async () => ({ok: true})});
  const papers = Array.from({length: 61}, (_, index) => ({item_id: `p${index}`}));

  assert.equal(api.pageSize(), 25);
  assert.equal(api.pageSlice(papers, 25).length, 25);
  assert.equal(api.nextPageCount(25, papers.length), 50);
  assert.equal(api.nextPageCount(50, papers.length), 61);
});

test('index exposes weekly tab and one load-more control', () => {
  const html = fs.readFileSync(path.join(root, 'site', 'index.html'), 'utf8');

  assert.match(html, /data-tab="weekly"[^>]*>本週新文</);
  assert.equal((html.match(/id="loadMore"/g) || []).length, 1);
});
