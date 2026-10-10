# Dhara backend architecture

Inspection date: 2026-10-10. Branch: `code-revamp`.

This document is the target layout and the current execution path. It replaces the earlier checklist that marked Phases 2–8 as done. Those phases created packages, models, and shims. They did not move catalogue, PDF grouping, or MCP onto shared services. See `RESIDUE_AUDIT.md` for module-by-module evidence.

Nothing in this file was verified by running the application or a database. Claims below are from reading imports and handlers. Items that need a running stack are marked **runtime**.

## Layout after modularisation (2026-10-11)

Application code lives under `backend/app/`. `backend/main.py` re-exports `app.main.app` so `uvicorn main:app` stays valid. MCP stdio is `python -m app.mcp`.

**Persistence:** App-DB access goes through SQLAlchemy (`session_scope` / `get_db` / repositories). `DISABLE_REQUEST_TIME_DDL` defaults **true**; Alembic `001` + `002` own schema (including HNSW). `app/db/psycopg.get_connection` is a pooled DBAPI bridge for leftover cursor helpers only (`init_schema` is a no-op). `pdf_store.py` re-exports `repositories/pdf_jobs`.

**HTTP:** `app/api/routes/` — catalogue is split into `catalogue_extract`, `catalogue_publish`, `catalogue_browse`, `catalogue_standards`. Domain errors use `AppError` with a global handler. Mutating routes use `require_roles(*MUTATING_ROLES)`; catalogue/access list/get pass `organisation_id`.

**MCP:** JWT by default (`MCP_HTTP_AUTH=jwt`); tools filter by organisation from the Bearer token context.

**Mega-modules:** `header_utils`, `table_confidence`, `metadata_llm`, and `pdf_grouping` are split with stable re-export facades.

Some older sections below may still describe pre-migration behavior; prefer `RESIDUE_AUDIT.md` and `REFACTOR_CHECKLIST.md` for current residue.

## Entry points

| Entry | What it loads |
|-------|----------------|
| `uvicorn main:app` from `backend/` | `backend/main.py` re-exports `app.main.app` |
| `python -m app.mcp` | stdio MCP in `app/mcp/` |
| HTTP MCP | `/mcp` and `/mcp/` on the same FastAPI app |

Docker Compose, `backend/Dockerfile`, root `start.sh`, and Render all start `uvicorn main:app`. There is no separate worker process. Extraction runs as `asyncio.to_thread` inside the API process (`app/api/routes/pdf.py`, `app/api/routes/upload.py`).

```text
backend/main.py
  └─ app.main.create_app
       ├─ app.api.router
       │    └─ app.api.routes  health, auth, kyds, llm_key, catalogue, pdf, upload, dashboard, access
       ├─ app.mcp.http_asgi
       └─ SPA /assets (if built)
```

```text
app/api/routes/pdf.py, upload.py
  └─ app/workers/extraction_jobs.py
       ├─ app/services/ingestion/service.py
       │    └─ adapters → app/services/extraction/pdf and app/services/ingestion (excel/csv)
       └─ app/db/pdf_store.py via app/db/psycopg.get_connection

app/api/routes/pdf.py persist-approved
  └─ app/db/pdf_store.py + app/services/grouping/pdf_grouping.py
       └─ app/storage/vectors.py

app/api/routes/catalogue.py
  └─ app/services/* and app/db/kyds_psycopg.py (metadata-fill read)

app/mcp tools
  └─ app/services/catalogue/query.py (no organisation filter)
```

## Target layers

