"""Tests for configuration file indexing (YAML, XML, properties, env, TOML)."""

import hashlib
from pathlib import Path

import pytest

from indexer.config_indexer import ConfigIndexer
from indexer.doc_indexer import DocumentIndexer, DocumentSection, ParsedDocument
from store.schema import EdgeType, NodeLabel


def sha16(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


@pytest.fixture
def cfg_indexer() -> ConfigIndexer:
    return ConfigIndexer()


@pytest.fixture
def doc_indexer() -> DocumentIndexer:
    return DocumentIndexer()


class TestYamlParsing:
    def test_top_level_keys_become_sections(self, cfg_indexer: ConfigIndexer, tmp_path: Path):
        content = """app:\n  name: demo\n  port: 8080\nlogging:\n  level: INFO\n"""
        p = tmp_path / "cfg.yml"
        p.write_text(content, encoding="utf-8")
        doc = cfg_indexer.parse_config(str(p), store_path="cfg.yml")

        assert isinstance(doc, ParsedDocument)
        titles = {s.title for s in doc.sections}
        assert titles == {"app", "logging"}
        assert doc.content_hash == sha16(content)
        assert any("8080" in s.content for s in doc.sections if s.title == "app")

    def test_yaml_non_mapping_root_single_section(self, cfg_indexer: ConfigIndexer, tmp_path: Path):
        content = "- a\n- b\n"
        p = tmp_path / "list.yml"
        p.write_text(content, encoding="utf-8")
        doc = cfg_indexer.parse_config(str(p))
        assert len(doc.sections) == 1
        assert doc.sections[0].title == "document"


class TestXmlParsing:
    def test_root_children_become_sections(self, cfg_indexer: ConfigIndexer, tmp_path: Path):
        content = """<?xml version="1.0"?>\n<root><server host="h1"/><db name="x"/></root>\n"""
        p = tmp_path / "cfg.xml"
        p.write_text(content, encoding="utf-8")
        doc = cfg_indexer.parse_config(str(p))

        titles = {s.title for s in doc.sections}
        assert titles == {"server", "db"}
        for s in doc.sections:
            assert "<" in s.content and s.start_line >= 1
            assert s.end_line >= s.start_line


class TestPropertiesParsing:
    def test_group_by_common_prefix(self, cfg_indexer: ConfigIndexer, tmp_path: Path):
        content = """spring.datasource.url=jdbc:h2:mem:test\nspring.datasource.username=sa\napp.name=demo\n"""
        p = tmp_path / "app.properties"
        p.write_text(content, encoding="utf-8")
        doc = cfg_indexer.parse_config(str(p))

        titles = {s.title for s in doc.sections}
        assert "spring.datasource" in titles
        ds_sections = [s for s in doc.sections if s.title == "spring.datasource"]
        assert len(ds_sections) == 1
        assert "url=jdbc" in ds_sections[0].content
        assert "username=sa" in ds_sections[0].content


class TestEnvParsing:
    def test_key_value_sections(self, cfg_indexer: ConfigIndexer, tmp_path: Path):
        content = "# comment\n\nFOO=1\nBAR=two\n"
        p = tmp_path / ".env"
        p.write_text(content, encoding="utf-8")
        doc = cfg_indexer.parse_config(str(p))

        titles = {s.title for s in doc.sections}
        assert titles >= {"FOO", "BAR"}


class TestTomlParsing:
    def test_tables_as_sections(self, cfg_indexer: ConfigIndexer, tmp_path: Path):
        content = """name = "root"\n\n[server]\nhost = "localhost"\nport = 80\n\n[db]\npath = "/data"\n"""
        p = tmp_path / "cfg.toml"
        p.write_text(content, encoding="utf-8")
        doc = cfg_indexer.parse_config(str(p))

        titles = {s.title for s in doc.sections}
        assert "server" in titles
        assert "db" in titles
        assert any(s.title == "server" and "localhost" in s.content for s in doc.sections)


class TestContentHash:
    def test_same_content_same_hash(self, cfg_indexer: ConfigIndexer, tmp_path: Path):
        text = "k: v\n"
        a = tmp_path / "a.yml"
        b = tmp_path / "b.yaml"
        a.write_text(text, encoding="utf-8")
        b.write_text(text, encoding="utf-8")
        da = cfg_indexer.parse_config(str(a))
        db = cfg_indexer.parse_config(str(b))
        assert da.content_hash == db.content_hash == sha16(text)


class TestEmptyFile:
    def test_empty_returns_no_sections(self, cfg_indexer: ConfigIndexer, tmp_path: Path):
        p = tmp_path / "empty.yml"
        p.write_text("", encoding="utf-8")
        doc = cfg_indexer.parse_config(str(p))
        assert doc.sections == []
        assert doc.content_hash == sha16("")


class TestIntegrationSupportedExtensions:
    def test_document_indexer_includes_config_extensions(self):
        exts = DocumentIndexer.SUPPORTED_EXTENSIONS
        for ext in (".yml", ".yaml", ".xml", ".properties", ".env", ".toml", ".conf"):
            assert ext in exts

    def test_document_indexer_delegates_yaml(self, doc_indexer: DocumentIndexer, tmp_path: Path):
        p = tmp_path / "x.yml"
        p.write_text("k: 1\n", encoding="utf-8")
        doc = doc_indexer.parse_document(str(p), store_path="x.yml")
        assert len(doc.sections) >= 1
        assert doc.title == "x"


class TestBuildGraph:
    def test_nodes_and_contains_edges(self, cfg_indexer: ConfigIndexer):
        doc = ParsedDocument(
            title="t",
            path="p.yml",
            content_hash="abcd",
            sections=[
                DocumentSection(
                    title="sec",
                    content="body",
                    level=2,
                    start_line=1,
                    end_line=3,
                )
            ],
        )
        nodes, edges = cfg_indexer.build_graph(doc)
        roots = [n for n in nodes if n.label == NodeLabel.DOCUMENT and "section" not in n.properties]
        children = [n for n in nodes if n.properties.get("section") == "sec"]
        assert len(roots) == 1
        assert children
        assert all(e.edge_type == EdgeType.CONTAINS for e in edges)
        assert edges[0].source_uid == roots[0].uid


class TestMalformedXml:
    def test_malformed_xml_returns_empty_sections(self, cfg_indexer: ConfigIndexer, tmp_path: Path):
        p = tmp_path / "bad.xml"
        p.write_text("<root><unclosed", encoding="utf-8")
        doc = cfg_indexer.parse_config(str(p))
        assert doc.sections == []


class TestConfExtension:
    def test_conf_file_parsed_as_properties_style(self, cfg_indexer: ConfigIndexer, tmp_path: Path):
        p = tmp_path / "daemon.conf"
        p.write_text("server.port=1234\n", encoding="utf-8")
        doc = cfg_indexer.parse_config(str(p))
        assert doc.sections
        joined = " ".join(s.content + " " + s.title for s in doc.sections)
        assert "1234" in joined
