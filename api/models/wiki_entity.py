"""API models for wiki ↔ code entity navigation (SOURCE_ENTITY)."""

from __future__ import annotations

from pydantic import BaseModel


class RelatedEntity(BaseModel):
    uid: str
    name: str
    entity_type: str  # Function / Class / Module
    repository: str
    file_path: str
    start_line: int | None = None
    signature: str = ""
    business_summary: str = ""


class WikiPageEntitiesResponse(BaseModel):
    page_path: str
    entities: list[RelatedEntity]
