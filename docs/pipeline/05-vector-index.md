# Stage 5 — Semantic chunking & vector index

**Status:** Implemented (pgvector + PDF Continue indexing)

## Purpose

After human approval, build **searchable semantic units** — not raw PDF text
blobs — so grouping and discovery can find related objects.

Do not embed every cell by default.

## Useful chunk kinds

```text
Dataset / table description
Table classification summary
Column meaning (name + role + concept)
Indicator definitions
Approved mappings / standards concepts
```

Example chunk text:

```text
"PHC ID | identifier | Primary Health Centre"
"Male | measure | Population | category Male"
```

## Why vectors come after classification

```text
Preferred:  extract → reconstruct → understand → approve → embed
Avoid:      embed raw PDF text and hope similarity is meaningful
```

## Architecture

```text
PostgreSQL (SoT)
├── pdf_tables / datasets / metadata …
└── pgvector · semantic_embeddings  (ancillary retrieval)
```

| Concern | Owner |
|---------|--------|
| Authoritative objects | Normal Postgres tables |
| Similarity search | `semantic_embeddings` + HNSW cosine index |

## In this codebase

- Image: `pgvector/pgvector:pg16`
- Init: `backend/db/init-pgvector.sql`
- Module: `backend/core/vector_store.py`
- Health: `/api/health` reports pgvector readiness
- PDF Preview → Continue upserts `table_summary` (+ column chunks)

Embeddings are keyed by `object_type` / `object_id` / `chunk_kind` (and often
`job_id`). They never replace `pdf_tables` or catalogue rows as SoT.

## Config

```text
EMBEDDING_DIM=1536          # text-embedding-3-small width
OPENAI_API_KEY=…            # MEITY-empanelled / OpenAI-compatible embedding endpoint
```