| Path | Responsibility |
|------|----------------|
| `app/api/` | HTTP, validation, status codes, auth dependencies. No SQL and no workflow branching. |
| `app/core/` | Settings, password hashing, JWT, permissions, exceptions, logging. |
| `app/db/models/` | SQLAlchemy models. One schema story, aligned with Alembic. |
| `app/db/repositories/` | Queries and writes. No FastAPI types. |
| `app/services/` | Use cases. No `Request`. REST and MCP both call these. |
| `app/services/ingestion/` | Choose an adapter and produce a shared contract. |
| `app/services/classification/` | Standards, NCO match, column classification. |
| `app/services/grouping/` | Group eligible reviewed tables. |
| `app/services/catalogue/` | Metadata, publish, published reads. |
| `app/storage/` | One object-store interface (local filesystem and cloud) and the vector index. |
| `app/workers/` | Job execution. Calls services. Does not reimplement them. |
| `app/mcp/` | Tool registration and transport. Thin handlers. |

`app/schemas/` should hold Pydantic request and response models. It is empty today; routes read `request.json()` and return dicts.

### Rules

- Routes stay thin. `routes/catalogue.py` and `routes/pdf.py` still contain the workflow.
- Services must not import FastAPI. `resolve_llm_credentials` currently takes a `Request` and lives in `app/api/dependencies.py`. A service-level credential lookup should accept an already-extracted key or load the stored secret by user id inside the repository.
- REST and MCP must call the same service functions. They do not. MCP calls `catalogue.query` without the organisation argument that `/api/v1` passes.
- Repositories own SQL. Catalogue and PDF still use psycopg2 in `catalogue/` and `pdf/pdf_store.py`. SQLAlchemy is used for auth, KYDS HTTP, and LLM key HTTP.
- Storage goes through `ObjectStore`. Catalogue uploads go through the `core.gcs_utils` shim, which does reach `get_object_store()`. PDF bytes do not: they are stored in `pdf_jobs.pdf_bytes`. `LocalFileStore` is not selected by `get_object_store()`.
- Workers call the ingestion service. Grouping and publish are separate and still live under `pdf/` and `catalogue/`.
- Configuration for connections and secrets is `app/core/config.py`. Prompt text is `app/services/llm_prompts.py`.
- Do not add abstractions that only rename a call. Move a vertical slice when a service can own a real function that routes and MCP both use.
- Preserve HTTP paths and response fields unless a phase below says otherwise and tests cover the change.

### Justified deviations

- Metadata wizard stays described as part of catalogue until it moves. There is no `app/services/metadata/` package. Adding an empty one would repeat the placeholder problem.
- `users.email` remains the primary key, with a unique `users.id` UUID. JWT `sub` is that UUID. Promoting `id` to primary key is a later, explicit migration, not part of the first security fixes.
- Two spreadsheet extractors stay separate: upload (`app/services/ingestion/excel.py` + shared validation) and catalogue wizard (`app/services/ingestion/wizard/extractor.py`).
- `backend/main.py` remains the process entry so existing commands keep working.

## What is live versus placeholder

Live inside `app/`: application factory, health, auth service, KYDS HTTP, LLM key HTTP (plaintext), settings, SQLAlchemy session and models, ingestion orchestration, confidence validation, extraction job worker, GCS-or-noop object store.

Placeholder or unused wrapper: classification, grouping, catalogue, datasets, standards, and organisations **service** modules; `app/mcp/`; `app/schemas/`; `app/core/permissions.py`; `app/core/logging.py`; `app/core/exceptions.py`; `app/db/repositories/catalogue.py` (not called by publish); `app/db/repositories/pdf_jobs.py` (not called by PDF routes).

`app/services/organisations/service.py` says the app has no organisations table. That sentence is false. `organisations` and `organisation_memberships` exist, and login calls `ensure_membership`.

## Actual dataset workflow

This is the product path the UI uses. It is not the ten-step target.

