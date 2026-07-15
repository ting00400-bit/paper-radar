# Paper Radar Round 3 Lightweight PRPM Implementation Plan

> **For Codex:** Execute with TDD. Do not apply the production `action_log` migration until Ting explicitly confirms it in the active session.

**Goal:** Learn a transparent, deterministic preference ranking from Paper Radar actions without LLMs, embeddings, impression events, or a new service.

**Architecture:** The Worker dual-writes current state plus append-only D1 events. A read-only exporter stores an ignored local snapshot. A standard-library Python trainer atomically enriches `site/papers.json` and writes `site/profile.json`. Existing NAS scripts run the PRPM step fail-open before deployment.

**Scope lock:** No `impression` event. Release 1 events are `content_on`, `deepread_on`, `pdf_upload`, `vote_up`, `vote_mid`, `vote_down`, and explicit `seen_only` only. Current `actions` are exported as per-signal fallback for pre-migration history.

---

## Task 1: Event schema and Worker dual-write

**Files:** `migrations/2026-07-15-action-log.sql`, `schema.sql`, `docs/D1_MIGRATIONS.md`, `site/_worker.js`, `site/app.js`, `tests/test_worker.js`, `tests/test_site.js`.

1. Add failing tests for action/upload events, explicit versus implicit seen, and missing-table tolerance.
2. Add `action_log` bootstrap/migration SQL and docs with the production confirmation gate.
3. Implement best-effort append-only event writes after the current-state write succeeds.
   Give queued actions a stable unique `event_id` so HTTP retries cannot double-count training signals.
4. Pass `implicit: true` for automatic seen actions so only direct seen clicks emit `seen_only`.
5. Run Node tests to green.

## Task 2: Read-only event export

**Files:** `export_action_log.py`, `tests/test_prpm_export.py`, `.gitignore`.

1. Test successful parsing/atomic cache replacement and failed query preserving the last good cache.
2. Export `action_log` plus a safe `actions` fallback snapshot to `_prpm_cache/events.json`.
3. Keep tokens, Wrangler metadata, and errors out of the artifact.

## Task 3: Standard-library PRPM trainer

**Files:** `train_prpm.py`, `tests/test_train_prpm.py`.

1. Test positive matching features, downvotes, 90-day decay, output contract, deterministic explore exclusion for downvoted papers, fallback actions, profile safety, and invalid-input no-overwrite.
2. Extract features only from existing paper metadata.
3. Preserve old score as `kw_score`; add normalized `score`, `rank`, object-shaped `why`, and `explore`.
4. Generate a public-safe `profile.json` and atomically replace both outputs only after validation.

## Task 4: Minimal frontend PRPM display

**Files:** `site/index.html`, `site/app.js`, `site/style.css`, `tests/test_site.js`, `tests/test_worker.js`.

1. Test object/string `why` compatibility, rank-aware default ordering, explore badge, and preference summary rendering.
2. Add secondary keyword score, expandable reasons, deterministic rank sorting, explore badge, and a small optional profile panel.
3. Keep old `papers.json` fully compatible.

## Task 5: Fail-open NAS pipeline integration

**Files:** `run.sh`, `redeploy.sh`, `deploy.sh`, tests or source-contract assertions.

1. Copy keyword output to `site/papers.json` first.
2. Run exporter then trainer; on either failure, warn and deploy the untouched keyword file.
3. Ensure `profile.json` from a failed/stale run is not deployed as fresh model state.
4. Add new scripts to the legacy deploy file list.

## Task 6: Verify, review, commit, and stop

1. Run all Node/Python tests, `py_compile`, migration smoke test, and `git diff --check`.
2. Generate a local PRPM fixture and inspect ordering/profile output.
3. Obtain independent code review and fix blocking findings.
4. Commit Round 3 independently.
5. Stop before production D1 migration, merge, push, NAS pull, event export, training, or deployment.

## Task 7: After explicit confirmation only

1. Apply `action_log` migration and verify table/index.
2. Integrate to `main`, rerun tests, push, fast-forward NAS.
3. Run exporter/trainer on NAS canonical data, inspect top ranking and `profile.json`, then deploy.
4. Verify action dual-write, online PRPM fields/profile, and fail-open behavior without emitting `impression`.
