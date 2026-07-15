# Paper Radar Round 4 UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Paper Radar 改成手機優先的單欄緊湊介面，加入本週新文入口、每批 25 篇渲染、清楚的卡片層級與基本無障礙，同時保留所有 D1 與 pipeline 語意。

**Architecture:** 維持單檔原生前端，不加 framework 或 dependency。把裝置預設、tab 判斷與分批數量做成少量純函式供 Node 測試，DOM 仍由既有 `render()` 與 `card()` 建立；CSS 只調整現有 selector 與手機 media query。

**Tech Stack:** Browser-native HTML/CSS/JavaScript、Node.js built-in test runner、Python pytest、Playwright Core + Microsoft Edge

## Global Constraints

- 正式設計依據：`docs/superpowers/specs/2026-07-15-paper-radar-round4-ui-design.md`。
- 不新增 npm／Python dependency，不引入 React、Vue 或 virtual list。
- 不修改 D1 schema、Worker API、`actions`／`action_log` 欄位或 paper pipeline 語意。
- `star`、`deepread`、`content`、`vote`、`seen` 與 upload route 必須維持原 key／route。
- 主操作保留 `已看`、`整理筆記`、`上傳 PDF`、👍／😐／👎；`品質評讀` 與 `內容整理` 放進更多區。
- 手機首次使用預設 `weekly`，桌面首次使用預設 `unseen`；已有 `LS_FILT` 時尊重已存分頁。
- 論文分頁每批 25 篇；同步狀態 dashboard 不分批。
- 所有正式程式修改都遵守 TDD：先執行失敗測試，再寫最小實作。
- 不執行 `paper_sync.py done`；不推 GitHub、不更新 NAS、不部署 Cloudflare，直到 Ting 另行確認。

## File Map

- Modify: `site/app.js` — view state、tab 篩選、分批渲染、卡片 DOM 與互動。
- Modify: `site/index.html` — 四分頁、載入更多按鈕與控制項 accessible name。
- Modify: `site/style.css` — 方案 A 單欄卡片、操作分組、focus 與手機觸控尺寸。
- Modify: `tests/test_site.js` — 純函式、靜態 HTML／CSS 與既有動作語意回歸測試。

---

### Task 1: 本週新文分頁與每批 25 篇渲染

**Files:**
- Modify: `tests/test_site.js:9-57`
- Modify: `tests/test_site.js`（現有 PRPM 測試之後新增 view-state tests）
- Modify: `site/app.js:6-38`
- Modify: `site/app.js:172-203`
- Modify: `site/app.js:274-378`
- Modify: `site/index.html:22-28`
- Modify: `site/index.html:94-97`

**Interfaces:**
- Consumes: `LS_FILT`、`actions`、`seenAtLoad`、`DATA.papers`、既有 `render()`／`save()`。
- Produces:
  - `initialFilter(saved, width) -> {badge, sort, search, tab}`
  - `paperInTab(paper, tab, action, wasSeenAtLoad) -> boolean`
  - `pageSlice(papers, count) -> papers[]`
  - `nextPageCount(current, total) -> number`
  - `resetPagination() -> void`
  - constant `PAGE_SIZE = 25`

- [ ] **Step 1: 擴充 test harness，寫入失敗測試**

把 `loadApp` signature 與 `window.innerWidth` 改成可注入寬度：

```diff
-function loadApp({storage = {}, sharedValues, fetchImpl, locks}) {
+function loadApp({storage = {}, sharedValues, fetchImpl, locks, innerWidth = 1024}) {
@@
     window: {
-      innerWidth: 1024,
+      innerWidth,
       addEventListener: (name, fn) => { listeners[name] = fn; },
     },
```

在 `globalThis.TEST_API` 物件尾端、`addPrpmQuery` 後加入：

```js
      initialFilter,
      paperInTab,
      pageSlice,
      nextPageCount,
      pageSize: () => PAGE_SIZE,
```

在 `tests/test_site.js` 新增：

```js
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
```

- [ ] **Step 2: 執行新測試並確認 RED**

Run:

```powershell
node --test --test-name-pattern="first visit|saved tab|weekly tab|paper batches|weekly tab and one load-more" tests/test_site.js
```

