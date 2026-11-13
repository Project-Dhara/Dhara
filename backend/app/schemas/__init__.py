"""Public API request/response schemas (Pydantic).

Validated contracts for OpenAPI /docs Try-it-out. Keep field names and shapes
identical to the JSON the frontend already sends and expects.
"""

from app.schemas.auth import AuthResponse, LoginRequest, MeResponse, SignupRequest
from app.schemas.catalogue import (
    ClassificationColumnUpdateRequest,
    FillDefinitionsRequest,
    FillGroupMetadataRequest,
    MatchOccupationsRequest,
    MatchLgdRequest,
    NcoAliasesRequest,
    SqlExtractRequest,
    TableMetadataRequest,
)
from app.schemas.jobs import PipelineStepRequest
from app.schemas.kyds import (
    KydsEntry,
    KydsMineResponse,
    KydsPatchResponse,
    KydsSaveRequest,
    KydsSaveResponse,
)
from app.schemas.llm_key import LlmKeySaveRequest, LlmKeyStatusResponse
from app.schemas.pdf import (
    AiSearchRequest,
    GroupingProposeRequest,
    GroupingSaveRequest,
    PersistApprovedRequest,
    ReviewTablePatch,
    TableIdsRequest,
)

__all__ = [
    "AuthResponse",
    "LoginRequest",
    "MeResponse",
    "SignupRequest",
    "PipelineStepRequest",
    "KydsEntry",
    "KydsMineResponse",
    "KydsPatchResponse",
    "KydsSaveRequest",
    "KydsSaveResponse",
    "LlmKeySaveRequest",
    "LlmKeyStatusResponse",
    "ClassificationColumnUpdateRequest",
    "FillDefinitionsRequest",
    "FillGroupMetadataRequest",
    "MatchOccupationsRequest",
    "MatchLgdRequest",
    "NcoAliasesRequest",
    "SqlExtractRequest",
    "TableMetadataRequest",
    "AiSearchRequest",
    "GroupingProposeRequest",
    "GroupingSaveRequest",
    "PersistApprovedRequest",
    "ReviewTablePatch",
    "TableIdsRequest",
]
