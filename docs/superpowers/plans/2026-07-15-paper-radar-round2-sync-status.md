# Paper Radar Round 2 Sync Status Dashboard Implementation Plan

> **For Codex:** Execute this plan with TDD. Do not run the production D1 migration until Ting explicitly confirms it in the active session.

**Goal:** Make Paper Radar's current PDF and sync state visible in a read-only in-app dashboard while keeping the existing Worker, D1, R2, and static frontend architecture.

**Scope:** Follow the approved reduced Round 2 scope from section 15: add only `sync_status`, `pdf_status`, `pdf_source`, `sync_error`, and `sync_updated_at`. Note fields remain absent from D1, return `null` from the API, and are not rendered.

**Architecture:** `paper_sync.py` writes current-state transitions to D1 through Wrangler; the Worker exposes sanitized action state joined with generated scoring fields from `papers.json`; the existing frontend adds a third read-only tab and pure rendering/filter helpers. No framework, new service, or audit-log table.

---

## Task 1: Lock the reduced D1 contract in tests and documentation

**Files:**
- Modify: `schema.sql`
- Modify: `docs/D1_MIGRATIONS.md`
- Create: `migrations/2026-07-15-sync-status.sql`
- Create: `tests/test_worker.js`

1. Add a Worker test harness that can execute `site/_worker.js` with mocked D1, R2, and static assets.
2. Add failing tests for `GET /api/sync-status` and manual PDF upload status writes.
3. Document the five-column migration and verification command, with an explicit production-confirmation warning.
4. Add the five nullable columns to the bootstrap schema and migration SQL.
5. Run `node --test tests/test_worker.js`; confirm the new route and upload tests are red before Worker implementation.

## Task 2: Implement the sanitized Worker status API

**Files:**
- Modify: `site/_worker.js`
- Test: `tests/test_worker.js`

1. Add `GET /api/sync-status` querying only rows requested for work or carrying sync state.
2. Fetch `papers.json` through `env.ASSETS`, join by `item_id` with DOI fallback, and expose scoring fields (`score`, optional `kw_score`, `rank`, `explore`, `why`).
3. Return only the approved public response shape; do not expose `pdf_key`, internal traces, tokens, or paths. Return note fields as `null` for forward compatibility.
4. On successful manual upload, set `sync_status='pending'`, `pdf_status='uploaded'`, `pdf_source='manual_upload'`, clear `sync_error`, and update `sync_updated_at` in the same D1 upsert.
5. When a work action is enabled, mark it pending; vote/seen-only changes must not create a work status.
6. Run the Worker tests to green.

## Task 3: Add tested `paper_sync.py` state transitions

**Files:**
- Modify: `paper_sync.py`
- Modify: `tests/test_paper_sync.py`

1. Add failing tests for safe status SQL generation, missing/fetch-failed PDF mapping, identity mismatch, accepted identity, and `done`.
2. Implement a small validated `update_sync_status()` helper using the existing Wrangler runner and `item_id` whitelist.
3. After each acquisition result, write:
   - PDF present: `pending` + `available` + source, clear error.
   - identity rejection: `blocked` + `identity_mismatch` + short error.
   - retryable acquisition failure: `pending` + `fetch_failed` + short error.
   - exhausted/no route: `pending` + `missing` + short error.
4. Wire CLI transitions:
   - `reject`: blocked/mismatch.
   - `accept`: pending/verified and clear error.
   - `done`: set legacy `synced=1`, `sync_status='synced'`, `pdf_status='verified'`, clear error.
5. Keep note verification outside this reduced phase.
6. Run targeted Python tests to green, then the full Python suite.

## Task 4: Add the read-only frontend dashboard

**Files:**
- Modify: `site/index.html`
- Modify: `site/style.css`
- Modify: `site/app.js`
- Modify: `tests/test_site.js`

1. Add failing pure-function tests for status labels, dashboard filters, scoring fallbacks, and readable API errors.
2. Add a third `同步狀態` tab. Load `/api/sync-status` lazily and render a compact card/table-style list.
3. Show requested work, sync/PDF badges, primary score plus optional PRPM fields, short error, and updated timestamp.
4. Add filters for all, pending, missing PDF, identity mismatch, synced, and explore. Omit note UI because note columns are deferred.
5. Preserve existing unseen/seen behavior and local pending-action indicator.
6. Run frontend tests to green and manually inspect desktop/mobile layout against a local mocked status response.

## Task 5: Verify, review, and stop at the production migration checkpoint

**Files:** all changed files above.

1. Run:
   - `node --test tests/test_worker.js tests/test_site.js`
   - `python -m pytest -q`
   - `python -m py_compile paper_sync.py`
   - `git diff --check`
2. Review the diff for schema compatibility, API sanitization, and accidental secret/generated-file inclusion.
3. Commit the completed Round 2 code independently on the feature branch.
4. Do **not** execute `wrangler d1 execute ...`, deploy the new Worker, or run the newly state-writing `paper_sync.py pending` yet.
5. Ask Ting for explicit confirmation to apply the five-column production D1 migration.

## Task 6: After explicit confirmation only — migrate, integrate, and deploy

1. Apply `migrations/2026-07-15-sync-status.sql` to production D1 with a D1:Edit-capable identity.
2. Verify `PRAGMA table_info(actions)` contains exactly the five new Round 2 fields.
3. Fast-forward the reviewed commit into `main`, rerun the full suite, push GitHub, fast-forward NAS, and redeploy from the NAS container.
4. Run `paper_sync.py pending` once to populate current status (it may write status but must not run `done`).
5. Verify `/api/sync-status` online, including the known wrong-PDF item showing blocked/mismatch if its rejection marker is available to the Windows pipeline.
6. Record deployment URL, API readback, and final commit.