1. An authenticated user uploads a PDF (`POST /api/pdf/upload`) or an Excel/SQL batch (`POST /api/catalogue/batch-extract` or `sql-extract`). `POST /api/upload` exists and is not used by the frontend.
2. PDF bytes are stored on `pdf_jobs.pdf_bytes`. Excel/CSV job inputs are not stored; the worker uses a temporary file. Optional GCS is only for later workbook exports.
3. A row is written to `pdf_jobs` and a thread is started in the API process. If the process dies mid-run, the job can remain `queued` or `running`. There is no retry loop and no second worker to resume it. Completed results do reload from Postgres.
4. PDF parsing is PyMuPDF in `app/services/extraction/pdf/`. CSV and Excel upload parsing is `app/services/ingestion/csv.py` and `excel.py`. The wizard uses a different extractor.
5. Shared validation is `app/services/extraction/pdf/confidence_validation/`, reached through shims. Contracts are `app/services/ingestion/contracts.py`.
6. Extraction asks the LLM to fill classification fields and `human_review_*` flags. The catalogue stage later matches NCO 2015 (bundled) or an uploaded standard. There is no single classification service that both stages call.
7. Preview is a UI step. `POST /api/pdf/jobs/{id}/persist-approved` requires `status == "done"` only. It does not reject tables with `human_review_needed`. The client may overlay table JSON in the body.
8. That same handler proposes groups and writes `pdf_tables`, `pdf_table_groups`, and `pdf_table_group_members`. Grouping of unreviewed tables is allowed.
9. Results are readable at `GET /api/pdf/jobs/{id}/grouping` after persist.
10. `POST /api/catalogue/batch-push` writes catalogue rows through `catalogue.datasets.push_to_catalogue` and does not set `organisation_id`.

Changing step 7 into a hard approval gate is a behavior change. It should be explicit, with the UI and tests updated together. Do not silently start rejecting Continue.

## Database

PostgreSQL is required. Changing `DATABASE_URL` to another engine does not make the app portable.

Confirmed PostgreSQL features:

- `JSONB`, `TEXT[]`, `BYTEA`, `TIMESTAMPTZ`, `UUID`, `ON CONFLICT`, `ILIKE`
- `CREATE EXTENSION vector` and an HNSW index created in `core/vector_store.py` (not in Alembic revision 001)
- `gen_random_uuid()` via pgcrypto in request-time DDL and the migration

SQLite and MySQL are not supported. `normalize_database_url` leaves unknown schemes unchanged; that is not a portability guarantee.

Schema is defined in three places:

1. SQLAlchemy models in `app/db/models/`
2. Alembic `migrations/versions/001_baseline_orgs_tenant.py`
3. `catalogue.db.init_schema()` plus `pdf_store` and `vector_store` DDL, skipped only when `DISABLE_REQUEST_TIME_DDL=true` (default **false**)

`Base.metadata.create_all` is not used. `/api/ready` does not run DDL.

Two connection styles share one DSN: a SQLAlchemy pool (`app/db/session.py`) and a new psycopg2 connection per `catalogue.db.get_connection()` call.

Identity and keys (do not renumber existing rows):

| Entity | Identifier |
|--------|------------|
| User | `users.email` primary key; `users.id` UUID unique, used as JWT `sub` |
| Organisation | `organisations.id` UUID |
| Membership | `(organisation_id, user_id)`, role on the row |
| Dataset | `datasets.dataset_id` text |
| PDF job | `pdf_jobs.job_id` text (hex uuid) |
| LLM key | `llm_api_keys.user_email` primary key, no organisation column |

`organisation_id` is nullable on datasets, groups, jobs, KYDS, staging, and embeddings. Access-API filters treat NULL as visible to the caller (`organisation_id = %s OR organisation_id IS NULL`). New publishes do not fill the column, so new catalogue rows stay in that shared set. **Runtime:** how many existing rows are NULL is a data question, not visible from code.

Vector search filters by `user_email` when provided, not by `organisation_id`.

Safe schema path: backup, `alembic upgrade head` (additive), then compare indexes with `init_schema` / `ensure_semantic_embeddings_table` and add a follow-up migration for anything only the request path creates (HNSW). Then set `DISABLE_REQUEST_TIME_DDL=true`. Do not drop tables or reset sequences.

## Authentication and tenancy

Intended: one organisation now, more later; admin and regular users; UUID `sub`; short-lived access tokens; role and membership checked on the server; organisation scope on datasets, uploads, jobs, groups, catalogue, and MCP.

