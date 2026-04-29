"""Classify and filter code comments by signal quality."""
from __future__ import annotations

import re
from enum import Enum


class CommentTier(Enum):
    STRUCTURED_DOC = 1
    FILE_HEADER = 2
    BLOCK_COMMENT = 3
    INLINE = 4
    NEVER = 99


_LICENSE_KEYWORDS = frozenset({
    "copyright", "licensed", "license", "apache", "mit license",
    "gpl", "bsd", "mozilla", "all rights reserved",
})

_CODE_KEYWORDS = frozenset({
    "if", "else", "for", "while", "return", "class", "import",
    "def", "function", "var", "let", "const", "new", "try",
    "catch", "throw", "public", "private", "static", "void",
})

_TRIVIAL_PATTERNS = re.compile(
    r"^(increment|decrement|return|set|get|init|todo|fixme|hack|xxx|note)\b",
    re.IGNORECASE,
)

_STRUCTURED_DOC_PATTERNS = re.compile(
    r"(@param|@return|@throws|@type|@property|@see|@since|@deprecated|"
    r":param\s|:returns?:|:raises?:|:type\s|Args:|Returns:|Raises:|Examples?:)",
    re.IGNORECASE,
)


class CommentFilter:
    def classify(self, text: str) -> CommentTier:
        stripped = text.strip()
        if not stripped or len(stripped) < 15:
            return CommentTier.NEVER
        if self._is_license(stripped):
            return CommentTier.NEVER
        if self._is_commented_code(stripped):
            return CommentTier.NEVER
        if self._is_trivial(stripped):
            return CommentTier.NEVER
        if self._is_structured_doc(stripped):
            return CommentTier.STRUCTURED_DOC
        if self._is_file_header(stripped):
            return CommentTier.FILE_HEADER
        if len(stripped) >= 40:
            return CommentTier.BLOCK_COMMENT
        return CommentTier.INLINE

    def _is_structured_doc(self, text: str) -> bool:
        if text.startswith("/**") or text.startswith("///"):
            return True
        if bool(_STRUCTURED_DOC_PATTERNS.search(text)):
            return True
        return False

    def _is_file_header(self, text: str) -> bool:
        lower = text.lower()
        if any(
            kw in lower
            for kw in (
                "module",
                "package",
                "this file",
                "this module",
                "provides",
                "responsible for",
            )
        ):
            if len(text) >= 30:
                return True
        return False

    def _is_license(self, text: str) -> bool:
        lower = text.lower()[:500]
        return sum(1 for kw in _LICENSE_KEYWORDS if kw in lower) >= 2

    def _is_commented_code(self, text: str) -> bool:
        tokens = text.split()
        if not tokens:
            return False
        code_count = sum(1 for t in tokens if t.rstrip("(;){},") in _CODE_KEYWORDS)
        ratio = code_count / len(tokens)
        has_syntax = any(c in text for c in [";", "{", "}", "=>", "->", "==", "!="])
        return ratio > 0.3 or (ratio > 0.15 and has_syntax)

    def _is_trivial(self, text: str) -> bool:
        return bool(_TRIVIAL_PATTERNS.match(text.strip()))
