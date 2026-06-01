"""Tests for global stem-suffix domain merge across batches and hierarchy levels."""

from __future__ import annotations

from wiki.nodes.graph_domain_decompose import (
    _cleanup_existing_slug_stems,
    _merge_global_stem_suffix_domains,
)


def test_merge_base_and_service_suffix():
    domain_mapping = {
        "foo": [("repo", "FooCore")],
        "foo-service": [("repo", "FooService")],
    }
    domain_display_names = {
        "foo": "Foo",
        "foo-service": "Foo Service",
    }

    merged_mapping, merged_names = _merge_global_stem_suffix_domains(
        domain_mapping, domain_display_names,
    )

    assert "foo-service" not in merged_mapping
    assert "foo" in merged_mapping
    assert len(merged_mapping["foo"]) == 2
    assert ("repo", "FooCore") in merged_mapping["foo"]
    assert ("repo", "FooService") in merged_mapping["foo"]
    assert "foo" in merged_names


def test_merge_base_and_system_suffix():
    domain_mapping = {
        "bar": [("repo", "BarA")],
        "bar-system": [("repo", "BarB")],
    }
    domain_display_names = {
        "bar": "Bar",
        "bar-system": "Bar System",
    }

    merged_mapping, _ = _merge_global_stem_suffix_domains(domain_mapping, domain_display_names)

    assert "bar-system" not in merged_mapping
    assert len(merged_mapping["bar"]) == 2


def test_skip_numeric_suffix():
    domain_mapping = {
        "foo": [("repo", "FooA")],
        "foo-2": [("repo", "FooB")],
    }
    domain_display_names = {
        "foo": "Foo",
        "foo-2": "Foo Alt",
    }

    merged_mapping, merged_names = _merge_global_stem_suffix_domains(
        domain_mapping, domain_display_names,
    )

    assert "foo" in merged_mapping
    assert "foo-2" in merged_mapping
    assert len(merged_mapping) == 2
    assert merged_names["foo-2"] == "Foo Alt"


def test_keep_larger_display_name():
    domain_mapping = {
        "foo": [("repo", "A")],
        "foo-service": [("repo", "B"), ("repo", "C"), ("repo", "D")],
    }
    domain_display_names = {
        "foo": "Short Name",
        "foo-service": "Longer Descriptive Name",
    }

    _, merged_names = _merge_global_stem_suffix_domains(domain_mapping, domain_display_names)

    assert merged_names["foo"] == "Longer Descriptive Name"


def test_existing_slug_absorbed():
    domain_mapping = {
        "foo-service": [("repo", "Svc")],
    }
    existing = ["foo"]

    cleaned = _cleanup_existing_slug_stems(domain_mapping, existing)

    assert "foo-service" not in cleaned
    assert "foo" in cleaned
    assert ("repo", "Svc") in cleaned["foo"]


def test_no_merge_when_unrelated():
    domain_mapping = {
        "foo": [("repo", "FooA")],
        "bar-service": [("repo", "BarB")],
    }
    domain_display_names = {
        "foo": "Foo",
        "bar-service": "Bar Service",
    }

    merged_mapping, merged_names = _merge_global_stem_suffix_domains(
        domain_mapping, domain_display_names,
    )

    assert len(merged_mapping) == 2
    assert "foo" in merged_mapping
    assert "bar-service" in merged_mapping
    assert merged_names["bar-service"] == "Bar Service"


def test_integration_with_decompose_flow():
    """Simulate cross-batch duplicates surviving per-batch dedup."""
    domain_mapping = {
        "relation-rank": [("repo", "RankCore")],
        "relation-rank-service": [("repo", "RankService")],
        "quick-message": [("repo", "QuickMsg")],
        "other-domain": [("repo", "Other")],
    }
    domain_display_names = {
        "relation-rank": "关系排名",
        "relation-rank-service": "关系排名服务",
        "quick-message": "快捷消息",
        "other-domain": "其他",
    }

    domain_mapping, domain_display_names = _merge_global_stem_suffix_domains(
        domain_mapping, domain_display_names,
    )

    slugs = set(domain_mapping.keys())
    assert "relation-rank-service" not in slugs
    assert "relation-rank" in slugs
    assert len(domain_mapping["relation-rank"]) == 2
    assert len(slugs) == 3

    existing = list(domain_mapping.keys())
    domain_mapping["relation-rank-service"] = [("repo", "RankDao")]
    domain_mapping = _cleanup_existing_slug_stems(domain_mapping, existing)

    assert "relation-rank-service" not in domain_mapping
    assert len(domain_mapping["relation-rank"]) == 3
