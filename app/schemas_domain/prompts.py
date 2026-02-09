from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class QualityRulesRequest(BaseModel):
    rules: Dict[str, Any]


class QualityRulesResponse(BaseModel):
    rules: Dict[str, Any]


class PromptVersionInfo(BaseModel):
    id: int
    prompt_id: int
    version_index: int
    content: str
    notes: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None


class PromptInfo(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    latest_version: Optional[PromptVersionInfo] = None
    versions: List[PromptVersionInfo] = Field(default_factory=list)


class PromptListResponse(BaseModel):
    prompts: List[PromptInfo]
    active_prompt_id: Optional[int] = None


class PromptCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    content: str
    notes: Optional[str] = None
    activate: bool = False
    created_by: Optional[str] = None


class PromptVersionCreateRequest(BaseModel):
    content: str
    notes: Optional[str] = None
    created_by: Optional[str] = None
