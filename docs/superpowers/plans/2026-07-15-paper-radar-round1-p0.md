# Paper Radar Round 1 P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Paper Radar actions from disappearing when `/api/action` fails, and make “最新優先” use a normalized sortable date.

**Architecture:** Keep the static HTML/CSS/JS architecture. Store each idempotent action assignment under its own localStorage key, overlay pending assignments after loading D1, and retry them on page load or the browser `online` event. Use Web Locks to serialize the same `item_id + key` across tabs. Normalize publication dates while producing `papers.json`; the browser only compares `pub_date_sort` with `first_seen` as fallback.

**Tech Stack:** Python 3 standard library, pytest, browser-native JavaScript, Node.js built-in test runner; no new dependency or framework.

## Global Constraints

- Section 15 of `100_Todo/drafts/2026-07-14_Paper-Radar網站檢視與改進建議.md` overrides older ordering.
- Do not run fetch/enrich against the Windows development database; NAS data remains canonical.
- Do not perform a D1 migration in this round.
- Preserve unrelated `.claude/` and NAS runtime changes.
- Use TDD: observe every new test fail for the intended reason before changing production code.

---

### Task 1: Normalize publication dates in the data layer

**Files:**
- Create: `tests/test_pub_dates.py`
- Modify: `fetch_and_score.py`
- Modify: `enrich.py`

**Interfaces:**
- Produces: `pub_date_sort(value: str) -> str`, returning ISO `YYYY-MM-DD` or an empty string.
- Produces: optional `pub_date_sort` on every exported paper.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from fetch_and_score import pub_date_sort

@pytest.mark.parametrize(("raw", "expected"), [
    ("2026-Jul-10", "2026-07-10"),
    ("2026-May", "2026-05-01"),
    ("2026", "2026-01-01"),
    ("2026-07-10", "2026-07-10"),
    ("", ""),
    ("not-a-date", ""),
])
def test_pub_date_sort(raw, expected):
    assert pub_date_sort(raw) == expected
```

- [ ] **Step 2: Run the test and confirm RED**

Run: `python -m pytest tests/test_pub_dates.py -q`

Expected: collection fails because `pub_date_sort` does not exist.

- [ ] **Step 3: Add the minimal normalizer**

```python
MONTHS = {name: f"{month:02d}" for month, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
)}

def pub_date_sort(value):
    match = re.fullmatch(r"(\d{4})(?:-([A-Za-z]{3}|\d{2})(?:-(\d{1,2}))?)?", (value or "").strip())
    if not match:
        return ""
    year, month, day = match.groups()
    month = MONTHS.get((month or "").title(), month or "01")
    try:
        return date(int(year), int(month), int(day or "1")).isoformat()
    except ValueError:
        return ""
```

Set `d["pub_date_sort"] = pub_date_sort(d["pub_date"])` in both JSON export paths. `enrich.py` imports the helper from `fetch_and_score.py` rather than duplicating it.

- [ ] **Step 4: Run focused and full Python tests**

Run: `python -m pytest tests/test_pub_dates.py -q`

Expected: `6 passed`.

Run: `python -m pytest -q`

Expected: all tests pass.

### Task 2: Add an idempotent pending action queue

**Files:**
- Create: `tests/test_site.js`
- Modify: `site/app.js`
- Modify: `site/index.html`

**Interfaces:**
- Storage prefix: `pr_pending_op_v1:`; each `item_id + "\u0000" + key` has its own encoded key so tabs cannot overwrite unrelated operations.
- Queue values are the exact `/api/action` JSON payload plus `updated`.
- `persist(paper, key, value)` returns the send Promise; existing click handlers may ignore it.
- `retryPendingOps()` retries current queue entries and removes only the exact version that succeeded; Web Locks serialize the same key across tabs when available.

- [ ] **Step 1: Write failing Node tests using `node:test` and a VM-loaded `site/app.js`**

The harness must remove the trailing `init();`, provide in-memory `localStorage`, `window`, and `document` stubs, then expose the lexical functions by appending:

```javascript
globalThis.TEST_API = {
  loadActionsFromServer, persist, retryPendingOps,
  pending: () => pendingOps,
  currentActions: () => actions,
  dateValue
};
```

Tests:

```javascript
test('HTTP 500 keeps one pending operation and retry clears it', async () => {
  // First fetch returns {ok:false}; second returns {ok:true}.
  // Assert pending count is 1 after persist and 0 after retry.
});

test('D1 load overlays newer pending values instead of discarding them', async () => {
  // Server says content=0; local pending says content=true.
  // Assert currentActions()[id].content === true.
});

test('the same item and key keep only the latest assignment', async () => {
  // Persist true then false while requests remain unresolved.
  // Assert one queue entry whose val is false.
});

