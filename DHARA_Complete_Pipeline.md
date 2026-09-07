# DHARA — End-to-End Data Understanding, Harmonization & Interoperability Pipeline

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

The current implementation has progressed through PDF extraction and the initial LLM-assisted reconstruction/semantic understanding stage.

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
```

The current PDF pipeline uses PyMuPDF rather than Camelot/pdfplumber. The LLM stage performs both **table reconstruction** and **initial semantic understanding/classification** in one call.

### Next

```text
→ Human classification review UI + persistence
→ Semantic chunking
→ Embedding generation
→ pgvector indexing
→ Similarity-based candidate retrieval
→ Intelligent grouping
→ Grouping human review
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

---

## 8. Stage 4 — Human Review of Classification

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
```

### NEXT

```text
Human classification review
 ↓
Persist approved semantic representation
 ↓
Semantic chunking
 ↓
Embedding generation
 ↓
pgvector
 ↓
Similarity retrieval
 ↓
Grouping
 ↓
Human grouping review
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