Expected: FAIL，錯誤包含 `initialFilter is not defined`，且 `index.html` 找不到 `data-tab="weekly"`／`id="loadMore"`。

- [ ] **Step 3: 實作最小 view-state 純函式**

在 `site/app.js` 的 storage constants 後加入：

```js
const PAGE_SIZE = 25;

function initialFilter(saved, width){
  const filter = {
    badge: 'all', sort: 'score', search: '',
    tab: width < 600 ? 'weekly' : 'unseen',
    ...(saved || {}),
  };
  if(saved && saved.tab === undefined && 'showSeen' in saved){
    filter.tab = saved.showSeen ? 'seen' : 'unseen';
    delete filter.showSeen;
  }
  return filter;
}

function paperInTab(paper, tab, action={}, wasSeenAtLoad=false){
  if(tab === 'seen') return !!action.seen;
  if(tab === 'weekly' && !paper.isNew) return false;
  if(!action.seen) return true;
  return !wasSeenAtLoad;
}

const pageSlice = (papers, count) => papers.slice(0, count);
const nextPageCount = (current, total) => Math.min(current + PAGE_SIZE, total);
```

把 filter 初始化與 pagination state 改成：

```js
let filt = initialFilter(load(LS_FILT, null), window.innerWidth);
let visibleCount = PAGE_SIZE;
function resetPagination(){ visibleCount = PAGE_SIZE; }
```

把 `passSeen()` 改成只轉接 pure helper：

```js
function passTab(p){
  return paperInTab(
    p,
    filt.tab,
    actions[p.item_id] || {},
    seenAtLoad.has(p.item_id),
  );
}
```

- [ ] **Step 4: 加入 weekly tab、load-more DOM 與 reset bindings**

把 `site/index.html` 的 tabs 改成：

```html
<div class="tabs" id="tabs">
  <button class="tab" data-tab="weekly">本週新文</button>
  <button class="tab" data-tab="unseen">全部未看</button>
  <button class="tab" data-tab="seen">已看</button>
  <button class="tab" data-tab="sync">同步狀態</button>
</div>
```

在 `<main id="list"></main>` 後加入：

```html
<button id="loadMore" class="load-more hidden" type="button">載入更多</button>
```

新增 binding：

```js
function bindLoadMore(){
  const button = document.getElementById('loadMore');
  button.onclick = () => {
    const total = Number(button.dataset.total || 0);
    visibleCount = nextPageCount(visibleCount, total);
    render();
  };
}

function renderFromStart(){
  resetPagination();
  render();
}
```

在 `init()` 的 `bindTabs()` 後加入：

```js
  bindLoadMore();
```

把會改變結果集合的 handlers 改為以下內容；`card()`、`actBtn()` 與 upload success 內的 `render()` 不改，避免每次按單篇操作都跳回第一批：

```js
// buildTopics() onclick 最後一行
renderFromStart();

// buildVisitBanner() onclick 最後一行
renderFromStart();

// bindFilters()
s.oninput = () => {
  filt.search = s.value;
  save(LS_FILT, filt);
  renderFromStart();
};
sort.onchange = () => {
  filt.sort = sort.value;
  save(LS_FILT, filt);
  renderFromStart();
};
document.querySelectorAll('#badgeFilter .chip').forEach(chip => {
  chip.onclick = () => {
    filt.badge = chip.dataset.badge;
    save(LS_FILT, filt);
    syncBadgeUI();
    renderFromStart();
  };
});

// bindTabs()
document.querySelectorAll('#tabs .tab').forEach(tab => {
  tab.onclick = () => {
    filt.tab = tab.dataset.tab;
    save(LS_FILT, filt);
    syncSortOptions();
    renderFromStart();
    if(filt.tab === 'sync' && syncLoadState === 'idle') loadSyncItems();
  };
});
```

- [ ] **Step 5: 改寫 tab count 與 render slicing**

把 `syncTabUI()` 改為：

