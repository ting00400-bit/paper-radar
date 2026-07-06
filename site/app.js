/* 論文學習雷達 — 前端 */
// 注：前端 fetch 的 papers.json 由 run.sh 從產生的 papers.json 複製覆蓋。
//     repo 內附 papers.sample.json 為合成範例（clone 後想直接看畫面可改名/複製成 papers.json）。
const LS_ACT = 'pr_actions_v1';     // 各篇動作 {item_id:{vote,star,zotero,deepread}}
const LS_TOPIC = 'pr_topics_v1';    // 主題開關 {group:bool}
const LS_FILT = 'pr_filters_v1';    // {badge,sort,search,tab}
const API = '/api/action';          // Worker(step 4)；失敗則純本地

let DATA = null;
let actions = load(LS_ACT, {});
let topics = load(LS_TOPIC, null);
let filt = load(LS_FILT, {badge:'all', sort:'score', search:'', tab:'unseen'});
// 一次性遷移：舊版用 showSeen checkbox，映射到 tab 後不再讀寫 showSeen
if(filt.tab === undefined){ filt.tab = filt.showSeen ? 'seen' : 'unseen'; delete filt.showSeen; }
let pendingSync = 0;                 // synced=0 且有實際動作的筆數（給同步 banner）
const seenAtLoad = new Set();        // 開頁當下已 seen 的 item_id → 只有「載入前就已看」的才隱藏；本 session 新點的留著（可再點第二顆鈕）
let headCollapsed = load('pr_headcollapse_v1', window.innerWidth < 600);
const hideTimers = new Map();        // item_id → 動作後延遲淡出的計時器（render 時全部重置）

function load(k,d){ try{return JSON.parse(localStorage.getItem(k))??d}catch{return d} }

// 全站圖示（lucide 風格 24x24 線條；currentColor 跟著文字色走，emoji 跨平台長相不一的問題掰掰）
const ICONS = {
  check:     '<path d="M20 6 9 17l-5-5"/>',
  x:         '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  eye:       '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z"/><circle cx="12" cy="12" r="3"/>',
  microscope:'<path d="M6 18h8"/><path d="M3 22h18"/><path d="M14 22a7 7 0 1 0 0-14h-1"/><path d="M9 14h2"/><path d="M9 12a2 2 0 0 1-2-2V6h6v4a2 2 0 0 1-2 2Z"/><path d="M12 6V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3"/>',
  book:      '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  thumbup:   '<path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/>',
  thumbdown: '<path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/>',
  meh:       '<circle cx="12" cy="12" r="10"/><line x1="8" x2="16" y1="15" y2="15"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/>',
  paperclip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  copy:      '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  sparkles:  '<path d="M12 3l1.9 5.7a2 2 0 0 0 1.4 1.4L21 12l-5.7 1.9a2 2 0 0 0-1.4 1.4L12 21l-1.9-5.7a2 2 0 0 0-1.4-1.4L3 12l5.7-1.9a2 2 0 0 0 1.4-1.4Z"/>',
  unlock:    '<rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/>',
  building:  '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>',
  search:    '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  file:      '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  hourglass: '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/><path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>',
  chevright: '<path d="m9 18 6-6-6-6"/>',
  chevdown:  '<path d="m6 9 6 6 6-6"/>',
  pen:       '<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.375 2.625a2.121 2.121 0 1 1 3 3L12 15l-4 1 1-4Z"/>',
};
function ic(name){
  return `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`;
}

// 從 D1 載入動作狀態（跨瀏覽器真實來源；失敗則沿用 localStorage）
async function loadActionsFromServer(){
  try{
    const r = await fetch('/api/state?_=' + Date.now());
    if(!r.ok) return;
    const j = await r.json();
    const map = {};
    let pend = 0;
    for(const a of (j.actions||[])){
      const e = {};
      if(a.vote) e.vote = a.vote;
      if(a.seen){ e.seen = true; seenAtLoad.add(a.item_id); }
      if(a.star) e.star = true;           // 📝 整理筆記請求（沿用舊 star 欄）
      if(a.deepread) e.deepread = true;   // 🔬 品質（沿用 deepread 欄）
      if(a.content) e.content = true;      // 📚 內容
      if(a.pdf_key) e.pdf_key = a.pdf_key; // 📎 已上傳全文 R2 key
      if(a.updated) e.updated = a.updated;   // 最後互動時間（已看 tab「看過時間」排序用）
      if(Object.keys(e).length) map[a.item_id] = e;
      // 等待同步＝未 synced 且有實際動作（純 seen 不算）
      const actionable = a.vote || a.deepread || a.content || a.star || a.zotero || a.pdf_key;
      if(!a.synced && actionable) pend++;
    }
    actions = map;
    pendingSync = pend;
    save(LS_ACT, actions);
  }catch(e){ /* keep localStorage */ }
}
function save(k,v){ localStorage.setItem(k, JSON.stringify(v)); }

