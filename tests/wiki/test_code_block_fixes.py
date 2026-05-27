"""Tests for F5 (MAX_CODE_LINES) and F6 (fence parser) fixes."""

from __future__ import annotations

from wiki.code_block_verifier import MAX_CODE_LINES, format_code_block
from wiki.nodes.finalize import _strip_fake_source_lines


class TestMaxCodeLines:
    def test_max_code_lines_is_80(self) -> None:
        assert MAX_CODE_LINES == 80

    def test_format_code_block_allows_60_lines(self) -> None:
        code = "\n".join(f"line{i}" for i in range(60))
        out = format_code_block(code, "Entity", "src/Entity.java", "java")
        for i in range(60):
            assert f"line{i}" in out


class TestStripFakeSourceLines:
    def test_strip_fake_source_removes_fake_blocks(self) -> None:
        content = """# Title

```java
// com/xxx/Fake.java
public class Fake {}
```

Normal paragraph.
"""
        result = _strip_fake_source_lines(content)
        assert "com/xxx/" not in result
        assert "public class Fake" not in result
        assert "Normal paragraph." in result

    def test_strip_fake_source_preserves_normal_blocks(self) -> None:
        content = """# Title

```java
// com/example/Real.java
public class Real {}
```

Normal paragraph.
"""
        result = _strip_fake_source_lines(content)
        assert "public class Real {}" in result
        assert "Normal paragraph." in result

    def test_strip_fake_source_handles_adjacent_fences(self) -> None:
        content = """```java
class A {}
```
```java
class B {}
```
"""
        result = _strip_fake_source_lines(content)
        assert "class A {}" in result
        assert "class B {}" in result

    def test_strip_fake_source_handles_closing_only(self) -> None:
        content = """```java
class C {}
```
"""
        result = _strip_fake_source_lines(content)
        assert "class C {}" in result
        assert result.count("```") == 2

    def test_strip_fake_source_lines_bare_fence(self) -> None:
        content = """# Title

```
public class Example {
    void run() {}
}
```

Normal paragraph.
"""
        result = _strip_fake_source_lines(content)
        assert "public class Example" in result
        assert "void run()" in result
        assert result.count("```") == 2
        assert "Normal paragraph." in result

    def test_strip_fake_source_lines_bare_fence_fake_block_removed_whole(self) -> None:
        content = """```
// com/xxx/Fake.java
public class Fake {}
```"""
        result = _strip_fake_source_lines(content)
        assert "com/xxx" not in result
        assert "public class Fake" not in result
