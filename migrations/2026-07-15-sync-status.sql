-- Run against production only after explicit confirmation from Ting.
-- For partially applied migrations, execute each statement separately and treat
-- "duplicate column name" as already applied after PRAGMA verification.
ALTER TABLE actions ADD COLUMN sync_status TEXT;
ALTER TABLE actions ADD COLUMN pdf_status TEXT;
ALTER TABLE actions ADD COLUMN pdf_source TEXT;
ALTER TABLE actions ADD COLUMN sync_error TEXT;
ALTER TABLE actions ADD COLUMN sync_updated_at TEXT;