// 今天的日期（本地時區，非 UTC，避免半夜跨日算錯）
function todayLocalStr(){
  const d = new Date();
  const tz = d.getTimezoneOffset()*60000;
  return new Date(d - tz).toISOString().slice(0,10);
}

async function init(){
  const r = await fetch('papers.json?_=' + Date.now());
  DATA = await r.json();
  if(topics===null){ // 首次：用 config default_on
    topics = {};
    for(const [k,v] of Object.entries(DATA.topic_groups)) topics[k] = v.default_on;
    save(LS_TOPIC, topics);
  }
  document.getElementById('meta').textContent =
    `更新 ${DATA.updated}｜${DATA.counts.exported} 篇`;
  await loadActionsFromServer();   // D1 = 跨瀏覽器真實來源
  // seenAtLoad 補種：離線 / D1 失敗時也能用 localStorage 的 seen 來隱藏
  for(const [id,a] of Object.entries(actions)) if(a && a.seen) seenAtLoad.add(id);
  buildTopics();
  buildSyncBanner();
  buildVisitBanner();
  bindFilters();
  bindTabs();
  syncSortOptions();
  bindUpload();
  bindHeadToggle();
  applyHeadCollapse();
  render();
}

// 等待同步 banner：提醒回 PC 喊「論文同步」（站在 CF Access 後，無法從網頁觸發）
function buildSyncBanner(){
  const el = document.getElementById('syncBanner');
  if(!el) return;
  if(pendingSync > 0){
    el.innerHTML = `${ic('hourglass')} 目前 ${pendingSync} 篇等待同步 — 回 PC 對 Claude 說「論文同步」`;
    el.classList.remove('hidden');
  } else {
    el.classList.add('hidden');
  }
}

function bindHeadToggle(){
  const btn = document.getElementById('headToggle');
  if(!btn) return;
  btn.onclick = () => {
    headCollapsed = !headCollapsed;
    save('pr_headcollapse_v1', headCollapsed);
    applyHeadCollapse();
  };
}
function applyHeadCollapse(){
  const ex = document.getElementById('headExtra');
  const btn = document.getElementById('headToggle');
  if(!ex) return;
  ex.classList.toggle('hidden', headCollapsed);
  if(btn){
    btn.classList.toggle('on', !headCollapsed);
    btn.innerHTML = ic(headCollapsed ? 'chevright' : 'chevdown');   // ▶ 收合 / ▼ 展開
  }
}

function bindUpload(){
  const btn = document.getElementById('upBtn');
  if(!btn) return;
  btn.onclick = async () => {
    const f = document.getElementById('upFile').files[0];
    const title = document.getElementById('upTitle').value.trim();
    const doi = document.getElementById('upDoi').value.trim();
    const content = document.getElementById('upContent').checked ? '1' : '0';
    const quality = document.getElementById('upQuality').checked ? '1' : '0';
    const msg = document.getElementById('upMsg');
    if(!f){ msg.textContent = '請先選 PDF'; return; }
    if(f.type !== 'application/pdf'){ msg.textContent = '只接受 PDF'; return; }
    msg.textContent = '上傳中…';
    const qs = new URLSearchParams({ title, doi, content, deepread: quality });
    if(doi) qs.set('item_id', 'doi:' + doi.toLowerCase());
    try{
      const r = await fetch('/api/upload?' + qs.toString(), {
        method:'POST', headers:{'Content-Type':'application/pdf'}, body: f });
      const j = await r.json();
      msg.innerHTML = r.ok ? `${ic('check')} 已上傳，說「論文同步」我就處理` : `${ic('x')} ${esc(j.error||'失敗')}`;
      if(r.ok){ document.getElementById('upFile').value=''; document.getElementById('upTitle').value=''; document.getElementById('upDoi').value=''; }
    }catch(e){ msg.innerHTML = `${ic('x')} 上傳失敗`; }
  };
}

