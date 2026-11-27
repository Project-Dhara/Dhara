# NCO value alias cleanup (ops-only)

**Do not** clear `nco_value_aliases` in Alembic migrations or application startup.
Desktop being cleared manually does **not** mean Web should be wiped without review.

## Before clearing Web (or any shared) aliases

1. **Export** the full table:

```sql
COPY (
  SELECT normalized_value, level, code, title, source, nco_version, updated_at
    FROM nco_value_aliases
   ORDER BY updated_at DESC NULLS LAST, normalized_value
) TO STDOUT WITH CSV HEADER;
```

Or via Settings → Classification → NCO value aliases (review in UI) and `psql` dump.

2. **Classify rows**
   - `source = steward` (or verified) — preserve unless clearly poisoned
   - `source = seed` — keep
   - unknown / auto-polluted / identity label-as-code — candidates for delete

3. **Preserve** legitimate steward-verified mappings.

4. **Delete** only bad rows (or use Settings → Clear learned (non-seed) after review).

5. **Record** deleted row counts in the ops ticket.

## Desktop one-time clear (already done for some installs)

```sql
-- After backup/export only
DELETE FROM nco_value_aliases;
SELECT COUNT(*) AS remaining FROM nco_value_aliases;
```

## Settings steward actions

- List / delete one alias
- Clear learned (non-seed) with confirmation — logs deleted count in API response `{ "deleted": N }`
