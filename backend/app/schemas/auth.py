"""Auth request/response contracts (login, signup, session)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    """Body for POST /api/login."""

    model_config = ConfigDict(extra="ignore")

    email: str = Field(
        ...,
        description="Login email in name@organization.domain form",
        examples=["steward@example.gov.in"],
    )
    password: str = Field(..., min_length=1, description="Account password")


class SignupRequest(BaseModel):
    """Body for POST /api/signup."""

    model_config = ConfigDict(extra="ignore")

    email: str = Field(
        ...,
        description="Login email in name@organization.domain form",
        examples=["steward@example.gov.in"],
    )
    password: str = Field(..., min_length=1, description="At least 8 characters")
    name: Optional[str] = Field(None, description="Display name")
    dept: Optional[str] = Field(None, description="Department / unit")


class AuthResponse(BaseModel):
    """Login / signup success payload. Field name ``token`` is required by the UI."""

    model_config = ConfigDict(extra="ignore")

    token: str
    email: str
    name: Optional[str] = None
    dept: Optional[str] = None
    user_id: str
    organisation_id: str
    role: str


class MeResponse(BaseModel):
    """GET /api/me session profile."""

    model_config = ConfigDict(extra="ignore")

    email: str
    name: Optional[str] = None
    dept: Optional[str] = None
    user_id: str
    organisation_id: str
    role: str
