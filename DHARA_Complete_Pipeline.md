# DHARA — End-to-End Data Understanding, Harmonization & Interoperability Pipeline

> **Canonical docs:** For architecture, stage-by-stage design (including planned
> steps), and on-prem/cloud deployment, see [`docs/`](./docs/README.md). This
> file remains a long-form design narrative; prefer `docs/` when something
> conflicts with current code status.

## 1. Overview

DHARA is designed as a data interoperability and AI-readiness layer for government data.

Core principle:

> **AI proposes → Human reviews → Human approves → DHARA remembers the approved meaning.**

The pipeline takes government data such as PDF/Excel, reconstructs usable tables, understands their meaning, gets human approval where needed, identifies related tables, harmonizes concepts against standards, and ultimately makes approved data discoverable and accessible through catalogue/API/MCP interfaces.

---

## 2. End-to-End Flow

```text
                        GOVERNMENT DATA
                              │
                    ┌─────────┴─────────┐
                    │                   │
                   PDF                Excel
                    │                   │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ 1. EXTRACTION     │
                    │ PyMuPDF / native  │
                    │ extraction        │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ 2. RECONSTRUCTION │
                    │ Candidate tables  │
                    │ → clean tables    │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ 3. INITIAL        │
                    │ SEMANTIC          │
                    │ UNDERSTANDING     │
                    │ Table + columns   │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ 4. HUMAN REVIEW   │
                    │ AI proposal       │
                    │ → edit → approve  │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ APPROVED SEMANTIC │
                    │ REPRESENTATION    │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ 5. VECTOR INDEX   │
                    │ Chunk + embed     │
                    │ Store in pgvector │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ 6. GROUPING       │
                    │ Similarity → LLM  │
                    │ → human approval  │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ 7. HARMONIZATION  │
                    │ Canonical concepts│
                    │ Standards / codes │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ 8. TRANSFORMATION │
                    │ Apply approved    │
                    │ mappings/rules    │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ 9. VALIDATION     │
                    │ Structure +       │
                    │ semantics + QA    │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ 10. METADATA &    │
                    │ CATALOGUE         │
                    │ NMDS / DCAT-AP    │
                    └─────────┬─────────┘
                              ↓
                    ┌───────────────────┐
                    │ 11. ACCESS        │
                    │ Catalogue / API   │
                    │ / MCP             │
                    └───────────────────┘
```

---

## 3. Current Status

The current implementation has progressed through PDF extraction, LLM-assisted reconstruction/semantic understanding, and the human classification review UI with persistence. Excel and PDF share the same Console stages rail for Dataset Inventory (Files → Preview → Grouping).

### Implemented

```text
✓ PDF page inspection
✓ PyMuPDF table extraction
✓ Multiple extraction strategies
✓ Deterministic confidence classification
✓ High-confidence bypass of LLM
✓ Batched LLM validation/reconstruction
✓ Initial semantic classification in the same LLM call
✓ Structured JSON output
✓ Extraction uncertainty tracking
✓ Semantic uncertainty tracking
✓ human_review_needed flags
✓ Human-review reasons
✓ PDF job API (upload, poll, result, table patch, soft-delete)
✓ Job persistence under backend/data/pdf_jobs/
✓ Processing progress UI (/console/processing/[jobId])
✓ Shared Console stages rail (Excel + PDF)
✓ Human classification review UI (/console/review/[jobId])
✓ Review filters, sticky filter bar, scroll-to-top
✓ Direction / dropdown cell editing where schema provides options
✓ Soft-delete of tables from a job
✓ Continue → Grouping (/console/grouping/[jobId])
✓ Extraction guards (ungrounded Direction strip, column-alignment flag)
✓ pgvector-enabled Postgres (pgvector/pg16)
✓ semantic_embeddings table + HNSW index (core/vector_store.py)
✓ pdf_jobs / pdf_tables / pdf_table_groups in PostgreSQL (SoT after Preview)
✓ Persist approved tables on Continue (POST …/persist-approved)
✓ Semantic chunking + embed (table_summary / column_meaning)
✓ pgvector similarity clustering → draft groups
✓ PDF Grouping UI (drag-and-drop, automatic/manual) at /console/grouping/[jobId]
```

The current PDF pipeline uses PyMuPDF rather than Camelot/pdfplumber. The LLM stage performs both **table reconstruction** and **initial semantic understanding/classification** in one call.

### Console stages (Dataset Inventory)

Excel (`components/console/Console.jsx`) and PDF (`components/pdf/PdfConsoleLayout` + `components/console/ConsoleStages.jsx`) use the same stage definitions:

```text
1 Files     — upload / PDF processing
2 Preview   — human table / classification review
3 Grouping  — PDF: pgvector propose + drag-and-drop (Excel: live title grouping)
4–6         — Metadata / Harmonisation / Publish (locked until built)
```

PDF routes:

```text
/console                         → upload (Files)
/console/processing/[jobId]      → extraction progress (Files)
/console/review/[jobId]          → Preview (PdfReview)
/console/grouping/[jobId]         → Grouping (pgvector propose + human edit)
```

### Next

```text
→ Persist approved semantic representation more deeply (beyond pdf_tables JSONB)
→ LLM cluster confirmation (optional split/merge reasoning)
→ Metadata workspace for PDF groups
→ Harmonization
→ Transformation
→ Final validation
→ Catalogue/API/MCP layer
```

---

## 4. Stage 0 — Dataset Context / KYDS

Before processing the data, DHARA captures context supplied by the data custodian.

Typical information:

```text
Dataset purpose
Data custodian
Domain
Entity
Geography
Time period
Frequency
Source
Existing metadata
Existing standards
```

Important distinction:

> **KYDS tells DHARA what the custodian says the dataset is.**

> **Extraction tells DHARA what is physically present in the file.**

> **Semantic understanding determines what the extracted data appears to mean.**

> **Human approval establishes the trusted interpretation.**

---

## 5. Stage 1 — Data Extraction

For PDFs:

```text
PDF
 ↓
PyMuPDF page inspection
 ↓
Identify pages with extractable text
 ↓
PyMuPDF find_tables()
 ↓
lines_strict extraction
 +
text-based extraction
 ↓
candidate tables
```

The extraction layer retrieves physical structure and source values.

It should not silently alter source data.

For other formats, the equivalent native parser can be used where appropriate.

---

## 6. Stage 2 — Deterministic Confidence & Reconstruction

Not every extracted table needs an LLM.

The pipeline first evaluates extraction confidence using deterministic signals such as:

```text
Cell fill rate
Header shape
Candidate agreement
Table structure
```

Then:

```text
High confidence
    ↓
Accept directly

Ambiguous / lower confidence
    ↓
Send to LLM
```

This prevents unnecessary LLM calls.

---

## 7. Stage 3 — LLM Reconstruction + Initial Semantic Understanding

The LLM receives extracted candidates and relevant page context.

It performs two related tasks in one call.

### A. Reconstruction

The LLM reconciles candidate extractions into a logical table.

It can:

- reconcile competing candidate extractions
- flatten multi-row headers
- preserve titles/descriptions
- identify structural issues
- flag uncertain cells
- avoid inventing values

### B. Semantic Understanding

At the same time it determines what the table appears to mean.

Table-level:

```text
Domain
Subject
Entity
Table type
Geography
Time period
Frequency
Unit
```

Column-level:

```text
Column name
Role
Concept
Description
Data type
Unit
Category
```

Possible roles:

```text
identifier
dimension
measure
attribute
unknown
```

Example:

```text
State
→ dimension
→ concept: State

PHC ID
→ identifier
→ concept: Primary Health Centre

Male
→ measure
→ concept: Population
→ category: Male

Female
→ measure
→ concept: Population
→ category: Female
```

This is **classification**, not harmonization.

At this stage DHARA asks:

> **What does this data appear to represent?**

It does not yet ask:

> **Which official canonical standard/code should this map to?**

### POC extraction guards (post-LLM)

After the LLM returns tables, the pipeline applies lightweight guards before review:

```text
Strip ungrounded Direction / Trend columns not present in source candidates
Flag column_alignment_mismatch when reconstructed columns disagree with candidates
Optional fallback to a pymupdf_lines_strict grid when alignment is severely broken
BrokenProcessPool retry with worker halving on OOM during extract
```

These improve review quality without changing the Stage 4 human-approval contract.

The LLM output is a proposal, not authoritative truth.

Review metadata identifies exactly what requires attention.

Example:

```json
{
  "name": "Direction",
  "role": "unknown",
  "concept": "Performance Direction",
  "human_review_needed": true,
  "human_review_reason": "uncertain_semantic_role"
}
```

At table level:

```json
{
  "human_review_needed": true,
  "human_review_reason": "uncertain_semantic_role"
}
```

Review flags can exist at:

```text
Table level
Classification field level
Column level
```

### Implemented in the POC (Preview UI)

This stage is live for PDF jobs in the frontend Preview step.