What the code does:

- Login and signup issue HS256 JWTs. `sub` is the user UUID. Optional `email` claim is not used for authorization. Role and organisation are loaded from the database on each `require_user` call. Default lifetime is 12 hours (`JWT_EXP_SECONDS`, default 43200). There is no refresh token.
- Passwords are bcrypt hashes.
- `JWT_SECRET` empty fails at token create/decode. It is not a hardcoded production secret. `.env.example` contains a placeholder.
- `ENABLE_SIGNUP` defaults to **true**. Signup joins the default organisation (`DEFAULT_ORGANISATION_SLUG`, default `default`). The first member becomes `administrator`; later members become `data_steward` unless `BOOTSTRAP_ADMIN_EMAIL` matches.
- No route calls `app/core/permissions.py`. `role` is returned by `/api/login` and `/api/me` and ignored by the UI, which stores `Administrator`.
- The client cannot send `organisation_id` on auth routes. Isolation bugs are missing filters, not a caller-supplied org id.
- PDF list/status/result use `_job_visible_to` (email, and org when the job has one). Review, download, persist, and grouping routes compare email only.
- `/api/v1/*` passes `user.organisation_id` and still returns NULL-org rows.
- Console catalogue list and publish do not filter or tag by organisation.
- Classification standards and NCO tables have no organisation column.
- CORS is `allow_origins=["*"]` with all methods and headers.
- `POST /api/catalogue/sql-extract` accepts a database URL or host, user, and password from the authenticated caller and connects outbound. That is a credential-relay and server-side request risk. Restrict hosts before treating this route as safe.

MCP is not tenant-aware. See below.

## LLM credentials

Confirmed lifecycle:

1. Settings posts `{ api_key, provider }` to `POST /api/llm-key` (JWT required).
2. `app/db/repositories/llm_keys.py` stores `api_key` in plaintext `TEXT`.
3. The handler returns the raw key on both GET and POST.
4. `frontend/src/context/AppContext.tsx` writes it to React state and `localStorage` (`dhara.llmApiKey`, `dhara.llmProvider`).
5. `frontend/src/lib/llmKey.ts` attaches `X-Llm-Api-Key` (and provider) on extraction and catalogue calls.
6. `resolve_llm_credentials` prefers the header, otherwise reads plaintext via `catalogue.llm_keys.get_llm_api_key`. Database errors become `(None, None)`.
7. The worker receives the key as a function argument. It is not written onto the `pdf_jobs` JSON payload.
8. Sign-out clears the auth token only. The settings form is filled from the stored key, so the field is not cleared after save.

There is no encryption. `cryptography` is already in `backend/requirements.txt`; use `cryptography.fernet.Fernet` or AES-GCM from that library. Do not invent a cipher.

Target behavior for a later phase (not implemented here):

- Browser sends the key once over HTTPS to an authenticated route, then drops it from memory and `localStorage`.
- Server encrypts before insert. The encryption key is `LLM_CREDENTIALS_KEY` (Fernet key) or a cloud KMS key, not a column in Postgres and not a JWT claim.
- Store ciphertext plus a key version. GET returns `{ configured, provider, updated_at }` only.
- Decrypt only inside the worker or service that calls the provider, for the authenticated user who owns the row.
- Bind the row to `user_id` (and later `organisation_id`). Today the key is per email, and any code that knows the email can read it through the psycopg2 helper.
- Redact `Authorization`, `X-Llm-Api-Key`, and `api_key` in logs. `app/core/logging.py` states that intent and does not implement it.
- Remove the header override after the UI stops sending it.
- Treat any key that has already been returned by GET, stored in `localStorage`, or checked into history as compromised. Rotate it at the provider. Do not copy it into docs, tests, or examples.

## Object storage and jobs

