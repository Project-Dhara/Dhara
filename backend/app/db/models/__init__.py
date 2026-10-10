"""ORM model package.

Current tables are created by psycopg2 DDL (users, metadata_groups,
datasets, dataset_rows, kyds_entries, classification_*, pdf_*,
extract_staging, semantic_embeddings, and later llm_api_keys). Models
will map those tables in Phase 3 without dropping data.
"""
