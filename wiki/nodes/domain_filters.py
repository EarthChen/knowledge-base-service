"""Shared domain classification filters."""
from __future__ import annotations

DATA_MODEL_NAME_SUFFIXES = (
    "DTO", "Dto", "VO", "Vo", "Req", "Resp", "Request", "Response",
    "Param", "Form", "Query", "Result", "Enum", "Constants", "Entity",
    "Bo", "PO", "Po", "Config",
)
DATA_MODEL_PATH_MARKERS = ("/dto/", "/model/", "/entity/", "/enums/", "/config/")

SLUG_DENYLIST: frozenset[str] = frozenset({
    "abs",
    "long",
    "int",
    "void",
    "null",
    "byte",
    "char",
    "short",
    "float",
    "double",
    "boolean",
    "string",
    "object",
    "class",
    "new",
    "this",
    "super",
    "true",
    "false",
    "return",
    "import",
    "package",
    "static",
    "final",
    "public",
    "private",
    "protected",
})


_JAVA_PRIMITIVE_PREFIXES: frozenset[str] = frozenset({
    "long", "int", "byte", "short", "float", "double", "boolean", "void",
    "char", "string", "object",
})


def is_denied_slug(slug: str) -> bool:
    """Return True if slug matches a reserved/primitive type keyword."""
    base = slug.lower().strip()
    if base in SLUG_DENYLIST:
        return True
    first_segment = base.split("-")[0]
    if first_segment in _JAVA_PRIMITIVE_PREFIXES:
        return True
    return False


def is_data_model(name: str, path: str) -> bool:
    """Return True when a module looks like a data/DTO artifact rather than business logic."""
    if any(name.endswith(suffix) for suffix in DATA_MODEL_NAME_SUFFIXES):
        return True
    if any(marker in path.lower() for marker in DATA_MODEL_PATH_MARKERS):
        return True
    return False