| Store | Used for |
|-------|----------|
| `pdf_jobs` JSONB + BYTEA | Job state and PDF bytes |
| Temp file in the worker | Extraction input; deleted in `finally` |
| GCS via `get_object_store()` when `ENABLE_GCS=true` and a bucket is set | Excel export blobs |
| `NoOpObjectStore` | Default. Callers still write Postgres. |
| `LocalFileStore` | Tests and a class that production selection ignores |
| `semantic_embeddings` | Ancillary index, not the source of truth for groups |

`get_object_store()` raises if GCS is enabled without a bucket. It does not read `STORAGE_BACKEND`.

Jobs: upsert by `job_id`, no content-hash idempotency, no automatic retry, in-flight work dies with the process, finished jobs reload. The API key is an argument, not a job column. **Runtime:** confirm access logs and the platform do not record `X-Llm-Api-Key`.

Direct storage bypass: PDF BYTEA writes in `pdf_store`; catalogue GCS through the shim (same implementation). No other cloud SDK call sites were found.

## MCP

Live package: `backend/app/mcp/`. Stdio is `python -m app.mcp`.

Tools: `search_datasets`, `get_metadata`, `get_table`. They are thin in the sense that they call `catalogue.query`, and they are not thin in the sense that they skip the REST authorisation arguments.

`MCP_HTTP_AUTH` defaults to `off`. `jwt` checks that a Bearer token decodes; it does not load the user or pass `organisation_id` into the query. `token` compares `MCP_AUTH_TOKEN`. DNS rebinding protection is disabled so a public host can reach `/mcp`.

Stdio has no per-request user. The process identity is whoever can run `python -m app.mcp` and whoever owns `backend/.env` (it calls `load_dotenv`). That mode is for a trusted local operator. It must not be exposed on a multi-user host without a separate OS user and a secret file that is not the database role.

Do not give MCP tools the raw LLM key. They do not need one today; these three tools are reads. Future tools that call the LLM must decrypt server-side.

## Tests that exist

CI (`.github/workflows/backend-ci.yml`) imports the app and runs `pytest -q -m "not postgres and not slow"` on Python 3.11. It does not start Postgres. The `postgres` marker is unused.

Unit tests cover health probes, JWT helper cases, a mocked tenant helper, MCP HTTP auth modes and tool **names**, storage fakes, worker registration with a mocked save, and a large set of PDF/Excel parsing fixtures. They do not cover login HTTP, LLM key HTTP, Alembic, real tenant isolation, MCP tool results, or the upload-to-group path against a database.

This audit did not run that suite and does not claim it passes.

## End-to-end test plan (not executed)

Run only against a disposable database and an empty storage directory. Do not point `DATABASE_URL` at a developer or production instance.

Fixture: one small PDF or CSV already in the repo test files, plus a fake LLM provider that returns a fixed classification payload. If the fake is used, report live-provider behavior as unverified.

Steps:

1. Create a database, run `alembic upgrade head`, set `DISABLE_REQUEST_TIME_DDL=true`.
2. Create organisation A, an admin, and a regular user. Create organisation B and a user in B. Disable public signup for this run.
3. Log in as the regular user. Assert JWT `sub` is their UUID, role comes from the membership row, and a data-user token cannot call an admin-only route once those checks exist.
4. Save an LLM credential that is a test value, not a real provider key. Assert the HTTP response has no raw secret, the database column is ciphertext, `localStorage` is empty, and a second GET returns only `configured` and `updated_at`.
5. Upload the fixture. Poll until the job is `done`. Assert extracted tables match the fixture contract.
6. Classify with the known standard (bundled NCO 2015 or a fixture standard) and record the version.
7. Attempt grouping while a required review flag is set, and assert it is rejected **after** the approval gate is implemented. Until then, record the current behavior (grouping is allowed) rather than failing the test on today's product rule.
8. Approve, group, and GET the grouping resource. Assert the same rows exist in Postgres.
9. Call the same read through MCP with organisation A's identity. Assert the same dataset or job is visible.
10. Restart the API process. GET the job and grouping again.
11. As organisation B, and with no token when MCP auth is required, assert 401 or empty results. Assert B cannot read A's PDF job by id.
12. Assert logs and the `pdf_jobs` row do not contain the test credential.

