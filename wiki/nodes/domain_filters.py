"""Shared domain classification filters."""
from __future__ import annotations

DATA_MODEL_NAME_SUFFIXES = (
    "DTO", "Dto", "VO", "Vo", "Req", "Resp", "Request", "Response",
    "Param", "Form", "Query", "Result", "Enum", "Constants", "Entity",
    "Bo", "PO", "Po", "Config",
)
DATA_MODEL_PATH_MARKERS = ("/dto/", "/model/", "/entity/", "/enums/", "/config/")


def is_data_model(name: str, path: str) -> bool:
    """Return True when a module looks like a data/DTO artifact rather than business logic."""
    if any(name.endswith(suffix) for suffix in DATA_MODEL_NAME_SUFFIXES):
        return True
    if any(marker in path.lower() for marker in DATA_MODEL_PATH_MARKERS):
        return True
    return False
