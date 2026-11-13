"""Catalogue / classify / SQL extract JSON bodies (UI-compatible)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class TableMetadataRequest(BaseModel):
    """POST /api/table-metadata."""

    model_config = ConfigDict(extra="ignore")

    table_id: Any = ""
    title: Any = ""
    description: Any = ""
    raw_header_rows: List[Any] = Field(default_factory=list)
    columns: List[Any] = Field(default_factory=list)
    sample_rows: List[Any] = Field(default_factory=list)
    raw_notes: List[Any] = Field(default_factory=list)


class SqlExtractRequest(BaseModel):
    """POST /api/catalogue/sql-extract."""

    model_config = ConfigDict(extra="ignore")

    database_url: Optional[str] = None
    host: Optional[str] = None
    port: Optional[Any] = None
    database: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    sslmode: Optional[str] = None
    query: Optional[str] = None
    title: Optional[str] = None
    table_id: Optional[str] = None
    row_limit: Optional[Any] = None
    max_tables: Optional[Any] = None


class FillGroupMetadataRequest(BaseModel):
    """POST /api/catalogue/fill-group-metadata."""

    model_config = ConfigDict(extra="ignore")

    groups: List[Dict[str, Any]]
    standard: Optional[str] = "nmds"
    dataset_files_b64: Optional[Dict[str, Any]] = None


class FillDefinitionsRequest(BaseModel):
    """POST /api/catalogue/fill-definitions."""

    model_config = ConfigDict(extra="ignore")

    columns: List[Dict[str, Any]] = Field(default_factory=list)
    allow_occupation: bool = False


class MatchOccupationsRequest(BaseModel):
    """POST /api/catalogue/match-occupations (or equivalent NCO match route)."""

    model_config = ConfigDict(extra="ignore")

    values: List[Any] = Field(default_factory=list)
    context: Optional[Dict[str, Any]] = None


class MatchLgdRequest(BaseModel):
    """POST /api/catalogue/match-lgd — values matched via explorer Directory.search."""

    model_config = ConfigDict(extra="ignore")

    values: List[Any] = Field(default_factory=list)


class NcoAliasesRequest(BaseModel):
    """POST /api/catalogue/nco-aliases."""

    model_config = ConfigDict(extra="ignore")

    aliases: List[Dict[str, Any]] = Field(default_factory=list)


class ClassificationColumnUpdateRequest(BaseModel):
    """PATCH /api/catalogue/metadata-groups/{id}/classifications."""

    model_config = ConfigDict(extra="ignore")

    column_name: Optional[str] = None
    column_names: Optional[List[Any]] = None
    codes: Optional[Any] = None
    expand_aliases: bool = True