## Implementation plan

Security first, then one vertical slice at a time. Do not delete a legacy module in the same change that introduces its replacement.

### Phase A — LLM credential containment

**Files:** `app/api/routes/llm_key.py`, `app/db/repositories/llm_keys.py`, `app/db/models/catalogue.py` (`LlmApiKey`), `app/api/dependencies.py` (`resolve_llm_credentials`), `catalogue/llm_keys.py`, `frontend/src/lib/llmKey.ts`, `frontend/src/context/AppContext.tsx`, `frontend/src/components/Settings.jsx`, `app/core/config.py`, a new Alembic revision (additive columns only).

**Callers:** Settings page; every route that calls `resolve_llm_credentials` or `withLlmKeyHeaders` (PDF upload, grouping propose, catalogue extract/match/fill).

**Changes:** Encrypt at rest with Fernet (or AES-GCM) and `LLM_CREDENTIALS_KEY`. GET/POST return metadata only. Stop writing `localStorage`. Clear the input after a successful save. Decrypt only in the server-side resolver. Keep the header override until the frontend no longer sends it, then remove it in a follow-up. Add log redaction for the header and JSON field. Do not put the key in JWT.

**Tests:** repository round-trip with a test Fernet key; route test that the body has no `api_key`; regression that extraction still receives a decrypted key server-side.

**Acceptance:** a saved key cannot be read back through the API or browser storage; extraction still runs when the server holds the secret.

**Rollback:** keep the plaintext column until ciphertext writes succeed, then stop reading plaintext. Do not drop the column in the first revision.

**Depends on:** nothing.

### Phase B — Close unauthenticated catalogue reads

**Files:** `mcp_server/http_asgi.py`, `mcp_server/__init__.py`, `catalogue/query.py`, `routes/catalogue.py` (list/get), `routes/access.py`, `app/db/repositories/catalogue.py`, `app/main.py` OpenAPI text.

**Callers:** `/mcp`, `/api/catalogue/groups`, `/api/catalogue/datasets`, `/api/v1/*`, frontend catalogue page.

**Changes:** Default `MCP_HTTP_AUTH` to `jwt` (or require an explicit `off` for a demo). When a user is present, pass `organisation_id` into the same query functions REST uses. Tag `batch-push` with the caller's organisation via the existing repository wrapper. Decide, in code and in a test, whether NULL-org rows stay globally visible. Document that choice; do not silently hide legacy rows if production still depends on them (**runtime** check of NULL counts first).

**Tests:** MCP initialize without a token returns 401 when auth is on; two orgs cannot read each other's tagged datasets; publish sets `organisation_id`.

**Rollback:** env `MCP_HTTP_AUTH=off` restores the old default. Org tagging is additive.

**Depends on:** Phase A is independent. Do B before any MCP feature work.

### Phase C — Authorization that matches the membership row

**Files:** `app/core/permissions.py`, `app/api/dependencies.py`, `app/api/routes/auth.py`, `frontend/src/context/AppContext.tsx`, `frontend/src/lib/auth.ts`, signup call sites, `scripts/create_user.py`.

**Changes:** Read `role` from `/api/login` and `/api/me` in the client. Stop hardcoding `Administrator`. Add server checks for the few operations that must be admin-only (user provisioning, standard upload/delete if that is the product rule). Default `ENABLE_SIGNUP` to false in deployment docs and production examples; keep a dev override. Leave self-serve signup available only when the flag is on, matching current product behavior unless you confirm invites are required.

**Tests:** data steward cannot call an admin route; UI fixture shows the server role; signup 403 when disabled.

**Rollback:** permission dependency can be feature-flagged per route.

**Depends on:** none. Independent of A and B.

### Phase D — PDF review and grouping as one service slice

**Files:** `routes/pdf.py`, `pdf/pdf_store.py`, `pdf/pdf_grouping.py`, `app/services/grouping/service.py`, `app/db/repositories/pdf_jobs.py`, `app/workers/extraction_jobs.py`.