function buildTopics(){
  const box = document.getElementById('topics');
  box.innerHTML = '';
  for(const [k,v] of Object.entries(DATA.topic_groups)){
    const b = document.createElement('div');
    b.className = 'topic' + (topics[k] ? ' on' : '');
    b.textContent = v.label;
    b.onclick = () => { topics[k]=!topics[k]; save(LS_TOPIC,topics); b.classList.toggle('on'); render(); };
    box.appendChild(b);
  }
}

function buildVisitBanner(){
  const today = todayLocalStr();
  const n = DATA.papers.filter(p => p.first_seen === today && passTopic(p)).length;
  const el = document.getElementById('visitBanner');
  if(!n){ el.classList.add('hidden'); return; }
  const labelOff = `${ic('sparkles')} 今天(${today})新增 ${n} 篇 — 點此只看這些`;
  const labelOn  = `${ic('sparkles')} 只看今天新增 ${n} 篇中 — 點此恢復全部`;
  el.innerHTML = filt.badge==='visit' ? labelOn : labelOff;
  el.classList.remove('hidden');
  el.onclick = () => {
    // toggle：已在 visit 篩選 → 恢復 all；否則進 visit
    filt.badge = (filt.badge==='visit') ? 'all' : 'visit';
    save(LS_FILT,filt); syncBadgeUI();
    el.innerHTML = filt.badge==='visit' ? labelOn : labelOff;
    render();
  };
}

function bindFilters(){
  const s = document.getElementById('search');
  s.value = filt.search || '';
  s.oninput = () => { filt.search=s.value; save(LS_FILT,filt); render(); };
  const sort = document.getElementById('sort');
  sort.value = filt.sort;
  sort.onchange = () => { filt.sort=sort.value; save(LS_FILT,filt); render(); };
  document.querySelectorAll('#badgeFilter .chip').forEach(c => {
    c.onclick = () => { filt.badge=c.dataset.badge; save(LS_FILT,filt); syncBadgeUI(); render(); };
  });
  syncBadgeUI();
}
function syncBadgeUI(){
  document.querySelectorAll('#badgeFilter .chip').forEach(c =>
    c.dataset.on = (c.dataset.badge===filt.badge) ? '1' : '0');
}

function bindTabs(){
  document.querySelectorAll('#tabs .tab').forEach(t => {
    t.onclick = () => { filt.tab = t.dataset.tab; save(LS_FILT, filt); syncSortOptions(); render(); };
  });
}
// 筆數以「主題+badge+搜尋過濾後」為分母（與 footer 同基準），兩 tab 各自計數
function syncTabUI(unseenN, seenN){
  document.querySelectorAll('#tabs .tab').forEach(t => {
    t.classList.toggle('on', t.dataset.tab === filt.tab);
    t.textContent = t.dataset.tab === 'seen' ? `已看 (${seenN})` : `未看 (${unseenN})`;
  });
}

// 「看過時間」排序只在已看 tab 有意義：動態加/移 option（option[hidden] 在 iOS Safari 不可靠）
function syncSortOptions(){
  const sort = document.getElementById('sort');
  let opt = sort.querySelector('option[value="seenat"]');
  if(filt.tab === 'seen'){
    if(!opt){
      opt = document.createElement('option');
      opt.value = 'seenat'; opt.textContent = '看過時間 新→舊';
      sort.appendChild(opt);
    }
  } else {
    if(opt) opt.remove();
    if(filt.sort === 'seenat'){ filt.sort = 'score'; save(LS_FILT, filt); }
  }
  sort.value = filt.sort;
}

function passTopic(p){ return topics[p.group]; }

function passBadge(p){
  const a = actions[p.item_id] || {};
  switch(filt.badge){
    case 'oa': return !!p.oa_pdf_url;   // 只算「真的抓得到 OA PDF」
    case 'oanew': return !!p.oaNew;
    case 'inst': return p.inst_subscribed===1;
    case 'new': return p.isNew;
    case 'visit': return p.first_seen === todayLocalStr();
    default: return true;
  }
}

