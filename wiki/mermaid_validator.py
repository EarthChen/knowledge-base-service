"""Mermaid diagram syntax validation using mermaid-syntax-parser."""

from __future__ import annotations

from dataclasses import dataclass

from mermaid_parser import validate_mermaid


@dataclass
class MermaidValidationResult:
    is_valid: bool
    error_message: str | None = None


def validate_mermaid_block(code: str) -> MermaidValidationResult:
    """Validate a single Mermaid diagram block."""
    if not code or not code.strip():
        return MermaidValidationResult(is_valid=False, error_message="Empty diagram")
    try:
        valid = validate_mermaid(code.strip())
        if valid:
            return MermaidValidationResult(is_valid=True)
        return MermaidValidationResult(is_valid=False, error_message="Mermaid syntax validation failed")
    except Exception as e:
        return MermaidValidationResult(is_valid=False, error_message=str(e))