**Callers:** PDF review and grouping pages, dashboard job lists.

**Changes:** Move persist and propose behind functions that take user id, organisation id, and job id, and enforce the same visibility rule on every PDF route. Keep HTTP shapes. Add an explicit approval rule only if product agrees; until then preserve "status done is enough" and test that. Grouping implementation moves into `app/services/grouping` by wrapping the current functions, not by rewriting the matcher.

**Tests:** extend `test_tenant_isolation.py` and `test_singleton_llm_grouping.py`; one test that a non-owner receives 404 on persist and on grouping.

**Rollback:** routes can call the old functions if the service is a pass-through.

**Depends on:** C for a shared permission helper is helpful, not blocking.

### Phase E — Catalogue publish slice

**Files:** `routes/catalogue.py`, `catalogue/datasets.py`, `catalogue/query.py`, `app/services/catalogue/service.py`, `app/services/datasets/service.py`, `metadata/*`.

**Changes:** One publish function used by `batch-push`. List/get for the console use the same org predicate as `/api/v1`. Metadata fill reads KYDS through `app/db/repositories/kyds.py`. Leave the wizard Excel extractor in place.

**Tests:** publish then list as the same user; other org excluded; KYDS text still appears in metadata fill.

**Depends on:** B (org tagging decision).

### Phase F — Classification and standards

**Files:** `catalogue/classifications.py`, `nco_matching.py`, `nco_aliases.py`, `classification_standards.py`, `app/services/classification/service.py`, `app/services/standards/service.py`, `routes/catalogue.py` classify routes.

**Changes:** Move match and standard selection into services without changing NCO 2015 as the bundled default. Standards stay global until a product decision makes them per organisation; record that they are global today.

**Tests:** existing `test_nco_matching.py`, `test_nco_alias_codes.py`, plus a route test for the selected standard id.

**Depends on:** E if classify stays on the publish page; otherwise independent.

### Phase G — Storage and durable jobs

**Files:** `app/storage/object_store.py`, `app/storage/local.py`, `app/workers/extraction_jobs.py`, `pdf/pdf_store.py`, `app/core/config.py`.

**Changes:** Honor `STORAGE_BACKEND=local|gcs|none`. Keep PDF BYTEA working until objects are written and read back through the interface; then store an object key on the job. Add a startup sweep that marks stale `running` jobs as `error` or requeues them. Do not introduce Celery in this phase unless operations asks for a second process. No secrets in the job row.

**Tests:** `test_storage.py` for backend selection; worker test that a restarted reader sees a completed job; failed job does not retry forever.

**Depends on:** D so job ownership rules exist before files move.

### Phase H — MCP on shared services

**Files:** `mcp_server/*` moved or wrapped by `app/mcp/`, tool handlers, tests `test_mcp_http.py`.

**Changes:** Tools call the Phase E read service. Pass the authenticated user. Preserve tool names and argument names. Stdio documented as process-identity access. Fix the docstring that claims JWT is the default once Phase B has landed.

**Tests:** tool call returns the same payload as `GET /api/v1/datasets` for one fixture; wrong org gets not found.

**Depends on:** B and E.

### Phase I — Schema single source and shim removal

**Files:** `catalogue/db.py` `init_schema`, `migrations/`, shims listed in `RESIDUE_AUDIT.md`, `catalogue/users.py`.

**Changes:** Add the missing vector index to Alembic. Turn off request-time DDL in production. Delete a shim only when its importers and tests are updated. Do not drop `catalogue/users.py` until the facade export is removed and external scripts are confirmed absent.

**Tests:** fresh database migrates with Alembic alone and `/api/ready` succeeds; PDF and catalogue smoke against that database.

**Depends on:** D, E, G.

### Phase J — Disposable end-to-end test

Implement the plan in the previous section in CI or a documented local script with a Postgres service. Mock the LLM. Do not mark the workflow verified until this run exists.

**Depends on:** A, B, D, E, H.
