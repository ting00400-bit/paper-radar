# D1 schema migrations

The D1 `actions` table (see `schema.sql`) occasionally needs new columns as the
front-end gains features (e.g. the `content` column for the 📚 button).

## How to run a migration

Schema changes (`ALTER TABLE ...`) must be run from a machine whose Cloudflare
API token has **D1:Edit** permission. A read-only host token cannot apply them.

Run the `ALTER` directly against the remote D1 database with wrangler:

```bash
wrangler d1 execute paper-radar-db --remote \
  --command "ALTER TABLE actions ADD COLUMN content INTEGER"
```

Migrations are intended to be idempotent: if the column already exists, wrangler
returns a `duplicate column` error which you can treat as success.

Verify the column landed:

```bash
wrangler d1 execute paper-radar-db --remote --json \
  --command "PRAGMA table_info(actions)"
```

## Notes

- The initial schema is created from `schema.sql`:
  ```bash
  wrangler d1 execute paper-radar-db --remote --file=schema.sql
  ```
- `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` come from your `.env`
  (see `env.example`). Never hard-code them.

## 2026-07-15: sync status dashboard

Round 2 adds only these five nullable current-state columns:

- `sync_status`
- `pdf_status`
- `pdf_source`
- `sync_error`
- `sync_updated_at`

The note-related columns from the longer design are deliberately deferred. Do not add them in this migration.

**Production safety:** applying this migration requires Ting's explicit confirmation in the active session. The new Worker must not be deployed before all five columns exist.

Apply the statements in `migrations/2026-07-15-sync-status.sql` one at a time with `--remote --command`. If a statement reports `duplicate column name`, verify the schema and continue with the remaining columns.

Verify afterward:

```bash
wrangler d1 execute paper-radar-db --remote --json \
  --command "PRAGMA table_info(actions)"
```

Expected new names are exactly the five listed above.
