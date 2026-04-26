"""YAML-driven validation for wiki pages (conventions + per page_type rules)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

import wiki


def resolve_wiki_schema_path(config_path: str) -> Path:
    """Map config default ``wiki/schema.yaml`` to the packaged file under ``wiki/``."""
    pkg = Path(wiki.__file__).resolve().parent
    p = Path(config_path)
    if p.is_absolute():
        return p
    if str(config_path).replace("\\", "/") in {"wiki/schema.yaml", "schema.yaml"}:
        return pkg / "schema.yaml"
    candidate = (Path.cwd() / config_path).resolve()
    if candidate.exists():
        return candidate
    return pkg / "schema.yaml"


def _content_has_heading(content: str, name: str) -> bool:
    n = re.escape(name)
    return bool(
        re.search(rf"(?m)^#{{1,6}}\s*{n}\s*$", content, re.IGNORECASE),
    )


def _content_has_steps(content: str) -> bool:
    c = content or ""
    if re.search(r"(?m)^#+\s*steps\s*$", c, re.IGNORECASE):
        return True
    if re.search(r"(?m)^\s*1[.)]\s+\S", c):
        return True
    if re.search(r"(?m)^\s*[-*]\s+\S", c):
        return True
    return False


class SchemaValidator:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self._page_types: dict[str, Any] = dict(raw.get("page_types") or {})
        self._conv: dict[str, Any] = dict(raw.get("conventions") or {})

    @classmethod
    def from_yaml_path(cls, path: Path) -> SchemaValidator:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(data if isinstance(data, dict) else {})

    def validate_page(self, page: dict[str, Any]) -> list[str]:
        """Return human-readable validation errors (empty if valid or no rules for this type)."""
        errors: list[str] = []
        pt = str(page.get("page_type") or "").strip()
        if not pt:
            return ["page_type: missing or empty"]
        spec = self._page_types.get(pt)
        if spec is None:
            return []

        req = spec.get("required_fields") or []
        for f in req:
            if f == "type":
                if not str(page.get("page_type") or "").strip():
                    errors.append("required field 'type' (page_type) missing or empty")
            elif f == "steps":
                if not _content_has_steps(str(page.get("content") or "")):
                    errors.append("required field 'steps' not found in content (heading or list)")
            else:
                v = page.get(f)
                if f in ("content", "title", "path"):
                    if v is None or not str(v).strip():
                        errors.append(f"required field '{f}' missing or empty")
                elif not v and v != 0 and v is not False:
                    errors.append(f"required field '{f}' missing or empty")

        pat = spec.get("naming_pattern")
        if pat:
            title = str(page.get("title") or "")
            if not re.fullmatch(pat, title):
                errors.append(
                    f"title: does not match naming_pattern {pat!r}",
                )

        max_title = self._conv.get("max_title_length")
        if max_title is not None:
            title = str(page.get("title") or "")
            if len(title) > int(max_title):
                errors.append("title: exceeds conventions.max_title_length")
        max_content = self._conv.get("max_content_length")
        if max_content is not None:
            content = str(page.get("content") or "")
            if len(content) > int(max_content):
                errors.append("content: exceeds conventions.max_content_length")

        for sec in self._conv.get("required_sections") or []:
            s = str(sec)
            if not _content_has_heading(str(page.get("content") or ""), s):
                errors.append(
                    f"content: required section {s!r} (markdown heading) not found",
                )
        return errors
