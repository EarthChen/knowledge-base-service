"""Tests for wiki.code_block_verifier (TDD)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from wiki.code_block_verifier import (
    CodeBlock,
    VerificationStats,
    compute_similarity,
    extract_code_blocks,
    format_code_block,
    infer_language,
    match_snippet,
    parse_code_ref,
    verify_and_inject,
)


class TestParseCodeRef:
    def test_basic_entity_only(self) -> None:
        assert parse_code_ref("<!-- CODE_REF: OrderService -->") == ("OrderService", None)

    def test_with_file_hint(self) -> None:
        e, fh = parse_code_ref("<!-- CODE_REF: FooService @ com/example/Foo.java -->")
        assert e == "FooService"
        assert fh == "com/example/Foo.java"

    def test_with_full_path_hint(self) -> None:
        e, fh = parse_code_ref("<!-- CODE_REF: Bar @ /src/main/kotlin/pkg/Bar.kt -->")
        assert e == "Bar"
        assert fh == "/src/main/kotlin/pkg/Bar.kt"

    def test_whitespace_tolerance(self) -> None:
        e, fh = parse_code_ref("<!--  CODE_REF:  X  @  hint.py  -->")
        assert e == "X"
        assert fh == "hint.py"

    def test_invalid_not_a_marker(self) -> None:
        assert parse_code_ref("plain text") == (None, None)

    def test_invalid_empty(self) -> None:
        assert parse_code_ref("") == (None, None)


class TestExtractCodeBlocks:
    def test_single_block(self) -> None:
        content = "intro\n```python\ndef foo():\n    pass\n```\noutro"
        blocks = extract_code_blocks(content)
        assert len(blocks) == 1
        b = blocks[0]
        assert b.language == "python"
        assert "def foo():" in b.code
        assert content[b.start : b.end].startswith("```")
        assert content[b.start : b.end].endswith("```")

    def test_multiple_blocks(self) -> None:
        content = "```java\nclass A {}\n```\n\n```go\nfunc main() {}\n```"
        blocks = extract_code_blocks(content)
        assert len(blocks) == 2
        assert blocks[0].language == "java"
        assert blocks[1].language == "go"

    def test_none(self) -> None:
        assert extract_code_blocks("no fences here") == []

    def test_position_preservation(self) -> None:
        content = "aaa\n```\nline\n```\nbbb"
        blocks = extract_code_blocks(content)
        assert len(blocks) == 1
        raw = content[blocks[0].start : blocks[0].end]
        assert raw == "```\nline\n```"


class TestComputeSimilarity:
    def test_identical_high(self) -> None:
        code = "public class UserService {\n  void save() {}\n}\n"
        s = compute_similarity(code, code, "UserService")
        assert s > 0.9

    def test_reformatted_still_good(self) -> None:
        a = "public class OrderService {\n  void cancel() {}\n}\n"
        b = "public   class   OrderService  {  void  cancel()  {  }  }"
        s = compute_similarity(a, b, "OrderService")
        assert s > 0.6

    def test_unrelated_low(self) -> None:
        a = "class Alpha { void one() {} }"
        b = "class Beta { void two() {} }"
        s = compute_similarity(a, b, "Gamma")
        assert s < 0.3

    def test_entity_name_substring_boost_over_point_four(self) -> None:
        code = "call MySpecialService now"
        # Small shared token so score is strictly above bare identifier_overlap (0.4).
        snippet = "call unrelated TokenOne TokenTwo"
        s = compute_similarity(code, snippet, "MySpecialService")
        assert s > 0.4


class TestMatchSnippet:
    def test_exact_match_returns_snippet(self) -> None:
        body = "public class X { void m() {} }"
        snip = f"[X @ src/X.java]\n{body}"
        m, score = match_snippet(body, [snip])
        assert m == snip
        assert score >= 0.5

    def test_no_match_returns_none_and_best_score(self) -> None:
        snip = "[Y @ y.py]\nclass Y: pass"
        m, score = match_snippet("totally different noise ZZZ QQQ", [snip])
        assert m is None
        assert score < 0.5


class TestInferLanguage:
    def test_java(self) -> None:
        assert infer_language("com/foo/Bar.java") == "java"

    def test_python(self) -> None:
        assert infer_language("pkg/mod.py") == "python"

    def test_kotlin(self) -> None:
        assert infer_language("src/Foo.kt") == "kotlin"

    def test_unknown(self) -> None:
        assert infer_language("README") == ""
        assert infer_language("file.xyz") == ""


class TestFormatCodeBlock:
    def test_includes_source_comment(self) -> None:
        out = format_code_block("int x = 1;", "Foo", "src/Foo.java", "java")
        assert "// Foo @ src/Foo.java" in out
        assert out.startswith("```java\n")

    def test_truncation(self) -> None:
        many = "\n".join(f"line{i}" for i in range(100))
        out = format_code_block(many, "E", "e.txt", "")
        inner_lines = out.split("\n")
        # opening fence, source line, up to MAX_CODE_LINES-1 body lines, closing
        assert inner_lines.count("line0") == 1
        assert "line99" not in out


@pytest.mark.asyncio
class TestVerifyAndInject:
    async def test_inject_from_snippets_memory(self) -> None:
        snippet = "[OrderService @ svc/Order.java]\npublic class OrderService {}"
        content = "See:\n<!-- CODE_REF: OrderService -->\n"
        new_c, stats = await verify_and_inject(content, [snippet], graph_store=None)
        assert "<!-- CODE_REF:" not in new_c
        assert "OrderService @" in new_c or "svc/Order.java" in new_c
        assert stats.injected == 1
        assert stats.replaced == 0
        assert stats.verified == 0

    async def test_inject_from_graph_when_snippets_miss(self) -> None:
        graph = AsyncMock()
        graph.execute_query.return_value = SimpleNamespace(
            data=[{"code_snippet": "def rare_fn(): pass", "file_path": "lib/rare.py"}]
        )
        content = "<!-- CODE_REF: rare_fn -->\n"
        new_c, stats = await verify_and_inject(content, [], graph_store=graph)
        assert "rare_fn" in new_c
        assert stats.injected == 1
        graph.execute_query.assert_called_once()

    async def test_unresolved_marker_kept(self) -> None:
        content = "<!-- CODE_REF: GhostEntity -->\n"
        new_c, stats = await verify_and_inject(content, [], graph_store=None)
        assert "<!-- CODE_REF: GhostEntity -->" in new_c
        assert stats.injected == 0

    async def test_phase2_replaces_hallucinated_medium_match(self) -> None:
        real = "class Med:\n    def run(self):\n        return 42\n"
        snippet = f"[Med @ m.py]\n{real}"
        # Overlaps Med-related tokens but stays below the 0.9 verified threshold.
        fuzzy = "def run(m: Med):\n    return 40\n"
        content = f"```python\n{fuzzy}\n```"
        new_c, stats = await verify_and_inject(content, [snippet], graph_store=None)
        assert stats.replaced >= 1
        assert "# llm extra" not in new_c
        assert "UNVERIFIED_CODE" not in new_c

    async def test_phase2_keeps_high_match_verified(self) -> None:
        body = "def ok_fn():\n    return 1\n"
        snippet = f"[ok_fn @ ok.py]\n{body}"
        content = f"```python\n{body}\n```"
        new_c, stats = await verify_and_inject(content, [snippet], graph_store=None)
        assert "```python" in new_c
        assert stats.verified >= 1
        assert stats.replaced == 0

    async def test_phase2_marks_unverified(self) -> None:
        snippet = "[Real @ r.py]\nclass Real: pass"
        content = "```python\nclass Fake999:\n    pass\n```"
        new_c, stats = await verify_and_inject(content, [snippet], graph_store=None)
        assert "<!-- UNVERIFIED_CODE -->" in new_c
        assert stats.unverified >= 1

    async def test_multiple_refs(self) -> None:
        s1 = "[A @ a.py]\ncode_a = 1\n"
        s2 = "[B @ b.py]\ncode_b = 2\n"
        content = "<!-- CODE_REF: A -->\n\n<!-- CODE_REF: B -->\n"
        _, stats = await verify_and_inject(content, [s1, s2], graph_store=None)
        assert stats.injected == 2

    async def test_empty_passthrough(self) -> None:
        new_c, stats = await verify_and_inject("", [], None)
        assert new_c == ""
        assert stats == VerificationStats()

    async def test_stats_aggregate(self) -> None:
        assert isinstance(VerificationStats(injected=1, verified=2), VerificationStats)


def test_dataclass_codeblock_fields() -> None:
    cb = CodeBlock(start=1, end=10, language="py", code="")
    assert cb.start == 1
