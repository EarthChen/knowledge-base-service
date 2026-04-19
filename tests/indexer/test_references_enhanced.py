"""P5.B: REFERENCES extraction and resolution (FQN, directory proximity, name fallback)."""

import re
from unittest.mock import MagicMock

import pytest

from indexer.doc_indexer import DocumentIndexer
from store.falkordb_store import FalkorDBStore, REFERENCES_CROSS_FILE_CYPHER


class TestExtractCodeReferencesEnhanced:
    def test_preserves_full_qualified_form(self) -> None:
        content = "Call `Foo.bar` for the hook."
        refs = DocumentIndexer._extract_code_references(content)
        assert "Foo.bar" in refs

    def test_also_includes_simple_name(self) -> None:
        content = "Call `Foo.bar` for the hook."
        refs = DocumentIndexer._extract_code_references(content)
        assert "bar" in refs

    def test_simple_identifier_only_once(self) -> None:
        content = "Use `authenticate`."
        refs = DocumentIndexer._extract_code_references(content)
        assert refs == ["authenticate"]

    def test_multiple_qualified_refs(self) -> None:
        content = "See `A.b` and `C.d.e`."
        refs = DocumentIndexer._extract_code_references(content)
        assert "A.b" in refs and "b" in refs
        assert "C.d.e" in refs and "e" in refs


class TestReferencesCrossFileCypher:
    """Resolution order in Cypher: FQN → directory + name → name-only."""

    def test_fqn_match_before_directory_proximity_before_name_only(self) -> None:
        q = REFERENCES_CROSS_FILE_CYPHER
        i_fqn = re.search(r"f1\.fqn\s*=\s*ref", q)
        i_dir = q.find("STARTS WITH doc_dir")
        i_name_only = q.find("size(dir_hits) = 0 AND f3.name = ref")
        assert i_fqn is not None and i_dir != -1 and i_name_only != -1
        assert i_fqn.start() < i_dir < i_name_only

    def test_references_resolution_fqn_exact_match_takes_priority(self) -> None:
        """Tier 1: match code entity by ``fqn`` equal to the reference string."""
        q = REFERENCES_CROSS_FILE_CYPHER
        assert re.search(r"f1\.fqn\s*=\s*ref", q)
        assert re.search(r"c1\.fqn\s*=\s*ref", q)

    def test_references_resolution_name_and_directory_proximity(self) -> None:
        """Tier 2: same simple ``name`` as ``ref`` and code ``file`` under the doc's directory prefix."""
        q = REFERENCES_CROSS_FILE_CYPHER
        assert "f2.name = ref" in q and "f2.file STARTS WITH doc_dir" in q
        assert "c2.name = ref" in q and "c2.file STARTS WITH doc_dir" in q
        assert "size(fqn_hits) = 0" in q

    def test_references_resolution_simple_name_fallback(self) -> None:
        """Tier 3: when no FQN or directory-scoped hits, match any Function/Class by ``name`` (prior behavior)."""
        q = REFERENCES_CROSS_FILE_CYPHER
        assert "f3.name = ref" in q and "c3.name = ref" in q
        assert "size(fqn_hits) = 0 AND size(dir_hits) = 0" in q

    def test_no_duplicate_references_edges_same_doc_entity_pair(self) -> None:
        """Single MERGE per (d, t) row prevents duplicate REFERENCES relationships."""
        q = REFERENCES_CROSS_FILE_CYPHER
        assert q.count("MERGE (d)-[:REFERENCES]->(t)") == 1


@pytest.mark.asyncio
class TestResolveCrossFileEdgesReferencesQuery:
    async def test_references_step_uses_enhanced_cypher(self) -> None:
        queries: list[str] = []

        def fake_query(q: str, params: dict | None = None):
            queries.append(q)
            m = MagicMock()
            m.result_set = [[0]]
            return m

        store = FalkorDBStore.__new__(FalkorDBStore)
        store._config = None
        store._embedding_dim = 1024
        store._db = None
        store._owns_connection = True
        store._graph = MagicMock()
        store._graph.query = fake_query

        await store.resolve_cross_file_edges()

        ref_rebuild = [q for q in queries if "MERGE (d)-[:REFERENCES]->(t)" in q]
        assert len(ref_rebuild) == 1
        assert ref_rebuild[0].strip() == REFERENCES_CROSS_FILE_CYPHER