```js
function syncTabUI(unseenN, seenN, weeklyN){
  document.querySelectorAll('#tabs .tab').forEach(t => {
    t.classList.toggle('on', t.dataset.tab === filt.tab);
    t.textContent = t.dataset.tab === 'weekly' ? `本週新文 (${weeklyN})`
      : t.dataset.tab === 'unseen' ? `全部未看 (${unseenN})`
      : t.dataset.tab === 'seen' ? `已看 (${seenN})`
      : `同步狀態${syncLoadState === 'ready' ? ` (${syncItems.length})` : ''}`;
  });
}
```

把論文分頁的 `render()` 主體改成：

```js
const base = DATA.papers.filter(p => passTopic(p) && passBadge(p) && passSearch(p));
let seenN = 0;
let weeklyN = 0;
for(const p of base){
  const seen = !!(actions[p.item_id] || {}).seen;
  if(seen) seenN++;
  if(p.isNew && !seen) weeklyN++;
}
syncTabUI(base.length - seenN, seenN, weeklyN);
if(filt.tab === 'sync'){
  renderSyncDashboard();
  document.getElementById('loadMore').classList.add('hidden');
  return;
}

const ps = base.filter(passTab);
const updatedAt = p => (actions[p.item_id] || {}).updated || '';
ps.sort(filt.sort === 'date'
  ? (a,b) => dateValue(b).localeCompare(dateValue(a))
  : filt.sort === 'seenat'
  ? (a,b) => updatedAt(b).localeCompare(updatedAt(a)) || b.score - a.score
  : paperOrder);
const visible = pageSlice(ps, visibleCount);
list.innerHTML = '';
if(!ps.length){
  list.innerHTML = `<div class="empty-state">${filt.tab === 'weekly'
    ? '本週沒有新文。<button id="showAllUnseen" type="button">查看全部未看</button>'
    : '目前沒有符合條件的論文。'}</div>`;
  document.getElementById('showAllUnseen')?.addEventListener('click', () => {
    filt.tab = 'unseen';
    save(LS_FILT, filt);
    renderFromStart();
  });
} else {
  for(const p of visible) list.appendChild(card(p));
}
const more = document.getElementById('loadMore');
more.dataset.total = String(ps.length);
more.classList.toggle('hidden', visible.length >= ps.length);
document.getElementById('count').textContent = `顯示 ${visible.length} / ${ps.length} 篇`;
```

- [ ] **Step 6: 執行 Task 1 tests 並確認 GREEN**

Run:

```powershell
node --test tests/test_site.js
```

Expected: 所有既有與新增 `test_site.js` tests PASS。

- [ ] **Step 7: Commit Task 1**

```powershell
git add -- tests/test_site.js site/app.js site/index.html
git diff --cached --check
git commit -m "feat(site): add focused paper pagination"
```

---

### Task 2: 原生控制元件與基本無障礙

**Files:**
- Modify: `tests/test_site.js`
- Modify: `site/app.js:244-254`
- Modify: `site/index.html:35-91`
- Modify: `site/style.css:2-60`
- Modify: `site/style.css`（mobile media query）

**Interfaces:**
- Consumes: `DATA.topic_groups`、`topics`、`LS_TOPIC`、`renderFromStart()`。
- Produces: 原生 topic buttons、input accessible names、focus ring、手機 44 px touch targets。

- [ ] **Step 1: 寫入無障礙失敗測試**

在 `tests/test_site.js` 新增：

```js
test('form controls have accessible names and styles expose focus state', () => {
  const html = fs.readFileSync(path.join(root, 'site', 'index.html'), 'utf8');
  const css = fs.readFileSync(path.join(root, 'site', 'style.css'), 'utf8');

  for(const id of ['search', 'upFile', 'upTitle', 'upDoi', 'sort']){
    assert.match(html, new RegExp(`id="${id}"[^>]*aria-label="[^"]+"`));
  }
  assert.match(css, /:focus-visible/);
  assert.match(css, /min-height:\s*44px/);
});

