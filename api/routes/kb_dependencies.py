"""FastAPI dependencies for Knowledge Base API routes (formerly in ``main``)."""

from __future__ import annotations

from fastapi import Depends, Header

import api.kb_state as kb_state
from api.exceptions import KbNotFound, KbServiceUnavailable
from core.auth import (
    TokenInfo,
    resolve_business_id,
    resolve_token,
)
from services.kb_service import KnowledgeBaseService


def resolve_token_header(authorization: str | None = Header(default=None)) -> TokenInfo | None:
    return resolve_token(authorization)


def get_effective_business_id(
    token_info: TokenInfo | None = Depends(resolve_token_header),
    x_business_id: str = Header(default="default"),
) -> str:
    return resolve_business_id(token_info, x_business_id)


async def get_service(
    business_id: str = Depends(get_effective_business_id),
) -> KnowledgeBaseService:
    if kb_state.registry is None:
        raise KbServiceUnavailable("Service not ready")
    try:
        return await kb_state.registry.get_service(business_id)
    except ValueError as exc:
        raise KbNotFound(str(exc)) from exc