function passSearch(p){
  const q = (filt.search||'').trim().toLowerCase();
  if(!q) return true;
  return (p.title+' '+p.authors+' '+p.source_name).toLowerCase().includes(q);
}

// 分頁分流：已看 tab 只留 seen；未看 tab 留未 seen 或「本 session 剛按、還在淡出緩衝期」的
function passSeen(p){
  const a = actions[p.item_id] || {};
  if(filt.tab === 'seen') return !!a.seen;
  if(!a.seen) return true;
  return !seenAtLoad.has(p.item_id);
}

function render(){
  for(const t of hideTimers.values()) clearTimeout(t);
  hideTimers.clear();
  const list = document.getElementById('list');
  const base = DATA.papers.filter(p => passTopic(p) && passBadge(p) && passSearch(p));
  let seenN = 0;
  for(const p of base) if((actions[p.item_id]||{}).seen) seenN++;
  syncTabUI(base.length - seenN, seenN);
  const ps = base.filter(passSeen);
  const upd = p => (actions[p.item_id]||{}).updated || '';
  ps.sort(filt.sort==='date'
    ? (a,b)=> (b.pub_date||b.first_seen).localeCompare(a.pub_date||a.first_seen)
    : filt.sort==='seenat'
    ? (a,b)=> upd(b).localeCompare(upd(a)) || b.score - a.score
    : (a,b)=> b.score - a.score);
  list.innerHTML = '';
  for(const p of ps) list.appendChild(card(p));
  document.getElementById('count').textContent = `顯示 ${ps.length} 篇`;
}

function card(p){
  const a = actions[p.item_id] || {};
  const el = document.createElement('div');
  el.className = 'card' + (a.vote==='down'?' down':'') + (a.seen?' seen':'');

  const sc = document.createElement('div');
  sc.className = 'score' + (p.score>=5?' hi':p.score>=3?' mid':'');
  sc.textContent = p.score;

  const body = document.createElement('div'); body.style.flex='1';
  const title = `<div class="c-title">${esc(p.title)}</div>
    <div class="c-src">${esc(p.source_name)}${p.pub_date?' · '+p.pub_date:''}${p.authors?' · '+esc(p.authors.split(',').slice(0,3).join(','))+(p.authors.split(',').length>3?' et al.':''):''}</div>`;

  // 徽章
  let badges = '';
  if(p.isNew) badges += `<span class="badge b-new">${ic('sparkles')} NEW</span>`;
  if(p.oa_pdf_url)   // 只在真的抓得到 OA PDF 時掛標；標成 OA 卻下載不到的不掛假標
    badges += `<a class="badge ${p.oaNew?'b-oanew':'b-oa'}" href="${p.oa_pdf_url}" target="_blank">${ic('unlock')} ${p.oaNew?'新開放':'OA PDF'}</a>`;
  if(p.inst_subscribed===1)
    badges += `<a class="badge b-tz" href="${p.sfx_url}" target="_blank">${ic('building')} 機構訂閱${p.inst_platforms?' '+esc(p.inst_platforms):''}</a>`;
  else if(p.sfx_url)
    badges += `<a class="badge b-tag" href="${p.sfx_url}" target="_blank">${ic('search')} SFX</a>`;
  if(a.pdf_key)
    badges += `<a class="badge b-tag" href="/api/pdf?key=${encodeURIComponent(a.pdf_key)}" target="_blank">${ic('file')} 查看PDF</a>`;
  for(const t of (p.tags||[]).filter(t=>!/^(neg|penalty|design|author):/.test(t)).slice(0,4))
    badges += `<span class="badge b-tag">${esc(t)}</span>`;

  body.innerHTML = title + `<div class="badges">${badges}</div>` +
    (p.abstract?`<div class="abs" id="abs-${p.item_id}">${formatAbs(p.abstract)}</div>`:'');

  // 📋 複製鈕：標題旁複製標題（貼 Google Scholar 搜全文）、摘要內複製摘要（貼 GPT 翻譯）
  body.querySelector('.c-title').appendChild(copyBtn(()=>p.title, '複製標題'));
  const absEl = body.querySelector('.abs');
  if(absEl) absEl.prepend(copyBtn(()=>p.abstract, '複製摘要'));

  // 動作鈕：已看(左) | 品質 | 內容 | 筆記 | 讚/普/爛 | 上傳PDF
  // 品質/內容 任一顆 = /paper-sync 跑共用前置(DOI核對+Zotero+抓全文)後分流；按任一鈕都隱含標 seen
  const acts = document.createElement('div'); acts.className='acts';
  acts.appendChild(actBtn(ic('eye')+' 已看','seen',!!a.seen,()=>toggle(p,'seen')));
  acts.appendChild(actBtn(ic('microscope')+' 品質','deepread',!!a.deepread,()=>toggleAct(p,'deepread')));
  acts.appendChild(actBtn(ic('book')+' 內容','content',!!a.content,()=>toggleAct(p,'content')));
  acts.appendChild(actBtn(ic('pen')+' 筆記','star',!!a.star,()=>toggleAct(p,'star'),'整理筆記：下次論文同步時產出 Obsidian 筆記'));
  acts.appendChild(actBtn(ic('thumbup'),'up vote',a.vote==='up',()=>setVote(p,'up'),'讚'));
  acts.appendChild(actBtn(ic('meh'),'neutral vote',a.vote==='neutral',()=>setVote(p,'neutral'),'普通'));
  acts.appendChild(actBtn(ic('thumbdown'),'down vote',a.vote==='down',()=>setVote(p,'down'),'不喜歡'));
  const upBtn = document.createElement('button');
  upBtn.className = 'act upload'; upBtn.innerHTML = a.pdf_key ? ic('check')+' 已上傳' : ic('paperclip')+' 上傳PDF';
  upBtn.onclick = () => uploadForPaper(p, upBtn);
  acts.appendChild(upBtn);
  body.appendChild(acts);

  body.querySelector('.c-title').onclick = () => {
    const ab = document.getElementById('abs-'+p.item_id);
    if(ab) ab.classList.toggle('show');
  };

  el.appendChild(sc); el.appendChild(body);

  // 本 session 剛按過動作的卡：反灰停留 2.5 秒再淡出收合。
  // 期間可補按第二顆鈕（每次 render 重新計時）；淡出後視同「載入前已看」，切「已看」tab 找得回來。
  if(filt.tab === 'unseen' && a.seen && !seenAtLoad.has(p.item_id)){
    hideTimers.set(p.item_id, setTimeout(() => {
      el.style.maxHeight = el.scrollHeight + 'px';
      requestAnimationFrame(() => { el.classList.add('fadeout'); el.style.maxHeight = '0'; });
      // 內層也登記進 hideTimers：淡出中若別的操作觸發 render，這顆才清得掉
      hideTimers.set(p.item_id, setTimeout(() => { seenAtLoad.add(p.item_id); render(); }, 400));
    }, 2500));
  }
  return el;
}