test('topic toggles are native pressed buttons', () => {
  const source = fs.readFileSync(path.join(root, 'site', 'app.js'), 'utf8');

  assert.match(source, /document\.createElement\('button'\)/);
  assert.match(source, /setAttribute\('aria-pressed'/);
});
```

- [ ] **Step 2: 執行新測試並確認 RED**

Run:

```powershell
node --test --test-name-pattern="accessible names|native pressed buttons" tests/test_site.js
```

Expected: FAIL，`index.html` 缺少 `aria-label`，CSS 找不到 `:focus-visible`／`min-height:44px`，`buildTopics()` 仍建立 `div`。

- [ ] **Step 3: 將 topic 改成 native button**

把 `buildTopics()` 改成：

```js
function buildTopics(){
  const box = document.getElementById('topics');
  box.innerHTML = '';
  for(const [key,value] of Object.entries(DATA.topic_groups)){
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'topic' + (topics[key] ? ' on' : '');
    button.textContent = value.label;
    button.setAttribute('aria-pressed', String(!!topics[key]));
    button.onclick = () => {
      topics[key] = !topics[key];
      save(LS_TOPIC, topics);
      button.classList.toggle('on');
      button.setAttribute('aria-pressed', String(!!topics[key]));
      renderFromStart();
    };
    box.appendChild(button);
  }
}
```

- [ ] **Step 4: 為所有 form controls 加 accessible name**

在 `site/index.html` 加入以下 attributes：

```html
<input type="search" id="search" aria-label="搜尋論文" placeholder="搜尋標題 / 作者 / 期刊…">
<input type="file" id="upFile" aria-label="選擇外部論文 PDF" accept="application/pdf">
<input type="text" id="upTitle" aria-label="外部論文標題" placeholder="標題（選填）">
<input type="text" id="upDoi" aria-label="外部論文 DOI" placeholder="DOI（選填，有的話更好）">
<select id="sort" aria-label="論文排序方式">
```

- [ ] **Step 5: 加入 focus、contrast 與手機觸控 CSS**

把 `--dim` 改為 `#506d67`，並加入：

```css
button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{
  outline:3px solid var(--accent);outline-offset:2px
}

.topic{font:inherit;cursor:pointer}
.load-more{display:block;width:calc(100% - 24px);max-width:736px;margin:0 auto 12px;
  padding:9px 12px;border-radius:10px;border:1px solid var(--line);background:var(--card);cursor:pointer}
.empty-state{text-align:center;color:var(--dim);padding:28px 12px}

@media (max-width:599px){
  .tab,.topic,.chip,.act,.copy,.summary-toggle,.load-more,input,select{min-height:44px}
}
```

保留既有 `.hidden{display:none!important}`，讓 `loadMore` 能正確收合。

- [ ] **Step 6: 執行 Task 2 tests 並確認 GREEN**

Run:

```powershell
node --test tests/test_site.js
```

Expected: 全部 PASS；既有同步、PRPM 與 pending-op tests 不受影響。

- [ ] **Step 7: Commit Task 2**

```powershell
git add -- tests/test_site.js site/app.js site/index.html site/style.css
git diff --cached --check
git commit -m "feat(site): make controls keyboard accessible"
```

---

### Task 3: 方案 A 單欄緊湊卡片

**Files:**
- Modify: `tests/test_site.js`
- Modify: `site/app.js:393-412`
- Modify: `site/app.js:526-624`
- Modify: `site/style.css:91-151`
- Modify: `site/index.html:8`
- Modify: `site/index.html:99`

**Interfaces:**
- Consumes: `whyEntries(paper)`、`copyBtn()`、`actBtn()`、`toggle()`、`toggleAct()`、`setVote()`、`uploadForPaper()`。
- Produces:
  - `paperTitleHtml(paper) -> safe HTML`
  - inline `whyHtml(paper) -> safe HTML`
  - `.c-head` score/title structure
  - `.acts-primary`、`.acts-votes`、`.more-actions` DOM groups
  - `.summary-toggle[aria-expanded][aria-controls]`

- [ ] **Step 1: 寫入卡片結構失敗測試**

在 `TEST_API` 匯出 `paperTitleHtml`，並在 `tests/test_site.js` 新增：

```js
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
  assert.match(source, /上傳PDF/);
  assert.match(source, /acts-votes/);
  assert.match(source, /more-actions/);
  assert.match(source, /品質評讀/);
  assert.match(source, /內容整理/);
  assert.match(source, /aria-expanded/);
  assert.match(source, /aria-controls/);
});

test('site assets use the round 4 cache key', () => {
  const html = fs.readFileSync(path.join(root, 'site', 'index.html'), 'utf8');
  assert.match(html, /style\.css\?v=20260715d/);
  assert.match(html, /app\.js\?v=20260715d/);
});
```

- [ ] **Step 2: 執行新測試並確認 RED**

Run:

```powershell
node --test --test-name-pattern="paper title|recommendation reasons|primary and secondary|round 4 cache" tests/test_site.js
```

Expected: FAIL，`paperTitleHtml is not defined`、`whyHtml()` 仍輸出 `<details>`、card source 沒有新 action groups、cache key 仍是 `20260715c`。

- [ ] **Step 3: 實作安全標題與 inline recommendation**

在 `whyEntries()` 前加入：

```js
function paperTitleHtml(paper){
  const title = esc(paper.title || '');
  return paper.url
    ? `<a class="c-title-link" href="${esc(paper.url)}" target="_blank" rel="noopener">${title}</a>`
    : `<span class="c-title-text">${title}</span>`;
}
```

把 `whyHtml()` 改成：

```js
function whyHtml(paper){
  const reasons = whyEntries(paper).slice(0, 3);
  if(!reasons.length) return '';
  return `<p class="recommendation"><span>推薦：</span>${reasons.map(reason =>
    `${esc(reason.label)}${reason.weight===null ? '' : ` ${reason.weight>0?'+':''}${reason.weight}`}`
  ).join(' · ')}</p>`;
}
```

- [ ] **Step 4: 重整 card header、摘要與 action groups**

在 `card(p)` 中，以以下結構取代原本獨立 score、可點擊 title 與單一 `.acts`：

```js
const body = document.createElement('div');
body.className = 'c-body';
body.innerHTML = `<div class="c-head">
    <span class="score${p.score>=5?' hi':p.score>=3?' mid':''}" aria-label="推薦分數 ${p.score}">${p.score}</span>
    <div class="c-title">${paperTitleHtml(p)}</div>
  </div>
  <div class="c-src">${esc(p.source_name)}${p.pub_date?' · '+p.pub_date:''}${p.authors?' · '+esc(p.authors.split(',').slice(0,3).join(','))+(p.authors.split(',').length>3?' et al.':''):''}</div>
  <div class="badges">${badges}</div>
  ${whyHtml(p)}`;

body.querySelector('.c-title').appendChild(copyBtn(()=>p.title, '複製標題'));

if(p.abstract){
  const abstractId = `abs-${p.item_id}`;
  const toggleButton = document.createElement('button');
  toggleButton.type = 'button';
  toggleButton.className = 'summary-toggle';
  toggleButton.setAttribute('aria-expanded', 'false');
  toggleButton.setAttribute('aria-controls', abstractId);
  toggleButton.innerHTML = `${ic('chevdown')} 摘要`;
  const abstract = document.createElement('div');
  abstract.className = 'abs';
  abstract.id = abstractId;
  abstract.innerHTML = formatAbs(p.abstract);
  abstract.prepend(copyBtn(()=>p.abstract, '複製摘要'));
  toggleButton.onclick = () => {
    const expanded = toggleButton.getAttribute('aria-expanded') !== 'true';
    toggleButton.setAttribute('aria-expanded', String(expanded));
    toggleButton.innerHTML = `${ic(expanded ? 'chevdown' : 'chevright')} ${expanded ? '收合摘要' : '摘要'}`;
    abstract.classList.toggle('show', expanded);
  };
  body.append(toggleButton, abstract);
}

const actionsBox = document.createElement('div');
actionsBox.className = 'acts';
const primary = document.createElement('div');
primary.className = 'acts-primary';
primary.appendChild(actBtn(ic('eye')+' 已看','seen',!!a.seen,()=>toggle(p,'seen')));
primary.appendChild(actBtn(ic('pen')+' 整理筆記','star',!!a.star,()=>toggleAct(p,'star')));
const upload = document.createElement('button');
upload.type = 'button';
upload.className = 'act upload';
upload.innerHTML = a.pdf_key ? ic('check')+' 已上傳' : ic('paperclip')+' 上傳PDF';
upload.onclick = () => uploadForPaper(p, upload);
primary.appendChild(upload);

const votes = document.createElement('div');
votes.className = 'acts-votes';
votes.setAttribute('aria-label', '論文評價');
votes.appendChild(actBtn(ic('thumbup'),'up vote',a.vote==='up',()=>setVote(p,'up'),'讚'));
votes.appendChild(actBtn(ic('meh'),'neutral vote',a.vote==='neutral',()=>setVote(p,'neutral'),'普通'));
votes.appendChild(actBtn(ic('thumbdown'),'down vote',a.vote==='down',()=>setVote(p,'down'),'不喜歡'));
actionsBox.append(primary, votes);
body.appendChild(actionsBox);

const more = document.createElement('details');
more.className = 'more-actions';
const moreSummary = document.createElement('summary');
moreSummary.textContent = '更多整理方式';
const moreButtons = document.createElement('div');
moreButtons.className = 'more-actions-buttons';
moreButtons.appendChild(actBtn(ic('microscope')+' 品質評讀','deepread',!!a.deepread,()=>toggleAct(p,'deepread')));
moreButtons.appendChild(actBtn(ic('book')+' 內容整理','content',!!a.content,()=>toggleAct(p,'content')));
more.append(moreSummary, moreButtons);
body.appendChild(more);

el.appendChild(body);
```

刪除原本 `body.querySelector('.c-title').onclick` 摘要切換；保留 `card()` 後段的 2.5 秒淡出程式。

把 `actBtn()` 補上 type 與 pressed state：

```js
function actBtn(label, cls, on, fn, tip){
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'act ' + cls.split(' ')[0] + (on?' on':'');
  button.innerHTML = label;
  button.setAttribute('aria-pressed', String(!!on));
  if(tip) button.setAttribute('aria-label', tip);
  button.onclick = () => { fn(); render(); };
  return button;
}
```

- [ ] **Step 5: 套用方案 A CSS 與 cache key**

以以下 selector 取代舊 `.score`／`.c-title`／`.acts` 版面規則：

```css
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:11px 12px;margin-bottom:10px;box-shadow:0 1px 2px rgba(18,56,50,.05)}
.c-body{min-width:0}
.c-head{display:flex;gap:8px;align-items:flex-start}
.score{flex:none;min-width:30px;height:30px;border-radius:7px;display:inline-flex;align-items:center;
  justify-content:center;font-weight:700;font-size:.85rem;background:#eaf4f1}
.c-title{flex:1;min-width:0;font-weight:600;font-size:.95rem}
.c-title-link{color:inherit;text-decoration-thickness:1px;text-underline-offset:2px}
.recommendation{font-size:.75rem;color:var(--fg);margin:6px 0 0}
.recommendation span{color:var(--dim)}
.summary-toggle{margin-top:7px;padding:4px 9px;border:0;background:transparent;color:var(--accent);cursor:pointer}
.acts{display:flex;justify-content:space-between;gap:6px;margin-top:8px;flex-wrap:wrap;
  border-top:1px solid var(--line);padding-top:8px}
.acts-primary,.acts-votes,.more-actions-buttons{display:flex;gap:5px;flex-wrap:wrap}
.more-actions{margin-top:7px;color:var(--dim);font-size:.75rem}
.more-actions summary{cursor:pointer;width:max-content}
.more-actions-buttons{margin-top:6px}
```

保留 `.act.deepread.on`、`.act.content.on`、`.act.star.on` 等狀態色。把 `site/index.html` 的 assets 更新為：

```html
<link rel="stylesheet" href="style.css?v=20260715d">
<script src="app.js?v=20260715d"></script>
```

- [ ] **Step 6: 執行 Task 3 tests 並確認 GREEN**

Run:

```powershell
node --test tests/test_site.js
```

Expected: 全部 PASS，包含既有 `whyEntries`、PRPM、upload context 與 pending-op tests。

- [ ] **Step 7: Commit Task 3**

```powershell
git add -- tests/test_site.js site/app.js site/style.css site/index.html
git diff --cached --check
git commit -m "feat(site): simplify mobile paper cards"
```

---

### Task 4: 完整測試與桌面／手機實際頁面驗證

**Files:**
- Verify only: `site/`
- Verify only: `tests/`

**Interfaces:**
- Consumes: Tasks 1–3 的完整 Round 4 UI。
- Produces: 測試證據與待 Ting 確認的本機實作；不部署、不 push、不更新 NAS。

- [ ] **Step 1: 執行完整 Node 與 Python tests**

Run:

```powershell
node --test tests/test_worker.js tests/test_site.js
python -X utf8 -m pytest -q
```

Expected: Node tests 0 fail；Python tests 143 或更多，0 fail。

- [ ] **Step 2: 執行 syntax 與 diff checks**

Run:

```powershell
node --check site/app.js
node --check site/_worker.js
git diff --check
git status --short
```

Expected: syntax checks 與 `git diff --check` exit 0；`git status` 只包含已知未追蹤 `.claude/`，或沒有輸出。

- [ ] **Step 3: 啟動本機 server，執行 Playwright desktop/mobile QA**

Run from repository root:

```powershell
$python = (Get-Command python).Source
$server = Start-Process -FilePath $python `
  -ArgumentList '-m','http.server','8765','--directory','site' `
  -WindowStyle Hidden -PassThru
try {
@'
const { chromium } = require('C:/Users/s3102/.agents/skills/cards/node_modules/playwright-core');
(async () => {
  const browser = await chromium.launch({
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    headless: true,
  });
  for(const config of [
    {name:'desktop', width:1440, height:900, expectedTab:'unseen'},
    {name:'mobile', width:390, height:844, expectedTab:'weekly', isMobile:true},
  ]){
    const context = await browser.newContext({
      viewport:{width:config.width, height:config.height},
      isMobile:Boolean(config.isMobile), locale:'zh-TW',
    });
    const page = await context.newPage();
    const errors = [];
    page.on('console', message => { if(message.type()==='error') errors.push(message.text()); });
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:8765', {waitUntil:'networkidle'});
    await page.waitForFunction(() => document.querySelectorAll('.card').length > 0);
    const result = await page.evaluate(() => ({
      activeTab: document.querySelector('.tab.on')?.dataset.tab,
      cards: document.querySelectorAll('.card').length,
      scoreInHeader: Boolean(document.querySelector('.c-head > .score')),
      sourceLink: Boolean(document.querySelector('.c-title-link[target="_blank"]')),
      summaryButton: Boolean(document.querySelector('.summary-toggle[aria-expanded][aria-controls]')),
      primaryUpload: Boolean(document.querySelector('.acts-primary .upload')),
      moreActions: Boolean(document.querySelector('.more-actions .deepread') && document.querySelector('.more-actions .content')),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    }));
    if(result.activeTab !== config.expectedTab) throw new Error(config.name + ' wrong default tab');
    if(result.cards > 25) throw new Error(config.name + ' rendered more than 25 cards');
    if(!result.scoreInHeader || !result.sourceLink || !result.summaryButton || !result.primaryUpload || !result.moreActions)
      throw new Error(config.name + ' missing approved card structure');
    if(result.horizontalOverflow) throw new Error(config.name + ' horizontal overflow');
    if(errors.length) throw new Error(config.name + ' console errors: ' + errors.join(' | '));
    console.log(JSON.stringify({name:config.name, ...result}));
    await context.close();
  }
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
'@ | node -
} finally {
  Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}
```

Expected: desktop 與 mobile 各輸出一行 JSON；desktop active tab 是 `unseen`、mobile 是 `weekly`；卡片數不超過 25；所有結構 checks 為 `true`；無 overflow 或 console error。

- [ ] **Step 4: 檢查 branch history 與停止點**

Run:

```powershell
git log --oneline main..HEAD
git status --short
```

Expected: branch 依序包含設計文件、Task 1、Task 2、Task 3 commits；不包含 deploy、NAS 或 D1 操作。到此停止並向 Ting 回報本機實作與測試結果，等待下一次確認。