```text
Load   GET  /api/pdf/jobs/{job_id}/result
Save   PATCH /api/pdf/jobs/{job_id}/tables/{table_id}
Delete POST /api/pdf/jobs/{job_id}/tables/delete
```

`PdfReview` (`frontend/src/components/pdf/PdfReview.jsx`) provides:

```text
Expandable table cards with classification + column metadata edits
Status / reason filters (needs review, no review, garbled, alignment, …)
Sticky filter bar inside the content panel (AppShell scroll parent)
Scroll-to-top on the review page
Editable Direction / categorical cells when input_type = dropdown
Numeric cells remain locked; garbled cells stay highlighted
Soft-delete of selected tables (persisted deleted_table_ids)
Continue → navigates to the Grouping placeholder for PDF
```

Processing progress before review (`/console/processing/[jobId]`) polls job status and maps backend percent bands to:

```text
classify → extract → classify_confidence → validate
```

(`validate` may show as skipped when no tables enter the LLM queue.)

The reviewer edits incorrect AI interpretations and approves the result.

The source data rows are not silently rewritten during classification review.

After approval:

```text
AI proposal
    ↓
Human correction
    ↓
Human approval
    ↓
APPROVED SEMANTIC REPRESENTATION
```

This approved representation becomes trusted DHARA knowledge.

### Important distinction

```text
semantic_status
→ Has semantic classification happened?

human_review_needed
→ Does an existing result need human attention?

human_review_reason
→ Why is attention required?
```

Example:

```text
semantic_status = "not_classified"
human_review_needed = false
```

is valid for a high-confidence table that bypassed the LLM.

---

## 9. Stage 5 — Semantic Chunking

After human approval, DHARA creates searchable semantic representations.

Do not embed every cell by default.

Useful semantic units include:

```text
Dataset description
Table description
Table classification
Column meaning
Column + role + concept
Indicator definitions
Approved mappings
Standards/concepts
Categorical concepts where useful
```

Example:

```text
"PHC ID | identifier | Primary Health Centre"

"State | dimension | State"

"Male | measure | Population | category Male"
```

These semantic chunks are converted into embeddings.

---

## 10. Stage 6 — Vector Database / pgvector

Use PostgreSQL as the source of truth and pgvector for semantic retrieval.

```text
PostgreSQL
├── Authoritative metadata
├── Approved classifications
├── Approved mappings
├── Provenance
└── pgvector
     └── Semantic embeddings
```

The vector store is **not** the authoritative database.

Its job is:

> **Find semantically similar objects quickly.**

PostgreSQL remains the source of truth.

Initial architecture should avoid adding Elasticsearch/OpenSearch unless scale later requires it.

### Implemented in the POC

```text
✓ Docker Postgres image: pgvector/pgvector:pg16
✓ CREATE EXTENSION vector (init SQL + catalogue.init_schema)
✓ semantic_embeddings table (chunk text + vector(1536) + object keys)
✓ HNSW cosine index for nearest-neighbour search
✓ backend/core/vector_store.py — upsert_embedding / similarity_search
✓ GET /api/health reports pgvector readiness
```

Embeddings are keyed to authoritative objects (`object_type`=`pdf_table`, `object_id`=table UUID, `chunk_kind`, optional `job_id`) and never replace `pdf_tables` / catalogue rows as source of truth. PDF Preview → Continue indexes `table_summary` (+ column chunks) into this store for grouping.

---

## 11. Stage 7 — Intelligent Grouping

Grouping asks:

> **Which tables are related and should be considered part of the same logical dataset/topic/group?**

This is different from classification.

Classification:

```text
"What does this table mean?"
```

Grouping:

```text
"Which other tables are related to this table?"
```

### Grouping flow

```text
Approved table
      ↓
Semantic representation
      ↓
Embedding
      ↓
pgvector similarity search
      ↓
Candidate related tables
      ↓
LLM compares candidates
      ↓
Relationship proposal
      ↓
Human review
      ↓
Approved grouping
```

Example:

```text
Table A
"Population by State"

Table B
"Population by District"

Table C
"Population by Sex"

Table D
"Number of Hospitals by State"
```

Vector retrieval identifies candidates with semantic similarity.

The LLM then reasons about whether they are actually related.

The human approves the final grouping.

### Important

Vector similarity is a **candidate retrieval mechanism**, not the final decision.

Use:

```text
Exact / lexical matching
+
PostgreSQL full-text search
+
pgvector semantic similarity
        ↓
Candidate set
        ↓
LLM reasoning
        ↓
Human approval
```

### Implemented in the POC (PDF)