test('initial state load finishes before online retry can clear its overlay', async () => {
  // The online listener must not exist until the D1 snapshot is merged and pending ops retried.
});

test('two tabs keep different keys and serialize the same key', async () => {
  // Shared localStorage retains both keys; a shared Web Lock leaves the latest value last in D1.
});

test('dateValue prefers pub_date_sort and falls back to first_seen', () => {
  assert.equal(api.dateValue({pub_date_sort:'2026-07-01', first_seen:'2026-01-01'}), '2026-07-01');
  assert.equal(api.dateValue({first_seen:'2026-01-01'}), '2026-01-01');
});
```

- [ ] **Step 2: Run the tests and confirm RED**

Run: `node --test tests/test_site.js`

Expected: failure because `pendingOps`, `retryPendingOps`, and `dateValue` do not exist.

- [ ] **Step 3: Implement the minimum queue and merge behavior in `site/app.js`**

```javascript
const PENDING_PREFIX = 'pr_pending_op_v1:';
function opId(op){ return `${op.item_id}\u0000${op.key}`; }
function pendingStorageKey(id){ return PENDING_PREFIX + encodeURIComponent(id); }

function loadPendingOps(){
  const ops = {};
  for(let i=0; i<localStorage.length; i++){
    const key = localStorage.key(i);
    if(!key?.startsWith(PENDING_PREFIX)) continue;
    const op = JSON.parse(localStorage.getItem(key));
    if(op?.item_id && op?.key) ops[opId(op)] = op;
  }
  return ops;
}

let pendingOps = loadPendingOps();

function updateSyncStatus(){
  const el = document.getElementById('syncStatus');
  if(!el) return;
  const n = Object.keys(pendingOps).length;
  el.textContent = n ? `尚有 ${n} 筆未同步` : '';
  el.classList.toggle('hidden', !n);
}

function queueOp(op){
  localStorage.setItem(pendingStorageKey(opId(op)), JSON.stringify(op));
  pendingOps = loadPendingOps();
  updateSyncStatus();
}

const inFlight = {};
async function sendLoop(id){
  while(true){
      const op = readPending(id);
      if(!op) break;
      let response;
      try{
        response = await fetch(API, {
          method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(op)
        });
      }catch{
        return false;
      }
      if(!response.ok) return false;
      if(JSON.stringify(readPending(id)) === JSON.stringify(op))
        localStorage.removeItem(pendingStorageKey(id));
      pendingOps = loadPendingOps();
      updateSyncStatus();
  }
  return true;
}

function sendQueued(id){
  if(inFlight[id]) return inFlight[id];
  const run = () => sendLoop(id);
  inFlight[id] = (navigator.locks?.request
    ? navigator.locks.request(`paper-radar-action:${id}`, run)
    : run()).finally(() => { delete inFlight[id]; });
  return inFlight[id];
}

async function retryPendingOps(){
  pendingOps = loadPendingOps();
  await Promise.all(Object.keys(pendingOps).map(sendQueued));
}

async function syncActionsOnLoad(){
  await loadActionsFromServer();
  await retryPendingOps();
  window.addEventListener('online', retryPendingOps);
}
```

`persist` must enqueue before calling `sendQueued(opId(op))`. The per-key lock prevents an older request from arriving after and overwriting a newer assignment, even across tabs. `loadActionsFromServer` must build the D1 map, then apply every pending assignment and keep the maximum `updated` timestamp. Register online/storage listeners only after the initial D1 snapshot and retry sequence finishes.

Add this header element:

```html
<span id="syncStatus" class="meta sync-status hidden"></span>
```

Use this comparator helper:

```javascript
const dateValue = p => p.pub_date_sort || p.first_seen || '';
```

- [ ] **Step 4: Run focused tests and full regression tests**

Run: `node --test tests/test_site.js`

Expected: all Node tests pass.

Run: `python -m pytest -q`

Expected: all Python tests pass.

### Task 3: Verify and commit Round 1

**Files:**
- Modify only files listed in Tasks 1–2 and this plan.

- [ ] **Step 1: Run final checks**

Run: `node --test tests/test_site.js`

Run: `python -m pytest -q`

Run: `git diff --check`

Expected: all commands exit 0 with no warnings.

- [ ] **Step 2: Inspect scope**

Run: `git status --short` and `git diff --stat`.

Expected: no unrelated files.

- [ ] **Step 3: Commit**

```powershell
git add docs/superpowers/plans/2026-07-15-paper-radar-round1-p0.md tests/test_pub_dates.py tests/test_site.js fetch_and_score.py enrich.py site/app.js site/index.html
git commit -m "fix(site): preserve offline actions and sort dates reliably"
```
