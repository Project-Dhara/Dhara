# Stage 11 — Access layer (Catalogue / API / MCP)

**Status:** Catalogue UI + authenticated REST live; MCP and public API productisation planned

## Purpose

Expose **only approved, authorised** data for discovery and consumption.

```text
Catalogue → API → MCP (agents)
```

## Live today

| Surface | Behaviour |
|---------|-----------|
| **Catalogue UI** | Browse published datasets / metadata |
| **REST API** | JWT-protected FastAPI routes; Swagger at `/docs` |
| **des-website** | External consumer of the same catalogue DB |

## Designed capabilities

```text
Dataset / table discovery
Semantic search (via embeddings)
API queries for approved rows
Cross-department access with authZ
AI-assisted discovery
MCP tools for agents (search_datasets, get_table, get_metadata, …)
```

## Publish step UI

The Console Publish screen may show placeholder API/MCP endpoint names for
product vision. Treat those as **design affordances** until a real MCP server
and stable public API contract ship.

## Design target

```text
                    metadata_groups / datasets
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
         Catalogue UI    Versioned REST     MCP server
                         (scoped JWT)     (tool schema)
```

Access policy should honour steward approval state — unpublished or
soft-deleted work must not appear on public surfaces.