// 複製到剪貼簿的小鈕；點了不冒泡（避免觸發標題的展開摘要）
function copyBtn(getText, tip){
  const b = document.createElement('button');
  b.className = 'copy';
  b.innerHTML = ic('copy');
  b.title = tip; b.setAttribute('aria-label', tip);
  b.onclick = (e) => {
    e.stopPropagation();
    navigator.clipboard.writeText(getText() || '').then(
      () => { b.innerHTML = ic('check'); },
      () => { b.innerHTML = ic('x'); });
    setTimeout(() => { b.innerHTML = ic('copy'); }, 1200);
  };
  return b;
}

function actBtn(label, cls, on, fn, tip){
  const b = document.createElement('button');
  b.className = 'act ' + cls.split(' ')[0] + (on?' on':'');
  b.innerHTML = label;
  if(tip){ b.title = tip; b.setAttribute('aria-label', tip); }
  b.onclick = () => { fn(); render(); };
  return b;
}

function setVote(p, v){
  const a = actions[p.item_id] || (actions[p.item_id]={});
  a.vote = (a.vote===v) ? null : v;
  persist(p, 'vote', a.vote);
  markSeen(p);   // 投票也算看過
}
function toggle(p, key){
  const a = actions[p.item_id] || (actions[p.item_id]={});
  a[key] = !a[key];
  if(key==='seen' && !a[key]) seenAtLoad.delete(p.item_id);   // 取消已看→回未看 tab 後重按仍有 2.5 秒緩衝
  persist(p, key, a[key]);
}
// 標 seen（不重複送）。本 session 內 passSeen 不隱藏，下次重整才消失
function markSeen(p){
  const a = actions[p.item_id] || (actions[p.item_id]={});
  if(!a.seen){ a.seen = true; persist(p, 'seen', true); }
}
// 🔬品質 / 📚內容：toggle 後一律標 seen
function toggleAct(p, key){ toggle(p, key); markSeen(p); }
function persist(p, key, val){
  // 本地也 bump updated（與 Worker 同格式）：剛按的卡在「看過時間」排序才會置頂，不用等重整回填
  const a = actions[p.item_id]; if(a) a.updated = new Date().toISOString();
  save(LS_ACT, actions);
  // best-effort 推 Worker(step 4)；失敗純本地保留，/paper-sync 之後可補
  fetch(API, {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({item_id:p.item_id, doi:p.doi, title:p.title, key, val})}).catch(()=>{});
}
// per-card 全文上傳（綁該篇 item_id；給機構沒訂、非 OA、你手上有 PDF 的論文）
function uploadForPaper(p, btn){
  const inp = document.createElement('input');
  inp.type = 'file'; inp.accept = 'application/pdf';
  inp.onchange = async () => {
    const f = inp.files[0]; if(!f) return;
    if(f.type !== 'application/pdf'){ btn.textContent = '只接受PDF'; return; }
    btn.innerHTML = ic('hourglass')+' 上傳中';
    const qs = new URLSearchParams({ item_id: p.item_id, doi: p.doi || '', title: p.title || '' });
    try{
      const r = await fetch('/api/upload?' + qs.toString(),
        { method:'POST', headers:{'Content-Type':'application/pdf'}, body: f });
      const j = await r.json();
      if(r.ok){
        const a = actions[p.item_id] || (actions[p.item_id]={});
        a.pdf_key = j.key; save(LS_ACT, actions);
        render();
      } else {
        btn.innerHTML = `${ic('x')} ${esc(j.error||'失敗')}`;
      }
    }catch(e){ btn.innerHTML = `${ic('x')} 失敗`; }
  };
  inp.click();
}

