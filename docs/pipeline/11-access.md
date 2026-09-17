# Stage 11 — Access layer (Catalogue / API / MCP)

**Status:** Catalogue UI + authenticated REST `/api/v1` + stdio MCP live

## Purpose

Expose **only approved, authorised** data for discovery and consumption.

```text
Catalogue → API → MCP (agents)
```

## Live today

| Surface | Behaviour |
|---------|-----------|
| **Catalogue UI** | Browse published datasets / metadata |
| **REST API (v1)** | JWT-protected query routes under `/api/v1` |
| **MCP (stdio)** | `python -m mcp_server` from `backend/` |
| **des-website** | External consumer of the same catalogue DB |

## REST (`/api/v1`)

All routes require the same Bearer JWT as the Console.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/v1` | Access API index |
| GET | `/api/v1/datasets` | Search/list (`q`, `metadata_id`, `limit`, `offset`) |
| GET | `/api/v1/datasets/{dataset_id}` | Dataset metadata |
| GET | `/api/v1/datasets/{dataset_id}/rows` | Paginated rows (`limit`, `offset`, optional `column` + `equals`/`contains`) |

Shared helpers live in `backend/catalogue/query.py` (also used by the MCP server).

Example:

```bash
TOKEN=…   # from POST /api/login
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/datasets?q=births&limit=10"
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/datasets/DS_EXAMPLE/rows?limit=50&column=State&contains=Delhi"
```

## MCP tools

From `backend/` (with `DATABASE_URL` / `.env` loaded):

```bash
cd backend && python -m mcp_server
```

| Tool | Maps to |
|------|---------|
| `search_datasets` | search/list datasets |
| `get_metadata` | one dataset card |
| `get_table` | paginated rows + optional column filter |

Cursor / MEITY-empanelled or desktop MCP client example config:

```json
{
  "mcpServers": {
    "dhara-catalogue": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "/absolute/path/to/dhara-poc/backend"
    }
  }
}
```

## Design

```text
                    metadata_groups / datasets
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         Catalogue UI    Versioned REST     MCP server
                         (scoped JWT)     (tool schema)
```

Access policy should honour steward approval state — unpublished or
soft-deleted work must not appear on public surfaces. Row filters are
equality / substring on a single JSONB key only (no free-form SQL).
