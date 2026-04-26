"""Tests for wiki.schema_validator."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from wiki.schema_validator import SchemaValidator, resolve_wiki_schema_path


def test_rejects_entity_title_not_matching_naming_pattern(tmp_path: Path) -> None:
    yml = tmp_path / "s.yaml"
    yml.write_text(
        yaml.dump(
            {
                "version": "1.0",
                "page_types": {
                    "entity": {
                        "required_fields": ["title", "content", "type"],
                        "naming_pattern": r"^[A-Z][a-zA-Z0-9_]+$",
                    },
                },
                "conventions": {},
            },
        ),
        encoding="utf-8",
    )
    v = SchemaValidator.from_yaml_path(yml)
    errors = v.validate_page(
        {
            "path": "Foo.md",
            "title": "bad",
            "content": "# x",
            "page_type": "entity",
        },
    )
    assert errors
    assert any("naming_pattern" in e for e in errors)


def test_required_description_section(tmp_path: Path) -> None:
    yml = tmp_path / "s.yaml"
    yml.write_text(
        yaml.dump(
            {
                "version": "1.0",
                "page_types": {"overview": {"required_fields": ["title", "content"]}},
                "conventions": {"required_sections": ["description"]},
            },
        ),
        encoding="utf-8",
    )
    v = SchemaValidator.from_yaml_path(yml)
    err = v.validate_page(
        {
            "path": "a.md",
            "title": "T",
            "content": "# no section here",
            "page_type": "overview",
        },
    )
    assert any("description" in e.lower() for e in err)


def test_business_flow_requires_steps_in_content(tmp_path: Path) -> None:
    yml = tmp_path / "s.yaml"
    yml.write_text(
        yaml.dump(
            {
                "version": "1.0",
                "page_types": {
                    "business_flow": {"required_fields": ["title", "content", "steps"]},
                },
                "conventions": {},
            },
        ),
        encoding="utf-8",
    )
    v = SchemaValidator.from_yaml_path(yml)
    err = v.validate_page(
        {
            "path": "flow.md",
            "title": "Flow",
            "content": "## Overview\nno steps",
            "page_type": "business_flow",
        },
    )
    assert any("steps" in e.lower() for e in err)


def test_valid_page_no_errors(tmp_path: Path) -> None:
    yml = tmp_path / "s.yaml"
    yml.write_text(
        yaml.dump(
            {
                "version": "1.0",
                "page_types": {
                    "entity": {
                        "required_fields": ["title", "content", "type"],
                        "naming_pattern": r"^[A-Z][a-zA-Z0-9_]+$",
                    },
                },
                "conventions": {
                    "max_title_length": 100,
                    "required_sections": ["description"],
                },
            },
        ),
        encoding="utf-8",
    )
    v = SchemaValidator.from_yaml_path(yml)
    content = "## Description\n\nok.\n"
    err = v.validate_page(
        {
            "path": "MyClass.md",
            "title": "MyClass",
            "content": content,
            "page_type": "entity",
        },
    )
    assert err == []


def test_max_title_length(tmp_path: Path) -> None:
    yml = tmp_path / "s.yaml"
    yml.write_text(
        yaml.dump(
            {
                "version": "1.0",
                "page_types": {"overview": {"required_fields": ["title", "content"]}},
                "conventions": {"max_title_length": 5},
            },
        ),
        encoding="utf-8",
    )
    v = SchemaValidator.from_yaml_path(yml)
    err = v.validate_page(
        {
            "path": "a.md",
            "title": "123456",
            "content": "x",
            "page_type": "overview",
        },
    )
    assert any("max_title_length" in e for e in err)


def test_resolve_wiki_schema_path_default() -> None:
    p = resolve_wiki_schema_path("wiki/schema.yaml")
    assert p.is_absolute()
    assert p.name == "schema.yaml"
    assert p.parent.name == "wiki"


def test_package_schema_yaml_loads() -> None:
    p = resolve_wiki_schema_path("wiki/schema.yaml")
    assert p.exists(), f"missing {p}"
    v = SchemaValidator.from_yaml_path(p)
    assert v.raw.get("version") == "1.0"
