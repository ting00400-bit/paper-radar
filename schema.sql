-- D1 schema for paper-radar 動作層
-- 建立：wrangler d1 execute paper-radar-db --file=schema.sql
CREATE TABLE IF NOT EXISTS actions (
  item_id   TEXT PRIMARY KEY,
  doi       TEXT,
  title     TEXT,
  vote      TEXT,           -- 'up' / 'down' / 'neutral' / NULL（訓練 interest_model）
  seen      INTEGER,        -- ✅ 已看過（按任一動作鈕都會標）；預設隱藏，純標記不觸發下游
  star      INTEGER,        -- 📝 整理筆記請求（/paper-sync 撿去產 Obsidian 筆記；舊「收藏」欄位再利用）
  zotero    INTEGER,        -- (deprecated) 舊「📥 Zotero」；Zotero 改由 /paper-sync 共用前置自動加
  deepread  INTEGER,        -- 🔬 品質評讀 → /paper-review（沿用舊欄名 deepread）
  content   INTEGER,        -- 📚 內容整理 → /paper-digest
  pdf_key   TEXT,           -- R2 內全文 PDF key（📎 上傳）
  synced    INTEGER DEFAULT 0,  -- /paper-sync 處理後設 1
  updated   TEXT,
  sync_status TEXT,         -- pending / synced / blocked / failed
  pdf_status TEXT,          -- missing / available / uploaded / verified / identity_mismatch / fetch_failed
  pdf_source TEXT,          -- cache / r2 / oa-url / paper-fetch / manual_upload
  sync_error TEXT,          -- 給狀態頁顯示的短錯誤，不放 stack trace
  sync_updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_synced ON actions(synced);

-- 上傳用量計數（worker 月配額硬擋用）
CREATE TABLE IF NOT EXISTS usage (
  month   TEXT PRIMARY KEY,   -- YYYY-MM
  uploads INTEGER DEFAULT 0,
  bytes   INTEGER DEFAULT 0
);