```text
✓ POST /api/pdf/jobs/{id}/persist-approved → pdf_jobs + pdf_tables
✓ Chunk table_summary (+ column_meaning) and upsert into semantic_embeddings
✓ Propose groups via cosine-distance clustering (union-find)
✓ GET/PUT /api/pdf/jobs/{id}/grouping + POST …/grouping/propose
✓ PdfGrouping UI — Automatic / Manual, drag-and-drop, rename, save
```

JSON under `data/pdf_jobs/` remains the extraction/review working cache; after Continue, **PostgreSQL is SoT** for tables and groups. Optional LLM cluster confirmation is still future work.

---

## 12. Stage 8 — Harmonization

Grouping tells us which tables are related.

Harmonization asks:

> **How should the meaning of those tables be aligned to common canonical concepts and standards?**

Example:

```text
Dataset A:
Gender = M / F

Dataset B:
Sex = Male / Female

Dataset C:
Gender = 1 / 2
```

Classification identifies what these fields mean.

Harmonization determines whether they can map to a common canonical concept and, where applicable, a standard code list.

The flow is:

```text
Observed source value
        ↓
AI interpretation
        ↓
Canonical concept
        ↓
Official standard/code
        ↓
Human approval
```

Potential standards:

```text
NMDS
LGD
NCO
Other government standards
Domain-specific standards
```

Do not overwrite original source values.

Store mappings separately with provenance.

---

## 13. Stage 9 — Transformation

Once harmonization mappings are approved, DHARA can generate transformation rules.

Example:

```text
Source:
M → Male
F → Female

Canonical:
Male → M
Female → F
```

Or:

```text
Source:
Karnataka

Canonical geography:
LGD concept/code
```

The transformation layer applies approved rules to create a harmonized representation.

Original source data remains immutable.

---

## 14. Stage 10 — Validation

After transformation, DHARA validates the resulting data.

### Structural validation

```text
Schema
Column names
Data types
Dates
Units
IDs
Nulls
Duplicates
Ranges
Row structure
```

### Semantic validation

```text
Does the transformed column still mean what it should?
Are mappings consistent?
Are units compatible?
Are categories valid?
Do related tables use compatible concepts?
```

### Provenance

Every transformation should be traceable:

```text
Original value
→ Rule/mapping
→ Harmonized value
→ Standard/concept
→ Approval
```

---

## 15. Stage 11 — Metadata and Catalogue

Once data is validated, DHARA creates/updates metadata.

Potential metadata standards:

```text
NMDS
DCAT-AP
Other required government metadata
```

The catalogue should expose:

```text
Dataset
Tables
Descriptions
Custodian
Domain
Geography
Time period
Frequency
Variables
Concepts
Standards
Provenance
Quality
Access information
```

---

## 16. Stage 12 — Access Layer

Approved and catalogued data can be exposed through:

```text
Catalogue
    ↓
API
    ↓
MCP
```

Potential capabilities:

```text
Dataset discovery
Table discovery
Semantic search
API queries
Cross-department data access
AI-assisted data discovery
MCP-based agent access
```

Only approved and authorized data should be exposed.

---

## 17. Separation of Responsibilities

| Component | Responsibility |
|---|---|
| PyMuPDF / extraction | Get physical data from documents |
| Python / SQL | Mechanical processing and validation |
| LLM | Understand, reconstruct, classify, reason |
| pgvector | Find semantically similar objects |
| Agent/orchestration | Coordinate multi-step investigation where needed |
| Human | Approve semantic decisions |
| PostgreSQL | Authoritative source of truth |
| Object storage | Original files and artifacts |
| Catalogue | Discoverability and metadata |
| API/MCP | Approved downstream access |

---

## 18. Core AI Pattern

DHARA should follow this pattern throughout the pipeline:

```text
                 AI
                  ↓
              PROPOSAL
                  ↓
              RETRIEVAL
                  ↓
               REASON
                  ↓
             HUMAN REVIEW
                  ↓
              APPROVAL
                  ↓
         AUTHORITATIVE KNOWLEDGE
```

AI should not silently turn an uncertain interpretation into truth.

---

## 19. Why Vector DB Comes After Classification

The vector database becomes much more useful once DHARA knows what the tables and columns mean.

Less useful:

```text
Raw PDF
 ↓
Embed raw text
 ↓
Find similar raw text
```

Preferred:

```text
PDF
 ↓
Extract
 ↓
Reconstruct
 ↓
Understand
 ↓
Human approve
 ↓
Create semantic representation
 ↓
Embed
 ↓
pgvector
```