function esc(s){ return (s||'').replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

// 摘要排版：結構式摘要（BACKGROUND:/Methods:/…）切段＋粗體標籤；一般摘要維持單段
const ABS_SEC_RE = /\b(BACKGROUND|INTRODUCTION|OBJECTIVES?|AIMS?|PURPOSE|MATERIALS? AND METHODS?|METHODS?|METHODOLOGY|RESULTS?|FINDINGS|DISCUSSION|CONCLUSIONS?|CLINICAL (?:RELEVANCE|SIGNIFICANCE|IMPLICATIONS?)|TRIAL REGISTRATION|REGISTRATION|FUNDING)\s*:/gi;
function fmtAbsLabel(s){
  return s.toLowerCase().replace(/(^|\s)(\w)/g, (m,sp,c)=>sp+c.toUpperCase()).replace(/ And /g,' and ');
}
// 逐句切割：句號/問號/驚嘆號＋空白＋大寫（或數字/括號）開頭才算斷句；
// 小數點(0.05)後面沒空白不會切；常見縮寫(e.g./i.e./vs./Fig.)切到就併回前一句
function sentSplit(t){
  const raw = t.replace(/([.!?])\s+(?=[A-Z0-9("“])/g, '$1\u0000').split('\u0000');
  const ABBR = /\b(?:e\.g|i\.e|vs|cf|ca|approx|Figs?|resp)\.$/;
  const out = [];
  for(const s of raw){
    if(out.length && ABBR.test(out[out.length-1])) out[out.length-1] += ' ' + s;
    else out.push(s);
  }
  return out;
}
function formatAbs(text){
  const ms = [...text.matchAll(ABS_SEC_RE)];
  if(ms.length < 2)   // 標記太少視為非結構式 → 逐句分段
    return sentSplit(text).map(s=>`<p>${esc(s)}</p>`).join('');
  let html = '';
  const pre = text.slice(0, ms[0].index).trim();
  if(pre) html += `<p>${esc(pre)}</p>`;
  for(let i = 0; i < ms.length; i++){
    const start = ms[i].index + ms[i][0].length;
    const end = i+1 < ms.length ? ms[i+1].index : text.length;
    html += `<p><strong>${esc(fmtAbsLabel(ms[i][1]))}:</strong> ${esc(text.slice(start, end).trim())}</p>`;
  }
  return html;
}

init();