The vector store is therefore built from meaningful semantic information rather than noisy document text.

---

## 20. Future Agentic Architecture

Initially DHARA does not need many autonomous agents.

The pipeline can remain a deterministic workflow with LLM calls at appropriate points.

Later, specialized orchestration could look like:

```text
Ingestion
Agent
   ↓
Semantic
Engine
   ↓
Grouping
Agent
   ↓
Harmonization
Agent
   ↓
Validation
Engine
```

Agents should be introduced when the system needs to decide dynamically:

```text
Which tool should I use?
Which source should I inspect?
Which standard should I retrieve?
Do I need more evidence?
Should this require human review?
```

Do not introduce agents simply for the sake of calling something an agent.

---

## 21. Target Architecture

```text
                         DHARA
                           │
          ┌────────────────┼────────────────┐
          │                │                │
     Object Storage     PostgreSQL      AI Gateway
          │                │                │
     Original files    Source of truth     LLM
     Extracted files   Metadata            Embeddings
     Artifacts         Approvals
                       Provenance
                           │
                       pgvector
                           │
                           ↓
                  Semantic Retrieval
                           │
                           ↓
                    Grouping Engine
                           │
                           ↓
                  Harmonization Engine
                           │
                           ↓
                    Validation Engine
                           │
                           ↓
                  Metadata / Catalogue
                           │
                     ┌─────┴─────┐
                     ↓           ↓
                    API         MCP
```

---

## 22. Current → Next → Future

### CURRENT

```text
PDF
 ↓
PyMuPDF
 ↓
Table extraction
 ↓
Deterministic confidence
 ↓
LLM reconstruction
 ↓
Initial classification
 ↓
Human-review metadata
 ↓
Shared Console stages (Files / Preview / Grouping)
 ↓
Processing progress UI
 ↓
Human classification review UI
 ↓
Persist table edits + soft-delete (pdf_jobs JSON cache)
 ↓
Persist approved tables to PostgreSQL (pdf_tables)
 ↓
Semantic chunks + embeddings (semantic_embeddings)
 ↓
pgvector similarity grouping + human drag-and-drop UI
```

### NEXT

```text
LLM cluster confirmation (optional)
 ↓
Metadata workspace for PDF groups
 ↓
Human grouping refinements → catalogue metadata
```

### AFTER GROUPING

```text
Approved groups
 ↓
Harmonization
 ↓
Standards mapping
 ↓
Human approval
 ↓
Transformation
 ↓
Validation
 ↓
Metadata
 ↓
Catalogue
 ↓
API / MCP
```

---

## 23. Key Design Principles

### 1. Original data is immutable

DHARA never silently changes source data.

### 2. AI output is a proposal

LLM-generated meaning does not automatically become authoritative.

### 3. Human approval creates trusted knowledge

Approved decisions are persisted and reused.

### 4. Vector search retrieves; it does not decide

Similarity provides candidates. Reasoning and human review establish relationships.

### 5. Deterministic processing stays deterministic

Use Python/SQL for mechanical operations wherever possible.

### 6. One LLM call can perform multiple related reasoning tasks

For example:

```text
Reconstruction + initial classification
```

rather than unnecessarily introducing separate sequential LLM calls.

### 7. Standards mapping happens after understanding

First determine:

> **What does this data mean?**

Then determine:

> **Which canonical standard represents that meaning?**

### 8. Provenance is retained throughout

Every semantic decision and transformation should be traceable back to the source.

### 9. Start simple

Initial infrastructure:

```text
PostgreSQL
+ pgvector
+ Object Storage
+ FastAPI
+ Background workers
+ LLM Gateway
```

Add specialized infrastructure only when scale requires it.

---

## 24. The DHARA Semantic Knowledge Loop

The long-term value of DHARA comes from turning one-off human decisions into reusable institutional knowledge.

```text
                 DATASET
                    ↓
                EXTRACTION
                    ↓
              UNDERSTANDING
                    ↓
             HUMAN APPROVAL
                    ↓
          ┌────────────────────┐
          │ APPROVED KNOWLEDGE │
          └─────────┬──────────┘
                    ↓
                pgvector
                    ↓
             FUTURE DATASETS
                    ↓
          Retrieve prior knowledge
                    ↓
              LLM reasoning
                    ↓
             Human approval
                    ↓
          More approved knowledge
                    │
                    └──────────────→
```

This is the foundation for DHARA becoming a reusable semantic and interoperability layer across government departments rather than a one-time document processing tool.
