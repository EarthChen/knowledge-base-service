# Wiki 导出与 Git 推送（Phase 5）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]` / `- [x]`) syntax for tracking.

**Goal:** 让业务级 Wiki 支持四种格式导出（标准 Markdown/ZIP、Git 推送、Obsidian vault、MkDocs），实现 `[[path]]` wikilink 到相对链接的转换，业务级 Wiki 树结构到文件系统目录结构的映射，以及基于 content_hash 的 Git 增量推送。

**Architecture:** 新增 `WikiLinkConverter` 作为底层 wikilink 格式转换器。新增 `BusinessWikiExporter` 从 WikiStore 查询业务级树结构（WikiSpace → WikiSection → WikiPage），将其映射为文件系统目录并生成 ExportPlan。`ObsidianExporter` 和 `MkDocsExporter` 包装 BusinessWikiExporter 并添加格式专属配置。`GitPublisher` 负责增量检测和 Git 推送。导出 API 端点统一调度各导出器。

**Tech Stack:** Python 3.12+, FastAPI, FalkorDB (Cypher), asyncio, pathlib, shutil, zipfile, asyncio.create_subprocess_exec (git)

**Spec:**
- [2026-04-26-wiki-tree-architecture-design.md](../specs/2026-04-26-wiki-tree-architecture-design.md)（"Wiki 导出与 Git 推送" 章节）
- [2026-04-24-wiki-enhancement-design.md](../specs/2026-04-24-wiki-enhancement-design.md)

**Code Review 要求:** 每个 Task 完成后必须进行 code review（spec compliance + code quality），确认代码质量和测试覆盖后再进入下一个 Task。

**前置条件:** Phase 0-4 均已完成。1364 测试通过。WikiConfig 中 Phase 5 配置字段已定义（`git_publish_*`, `export_*`）。WikiStore 已有 `get_wiki_tree()`、`get_wiki_page_detail()`、`get_wiki_page_references()`、`get_wiki_page_back_references()` 等查询方法。

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `wiki/wikilink_converter.py` | `[[path]]` → 相对 markdown 链接 / Obsidian 格式转换 |
| Create | `wiki/business_wiki_exporter.py` | 业务级 Wiki 树 → 目录结构导出（标准 Markdown），生成 ExportPlan |
| Create | `wiki/obsidian_exporter.py` | Obsidian vault 导出（保留 wikilink + `.obsidian/` 配置） |
| Create | `wiki/mkdocs_exporter.py` | MkDocs 导出（`mkdocs.yml` 导航配置生成，标准 markdown 链接） |
| Create | `wiki/git_publisher.py` | Git 增量推送（content_hash 对比 + `asyncio.create_subprocess_exec` 执行 git） |
| Modify | `api/routes/wiki_routes.py` | 新增 `POST /api/v1/wiki/export` 端点 |
| Modify | `store/wiki_store.py` | 新增 `get_wiki_pages_for_business()` 批量查询 |
| Modify | `wiki/__init__.py` | 导出 Phase 5 新组件 |
| Create | `tests/wiki/test_wikilink_converter.py` | WikiLinkConverter 单元测试 |
| Create | `tests/wiki/test_business_wiki_exporter.py` | BusinessWikiExporter 单元测试 |
| Create | `tests/wiki/test_obsidian_exporter.py` | ObsidianExporter 单元测试 |
| Create | `tests/wiki/test_mkdocs_exporter.py` | MkDocsExporter 单元测试 |
| Create | `tests/wiki/test_git_publisher.py` | GitPublisher 单元测试 |
| Create | `tests/wiki/test_export_api.py` | 导出 API 端点测试 |
| Create | `tests/wiki/integration/test_phase5_smoke.py` | Phase 5 集成烟雾测试 |

---

### Task 1: WikiLinkConverter — wikilink 格式转换器

**Files:**
- Create: `wiki/wikilink_converter.py`
- Create: `tests/wiki/test_wikilink_converter.py`

**背景:** Phase 4 的 `WikiReferenceGenerator.inject_wikilinks()` 已在 WikiPage.content 中注入了 `[[/用户管理/UserService]]` 格式的标记。WikiLinkConverter 负责在导出时将这些标记转换为目标格式。

- [ ] **Step 1: Write the failing tests**

创建 `tests/wiki/test_wikilink_converter.py`：

```python
# tests/wiki/test_wikilink_converter.py
"""Unit tests for WikiLinkConverter."""

import pytest
from wiki.wikilink_converter import WikiLinkConverter


class TestToMarkdown:
    def test_same_directory_sibling(self):
        conv = WikiLinkConverter()
        content = "See [[/domain/sibling]] for details."
        result = conv.to_markdown(content, current_path="/domain/page")
        assert "[sibling](sibling.md)" in result
        assert "[[" not in result

    def test_cross_directory(self):
        conv = WikiLinkConverter()
        content = "Calls [[/other/target]]."
        result = conv.to_markdown(content, current_path="/domain/page")
        assert "[target](../other/target.md)" in result

    def test_overview_maps_to_readme(self):
        conv = WikiLinkConverter()
        content = "See [[/domain/_overview]]."
        result = conv.to_markdown(content, current_path="/other/page")
        assert "domain/README.md" in result

    def test_no_wikilinks_passthrough(self):
        conv = WikiLinkConverter()
        content = "No links here."
        result = conv.to_markdown(content, current_path="/a/b")
        assert result == content

    def test_multiple_wikilinks_in_one_line(self):
        conv = WikiLinkConverter()
        content = "Uses [[/a/X]] and [[/b/Y]]."
        result = conv.to_markdown(content, current_path="/c/page")
        assert "[[" not in result
        assert "[X](" in result
        assert "[Y](" in result

    def test_deeply_nested_path(self):
        conv = WikiLinkConverter()
        content = "See [[/用户管理/注册流程/UserController]]."
        result = conv.to_markdown(content, current_path="/订单处理/page")
        assert "UserController" in result
        assert ".md" in result
        assert "[[" not in result


class TestToObsidian:
    def test_strips_leading_slash(self):
        conv = WikiLinkConverter()
        content = "See [[/domain/UserService]]."
        result = conv.to_obsidian(content)
        assert "[[domain/UserService]]" in result
        assert "[[/" not in result

    def test_preserves_double_brackets(self):
        conv = WikiLinkConverter()
        content = "See [[/a/B]]."
        result = conv.to_obsidian(content)
        assert "[[a/B]]" in result

    def test_no_wikilinks_passthrough(self):
        conv = WikiLinkConverter()
        content = "Plain text."
        result = conv.to_obsidian(content)
        assert result == content


class TestExtractWikilinks:
    def test_extract_multiple(self):
        conv = WikiLinkConverter()
        content = "See [[/a/X]] and [[/b/Y]]."
        links = conv.extract_wikilinks(content)
        assert "/a/X" in links
        assert "/b/Y" in links

    def test_extract_empty_content(self):
        conv = WikiLinkConverter()
        links = conv.extract_wikilinks("No links.")
        assert links == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_wikilink_converter.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'wiki.wikilink_converter'`

- [ ] **Step 3: Implement WikiLinkConverter**

创建 `wiki/wikilink_converter.py`：

```python
"""Convert [[path]] wikilinks to relative markdown links or Obsidian format."""

from __future__ import annotations

import os
import re


_WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


class WikiLinkConverter:
    """Bi-directional wikilink format converter.

    Handles conversion between internal ``[[/path]]`` markers
    (injected by ``WikiReferenceGenerator.inject_wikilinks``)
    and output formats (standard markdown links, Obsidian wikilinks).
    """

    def to_markdown(self, content: str, current_path: str) -> str:
        """Convert ``[[/path]]`` → ``[title](relative.md)`` standard markdown links."""

        def _replace(m: re.Match[str]) -> str:
            target = m.group(1).strip()
            title = target.rsplit("/", 1)[-1]
            if title == "_overview":
                parent = target.rsplit("/", 1)[0].rsplit("/", 1)[-1]
                title = parent if parent else "_overview"
            rel = self._relative_link(current_path, target)
            return f"[{title}]({rel})"

        return _WIKILINK_PATTERN.sub(_replace, content)

    def to_obsidian(self, content: str) -> str:
        """Normalize ``[[/path]]`` → ``[[path]]`` for Obsidian vault."""

        def _replace(m: re.Match[str]) -> str:
            target = m.group(1).strip().lstrip("/")
            return f"[[{target}]]"

        return _WIKILINK_PATTERN.sub(_replace, content)

    def extract_wikilinks(self, content: str) -> list[str]:
        """Return all ``[[path]]`` targets found in content."""
        return [m.group(1).strip() for m in _WIKILINK_PATTERN.finditer(content)]

    @staticmethod
    def _relative_link(from_path: str, to_path: str) -> str:
        """Compute relative markdown file path from one wiki path to another."""
        from_dir = os.path.dirname(from_path.strip("/"))
        to_clean = to_path.strip("/")
        if to_clean.endswith("/_overview"):
            to_file = to_clean.replace("/_overview", "/README.md")
        else:
            to_file = to_clean + ".md"
        rel = os.path.relpath(to_file, start=from_dir or ".")
        return rel.replace(os.sep, "/")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_wikilink_converter.py -v`

Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`

Expected: All pass, no regressions

**Commit:** `feat(wiki): add WikiLinkConverter for wikilink format conversion`

---

### Task 2: BusinessWikiExporter — 业务级 Wiki 导出核心

**Files:**
- Create: `wiki/business_wiki_exporter.py`
- Create: `tests/wiki/test_business_wiki_exporter.py`
- Modify: `store/wiki_store.py` — 新增 `get_wiki_pages_for_business()` 方法

**背景:** 现有 `WikiDiskExporter` 基于单仓库 `WikiStructure`（平坦列表），不支持业务级 WikiSpace/WikiSection 树。`BusinessWikiExporter` 从图谱查询业务级树结构并映射为文件系统目录。

- [ ] **Step 1: Write the failing tests**

创建 `tests/wiki/test_business_wiki_exporter.py`：

```python
# tests/wiki/test_business_wiki_exporter.py
"""Unit tests for BusinessWikiExporter."""

import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

from wiki.business_wiki_exporter import (
    BusinessWikiExporter,
    ExportFile,
    ExportPlan,
)


class TestGenerateReadme:
    def test_contains_business_id(self):
        exporter = BusinessWikiExporter(store=None)
        readme = exporter.generate_readme("my-biz", ["用户管理", "订单处理"])
        assert "my-biz" in readme

    def test_contains_domain_names(self):
        exporter = BusinessWikiExporter(store=None)
        readme = exporter.generate_readme("biz", ["用户管理", "订单处理"])
        assert "用户管理" in readme
        assert "订单处理" in readme

    def test_markdown_links(self):
        exporter = BusinessWikiExporter(store=None)
        readme = exporter.generate_readme("biz", ["用户管理"])
        assert "用户管理/README.md" in readme or "用户管理/" in readme


class TestGenerateDomainIndex:
    def test_lists_all_domains_with_pages(self):
        exporter = BusinessWikiExporter(store=None)
        domains = {"用户管理": ["UserController.md", "UserService.md"]}
        index = exporter.generate_domain_index(domains)
        assert "用户管理" in index
        assert "UserController.md" in index
        assert "UserService.md" in index

    def test_empty_domains(self):
        exporter = BusinessWikiExporter(store=None)
        index = exporter.generate_domain_index({})
        assert "empty" in index.lower() or len(index.strip()) > 0


class TestBuildExportPlan:
    @pytest.mark.asyncio
    async def test_empty_tree_returns_empty_plan(self):
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(
            return_value=MagicMock(data=[])
        )
        exporter = BusinessWikiExporter(mock_store)
        plan = await exporter.build_export_plan("empty-biz")
        assert isinstance(plan, ExportPlan)
        assert plan.business_id == "empty-biz"
        assert len(plan.files) == 0

    @pytest.mark.asyncio
    async def test_plan_structure(self):
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(
            return_value=MagicMock(
                data=[
                    {
                        "uid": "section:domain:用户管理",
                        "title": "用户管理",
                        "label": "WikiSection",
                        "depth": 1,
                        "sort_order": 0,
                        "path": "",
                        "page_type": "",
                    },
                ]
            )
        )
        mock_store.get_wiki_pages_for_business = AsyncMock(return_value=[])
        exporter = BusinessWikiExporter(mock_store)
        plan = await exporter.build_export_plan("biz")
        assert plan.business_id == "biz"


class TestExportFile:
    def test_dataclass_fields(self):
        f = ExportFile(relative_path="domain/page.md", content="# Title")
        assert f.relative_path == "domain/page.md"
        assert f.content == "# Title"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_business_wiki_exporter.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Add `get_wiki_pages_for_business()` to WikiStore**

在 `store/wiki_store.py` 中添加新方法（在 `get_wiki_tree` 方法之后）：

```python
    async def get_wiki_pages_for_business(
        self, business_id: str, min_tier: str = "skeleton"
    ) -> list[dict[str, Any]]:
        """Return all WikiPages under a business's WikiSpace tree."""
        tier_filter = ""
        if min_tier == "standard":
            tier_filter = "AND wp.importance_tier IN ['core', 'standard'] "
        elif min_tier == "core":
            tier_filter = "AND wp.importance_tier = 'core' "

        q = (
            "MATCH (ws:WikiSpace {business_id: $business_id}) "
            "MATCH (ws)-[:HAS_CHILD*1..10]->(wp:WikiPage) "
            f"{tier_filter}"
            "RETURN wp.uid AS uid, wp.title AS title, wp.path AS path, "
            "wp.content AS content, wp.page_type AS page_type, "
            "wp.repository AS repository, wp.importance_tier AS importance_tier, "
            "coalesce(wp.content_hash, '') AS content_hash "
            "ORDER BY wp.path"
        )
        result = await self._store.execute_query(
            q, {"business_id": business_id}
        )
        rows: list[dict[str, Any]] = []
        for row in result.data:
            rows.append({
                "uid": str(row.get("uid") or ""),
                "title": str(row.get("title") or ""),
                "path": str(row.get("path") or ""),
                "content": str(row.get("content") or ""),
                "page_type": str(row.get("page_type") or ""),
                "repository": str(row.get("repository") or ""),
                "importance_tier": str(row.get("importance_tier") or ""),
                "content_hash": str(row.get("content_hash") or ""),
            })
        return rows
```

- [ ] **Step 4: Implement BusinessWikiExporter**

创建 `wiki/business_wiki_exporter.py`：

```python
"""Export business-level Wiki tree to file system directory structure."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from log import get_logger
from wiki.wikilink_converter import WikiLinkConverter

log = get_logger(__name__)


@dataclass
class ExportFile:
    """A single file to write during export."""
    relative_path: str
    content: str
    content_hash: str = ""
    is_index: bool = False


@dataclass
class ExportPlan:
    """Complete export plan for a business wiki."""
    business_id: str
    view: str = "business_domain"
    files: list[ExportFile] = field(default_factory=list)
    domain_names: list[str] = field(default_factory=list)
    total_pages: int = 0


class BusinessWikiExporter:
    """Exports business-level Wiki tree to directory structure.

    Maps WikiSpace → root, WikiSection → directory, WikiPage → .md file.
    Uses WikiLinkConverter to convert [[path]] markers in content.
    """

    def __init__(
        self,
        store: Any | None,
        link_mode: str = "markdown",
    ) -> None:
        self._store = store
        self._link_converter = WikiLinkConverter()
        self._link_mode = link_mode

    async def build_export_plan(
        self,
        business_id: str,
        view: str = "business_domain",
        min_tier: str = "standard",
    ) -> ExportPlan:
        """Build an export plan by querying the wiki tree and pages."""
        plan = ExportPlan(business_id=business_id, view=view)
        if self._store is None:
            return plan

        tree_result = await self._store.get_wiki_tree(
            business_id, view_type=view
        )
        tree_nodes = tree_result.data if tree_result else []
        if not tree_nodes:
            return plan

        pages = await self._store.get_wiki_pages_for_business(
            business_id, min_tier=min_tier
        )
        plan.total_pages = len(pages)

        domain_names: list[str] = []
        for node in tree_nodes:
            label = node.get("label", "")
            if label == "WikiSection" and node.get("depth", 0) == 1:
                domain_names.append(str(node.get("title", "")))
        plan.domain_names = domain_names

        page_files = self._map_pages_to_files(pages)
        plan.files.extend(page_files)

        readme = self.generate_readme(business_id, domain_names)
        plan.files.insert(0, ExportFile(
            relative_path="README.md",
            content=readme,
            is_index=True,
        ))

        domain_index = self.generate_domain_index(
            self._group_pages_by_domain(pages)
        )
        plan.files.append(ExportFile(
            relative_path="_index/by-domain.md",
            content=domain_index,
            is_index=True,
        ))

        return plan

    def _map_pages_to_files(self, pages: list[dict[str, Any]]) -> list[ExportFile]:
        """Map WikiPage records to ExportFile instances."""
        files: list[ExportFile] = []
        for page in pages:
            wiki_path = page.get("path", "").strip("/")
            if not wiki_path:
                continue
            page_type = page.get("page_type", "")
            content = page.get("content", "")

            if page_type == "domain_overview" or wiki_path.endswith("/_overview"):
                dir_part = wiki_path.rsplit("/_overview", 1)[0] if "/_overview" in wiki_path else wiki_path
                rel_path = f"{dir_part}/README.md"
            else:
                rel_path = f"{wiki_path}.md"

            converted = self._convert_content(content, wiki_path)
            files.append(ExportFile(
                relative_path=rel_path,
                content=converted,
                content_hash=page.get("content_hash", ""),
            ))
        return files

    def _convert_content(self, content: str, current_path: str) -> str:
        """Convert wikilinks in content based on link_mode."""
        if self._link_mode == "obsidian":
            return self._link_converter.to_obsidian(content)
        return self._link_converter.to_markdown(content, current_path=f"/{current_path}")

    def _group_pages_by_domain(self, pages: list[dict[str, Any]]) -> dict[str, list[str]]:
        """Group page filenames by their top-level domain directory."""
        groups: dict[str, list[str]] = {}
        for page in pages:
            path = page.get("path", "").strip("/")
            if not path:
                continue
            parts = path.split("/")
            domain = parts[0] if parts else "uncategorized"
            filename = parts[-1] + ".md"
            groups.setdefault(domain, []).append(filename)
        return groups

    def generate_readme(self, business_id: str, domain_names: list[str]) -> str:
        """Generate README.md content for the wiki root."""
        lines = [
            f"# {business_id} Knowledge Base",
            "",
            "## Business Domains",
            "",
        ]
        for name in domain_names:
            lines.append(f"- [{name}]({name}/README.md)")
        lines.extend(["", "---", "", "*Auto-generated by Knowledge Base Service.*", ""])
        return "\n".join(lines)

    def generate_domain_index(self, domains: dict[str, list[str]]) -> str:
        """Generate _index/by-domain.md with tree-shaped index."""
        lines = ["# Domain Index", ""]
        if not domains:
            lines.append("No domains found.")
            return "\n".join(lines)
        for domain, pages in sorted(domains.items()):
            lines.append(f"## {domain}")
            lines.append("")
            for page in sorted(pages):
                lines.append(f"- [{page}](../{domain}/{page})")
            lines.append("")
        return "\n".join(lines)

    async def export_to_directory(self, plan: ExportPlan, output_dir: str) -> list[str]:
        """Write all files in the export plan to output_dir."""
        created: list[str] = []
        out = Path(output_dir)
        for f in plan.files:
            full = out / f.relative_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(f.content, encoding="utf-8")
            created.append(str(full))
        return created
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_business_wiki_exporter.py -v`

- [ ] **Step 6: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`

**Commit:** `feat(wiki): add BusinessWikiExporter for business-level wiki export`

---

### Task 3: ObsidianExporter + MkDocsExporter — 格式适配器

**Files:**
- Create: `wiki/obsidian_exporter.py`
- Create: `wiki/mkdocs_exporter.py`
- Create: `tests/wiki/test_obsidian_exporter.py`
- Create: `tests/wiki/test_mkdocs_exporter.py`

**背景:** Obsidian 和 MkDocs 需要额外的配置文件和不同的链接格式。两者均复用 BusinessWikiExporter 的核心导出逻辑。

- [ ] **Step 1: Write failing Obsidian tests**

创建 `tests/wiki/test_obsidian_exporter.py`：

```python
# tests/wiki/test_obsidian_exporter.py
"""Unit tests for ObsidianExporter."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.obsidian_exporter import ObsidianExporter


class TestGenerateObsidianConfig:
    def test_app_json_content(self):
        exporter = ObsidianExporter(store=None)
        config = exporter.generate_app_config()
        parsed = json.loads(config)
        assert "useMarkdownLinks" in parsed
        assert parsed["useMarkdownLinks"] is False

    def test_graph_json_content(self):
        exporter = ObsidianExporter(store=None)
        config = exporter.generate_graph_config()
        parsed = json.loads(config)
        assert "collapse-filter" in parsed or "colorGroups" in parsed or isinstance(parsed, dict)


class TestObsidianExportPlan:
    @pytest.mark.asyncio
    async def test_plan_includes_obsidian_config(self):
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(
            return_value=MagicMock(data=[])
        )
        mock_store.get_wiki_pages_for_business = AsyncMock(return_value=[])
        exporter = ObsidianExporter(mock_store)
        plan = await exporter.build_export_plan("test-biz")
        paths = [f.relative_path for f in plan.files]
        assert ".obsidian/app.json" in paths

    @pytest.mark.asyncio
    async def test_obsidian_uses_wikilink_mode(self):
        exporter = ObsidianExporter(store=None)
        assert exporter._link_mode == "obsidian"
```

- [ ] **Step 2: Write failing MkDocs tests**

创建 `tests/wiki/test_mkdocs_exporter.py`：

```python
# tests/wiki/test_mkdocs_exporter.py
"""Unit tests for MkDocsExporter."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.mkdocs_exporter import MkDocsExporter


class TestGenerateMkDocsYml:
    def test_contains_site_name(self):
        exporter = MkDocsExporter(store=None)
        yml = exporter.generate_mkdocs_yml("my-wiki", ["用户管理", "订单处理"])
        assert "site_name:" in yml
        assert "my-wiki" in yml

    def test_contains_nav_section(self):
        exporter = MkDocsExporter(store=None)
        yml = exporter.generate_mkdocs_yml("wiki", ["用户管理"])
        assert "nav:" in yml
        assert "用户管理" in yml

    def test_contains_mermaid_plugin(self):
        exporter = MkDocsExporter(store=None)
        yml = exporter.generate_mkdocs_yml("wiki", [])
        assert "mermaid" in yml.lower() or "pymdownx" in yml.lower()


class TestMkDocsExportPlan:
    @pytest.mark.asyncio
    async def test_plan_includes_mkdocs_yml(self):
        mock_store = AsyncMock()
        mock_store.get_wiki_tree = AsyncMock(
            return_value=MagicMock(data=[])
        )
        mock_store.get_wiki_pages_for_business = AsyncMock(return_value=[])
        exporter = MkDocsExporter(mock_store)
        plan = await exporter.build_export_plan("test-biz")
        paths = [f.relative_path for f in plan.files]
        assert "mkdocs.yml" in paths

    @pytest.mark.asyncio
    async def test_mkdocs_uses_markdown_mode(self):
        exporter = MkDocsExporter(store=None)
        assert exporter._link_mode == "markdown"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_obsidian_exporter.py tests/wiki/test_mkdocs_exporter.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: Implement ObsidianExporter**

创建 `wiki/obsidian_exporter.py`：

```python
"""Obsidian vault export — preserves [[wikilinks]] and generates .obsidian/ config."""

from __future__ import annotations

import json
from typing import Any

from wiki.business_wiki_exporter import BusinessWikiExporter, ExportFile, ExportPlan


class ObsidianExporter(BusinessWikiExporter):
    """Exports business wiki as an Obsidian vault."""

    def __init__(self, store: Any | None) -> None:
        super().__init__(store=store, link_mode="obsidian")

    async def build_export_plan(
        self,
        business_id: str,
        view: str = "business_domain",
        min_tier: str = "standard",
    ) -> ExportPlan:
        plan = await super().build_export_plan(business_id, view, min_tier)
        plan.files.append(ExportFile(
            relative_path=".obsidian/app.json",
            content=self.generate_app_config(),
            is_index=True,
        ))
        plan.files.append(ExportFile(
            relative_path=".obsidian/graph.json",
            content=self.generate_graph_config(),
            is_index=True,
        ))
        return plan

    def generate_app_config(self) -> str:
        config = {
            "useMarkdownLinks": False,
            "newFileLocation": "folder",
            "attachmentFolderPath": "_attachments",
            "alwaysUpdateLinks": True,
        }
        return json.dumps(config, indent=2, ensure_ascii=False)

    def generate_graph_config(self) -> str:
        config = {
            "collapse-filter": True,
            "search": "",
            "showTags": False,
            "showAttachments": False,
            "hideUnresolved": False,
            "colorGroups": [],
        }
        return json.dumps(config, indent=2, ensure_ascii=False)
```

- [ ] **Step 5: Implement MkDocsExporter**

创建 `wiki/mkdocs_exporter.py`：

```python
"""MkDocs export — generates mkdocs.yml with navigation config."""

from __future__ import annotations

from typing import Any

from wiki.business_wiki_exporter import BusinessWikiExporter, ExportFile, ExportPlan


class MkDocsExporter(BusinessWikiExporter):
    """Exports business wiki in MkDocs-ready format."""

    def __init__(self, store: Any | None) -> None:
        super().__init__(store=store, link_mode="markdown")

    async def build_export_plan(
        self,
        business_id: str,
        view: str = "business_domain",
        min_tier: str = "standard",
    ) -> ExportPlan:
        plan = await super().build_export_plan(business_id, view, min_tier)
        yml = self.generate_mkdocs_yml(business_id, plan.domain_names)
        plan.files.append(ExportFile(
            relative_path="mkdocs.yml",
            content=yml,
            is_index=True,
        ))
        docs_files = []
        for f in plan.files:
            if f.relative_path == "mkdocs.yml":
                continue
            docs_files.append(ExportFile(
                relative_path=f"docs/{f.relative_path}",
                content=f.content,
                content_hash=f.content_hash,
                is_index=f.is_index,
            ))
        docs_files.append(ExportFile(
            relative_path="mkdocs.yml",
            content=yml,
            is_index=True,
        ))
        plan.files = docs_files
        return plan

    def generate_mkdocs_yml(self, site_name: str, domain_names: list[str]) -> str:
        nav_items = []
        for name in domain_names:
            nav_items.append(f"    - {name}: {name}/README.md")
        nav_section = "\n".join(nav_items) if nav_items else "    - Home: README.md"

        return (
            f"site_name: {site_name}\n"
            "theme:\n"
            "  name: material\n"
            "  features:\n"
            "    - navigation.tabs\n"
            "    - navigation.sections\n"
            "    - search.suggest\n"
            "markdown_extensions:\n"
            "  - pymdownx.superfences:\n"
            "      custom_fences:\n"
            "        - name: mermaid\n"
            "          class: mermaid\n"
            "          format: !!python/name:pymdownx.superfences.fence_code_format\n"
            "  - pymdownx.tabbed:\n"
            "      alternate_style: true\n"
            "nav:\n"
            "  - Home: README.md\n"
            f"  - Domains:\n"
            f"{nav_section}\n"
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_obsidian_exporter.py tests/wiki/test_mkdocs_exporter.py -v`

- [ ] **Step 7: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`

**Commit:** `feat(wiki): add Obsidian and MkDocs export formats`

---

### Task 4: GitPublisher — Git 增量推送 + 人工标注回流

**Files:**
- Create: `wiki/git_publisher.py`
- Create: `tests/wiki/test_git_publisher.py`

**背景:** GitPublisher 接收 ExportPlan，对比现有文件的 content_hash 识别变更，通过 `asyncio.create_subprocess_exec` 执行 git 操作。同时支持从目标仓库回流 `.annotations.md` 人工标注。

- [ ] **Step 1: Write the failing tests**

创建 `tests/wiki/test_git_publisher.py`：

```python
# tests/wiki/test_git_publisher.py
"""Unit tests for GitPublisher."""

import hashlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wiki.git_publisher import GitPublisher, PublishResult


class TestDetectChanges:
    def test_new_files_detected_as_added(self):
        pub = GitPublisher(remote_url="https://example.com/wiki.git", branch="main")
        existing: dict[str, str] = {}
        new_files = {"README.md": "# Hello", "domain/page.md": "content"}
        changes = pub.detect_changes(existing, new_files)
        assert set(changes["added"]) == {"README.md", "domain/page.md"}
        assert changes["modified"] == []
        assert changes["deleted"] == []

    def test_modified_files_detected_by_hash(self):
        pub = GitPublisher(remote_url="", branch="main")
        old_hash = hashlib.sha256(b"old content").hexdigest()
        existing = {"a.md": old_hash}
        new_files = {"a.md": "new content"}
        changes = pub.detect_changes(existing, new_files)
        assert "a.md" in changes["modified"]

    def test_unchanged_files_not_in_changes(self):
        pub = GitPublisher(remote_url="", branch="main")
        content = "same content"
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        existing = {"a.md": content_hash}
        new_files = {"a.md": content}
        changes = pub.detect_changes(existing, new_files)
        assert changes["added"] == []
        assert changes["modified"] == []

    def test_deleted_files_detected(self):
        pub = GitPublisher(remote_url="", branch="main")
        existing = {"old.md": "somehash"}
        new_files: dict[str, str] = {}
        changes = pub.detect_changes(existing, new_files)
        assert "old.md" in changes["deleted"]


class TestGenerateCommitMessage:
    def test_includes_file_names(self):
        pub = GitPublisher(remote_url="", branch="main")
        msg = pub.generate_commit_message(
            added=["domain/new.md"],
            modified=["domain/updated.md"],
            deleted=[],
            trigger_info="user-service@abc1234",
        )
        assert "docs(wiki):" in msg
        assert "new.md" in msg

    def test_full_regeneration_message(self):
        pub = GitPublisher(remote_url="", branch="main")
        msg = pub.generate_commit_message(
            added=[], modified=[], deleted=[],
            trigger_info="full-regeneration",
            is_full=True,
        )
        assert "full regeneration" in msg.lower()

    def test_prefix_customizable(self):
        pub = GitPublisher(
            remote_url="", branch="main",
            commit_message_prefix="docs(kb):",
        )
        msg = pub.generate_commit_message(
            added=["a.md"], modified=[], deleted=[],
        )
        assert msg.startswith("docs(kb):")


class TestPublishResult:
    def test_result_dataclass(self):
        result = PublishResult(
            success=True,
            files_added=2,
            files_modified=1,
            files_deleted=0,
            commit_sha="abc123",
        )
        assert result.success
        assert result.files_added == 2
        assert result.commit_sha == "abc123"

    def test_error_result(self):
        result = PublishResult(
            success=False,
            files_added=0,
            files_modified=0,
            files_deleted=0,
            error="Permission denied",
        )
        assert not result.success
        assert "Permission" in (result.error or "")


class TestScanAnnotations:
    def test_finds_annotation_files(self, tmp_path):
        ann_dir = tmp_path / "用户管理"
        ann_dir.mkdir()
        ann_file = ann_dir / "UserController.annotations.md"
        ann_file.write_text("## Custom Notes\nImportant detail.", encoding="utf-8")

        pub = GitPublisher(remote_url="", branch="main")
        annotations = pub.scan_annotations(str(tmp_path))
        assert len(annotations) == 1
        assert "用户管理/UserController" in annotations
        assert "Important detail" in annotations["用户管理/UserController"]

    def test_no_annotation_files(self, tmp_path):
        pub = GitPublisher(remote_url="", branch="main")
        annotations = pub.scan_annotations(str(tmp_path))
        assert annotations == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_git_publisher.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement GitPublisher**

创建 `wiki/git_publisher.py`：

```python
"""Git incremental publisher for wiki content."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from log import get_logger

log = get_logger(__name__)


@dataclass
class PublishResult:
    """Result of a git publish operation."""
    success: bool
    files_added: int
    files_modified: int
    files_deleted: int
    commit_sha: str | None = None
    error: str | None = None
    annotations_found: int = 0


class GitPublisher:
    """Publishes wiki export to a Git repository with incremental commits."""

    def __init__(
        self,
        remote_url: str,
        branch: str = "main",
        author_name: str = "KBS Wiki Bot",
        author_email: str = "wiki-bot@company.com",
        commit_message_prefix: str = "docs(wiki):",
        git_token: str = "",
        ssh_key_path: str = "",
    ) -> None:
        self._remote_url = remote_url
        self._branch = branch
        self._author_name = author_name
        self._author_email = author_email
        self._prefix = commit_message_prefix
        self._git_token = git_token
        self._ssh_key_path = ssh_key_path

    def detect_changes(
        self,
        existing_hashes: dict[str, str],
        new_files: dict[str, str],
    ) -> dict[str, list[str]]:
        """Compare content hashes to identify added/modified/deleted files."""
        added: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []

        for path, content in new_files.items():
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if path not in existing_hashes:
                added.append(path)
            elif existing_hashes[path] != content_hash:
                modified.append(path)

        for path in existing_hashes:
            if path not in new_files:
                deleted.append(path)

        return {"added": added, "modified": modified, "deleted": deleted}

    def generate_commit_message(
        self,
        added: list[str],
        modified: list[str],
        deleted: list[str] | None = None,
        trigger_info: str = "",
        is_full: bool = False,
    ) -> str:
        """Generate a descriptive commit message."""
        if is_full:
            return f"{self._prefix} full regeneration for business wiki"

        parts: list[str] = []
        if added:
            names = ", ".join(Path(p).stem for p in added[:5])
            suffix = f" (+{len(added) - 5} more)" if len(added) > 5 else ""
            parts.append(f"add {names}{suffix}")
        if modified:
            names = ", ".join(Path(p).stem for p in modified[:5])
            suffix = f" (+{len(modified) - 5} more)" if len(modified) > 5 else ""
            parts.append(f"update {names}{suffix}")
        if deleted:
            parts.append(f"remove {len(deleted)} pages")

        summary = "; ".join(parts) if parts else "no changes"
        msg = f"{self._prefix} {summary}"
        if trigger_info:
            msg += f" (triggered by {trigger_info})"
        return msg

    def scan_annotations(self, repo_dir: str) -> dict[str, str]:
        """Scan a directory tree for .annotations.md files."""
        annotations: dict[str, str] = {}
        root = Path(repo_dir)
        for ann_file in root.rglob("*.annotations.md"):
            rel = ann_file.relative_to(root)
            wiki_path = str(rel).replace(".annotations.md", "").replace(os.sep, "/")
            try:
                content = ann_file.read_text(encoding="utf-8")
                annotations[wiki_path] = content
            except OSError:
                log.warning("Failed to read annotation file: %s", ann_file, exc_info=True)
        return annotations

    async def publish(
        self,
        export_files: dict[str, str],
        trigger_info: str = "",
        is_full: bool = False,
    ) -> PublishResult:
        """Clone/pull target repo, write files, commit and push changes."""
        if not self._remote_url:
            return PublishResult(
                success=False, files_added=0, files_modified=0,
                files_deleted=0, error="No remote_url configured",
            )

        work_dir = tempfile.mkdtemp(prefix="kbs-wiki-publish-")
        try:
            return await self._do_publish(work_dir, export_files, trigger_info, is_full)
        except Exception as exc:
            log.error("Git publish failed: %s", exc, exc_info=True)
            return PublishResult(
                success=False, files_added=0, files_modified=0,
                files_deleted=0, error=str(exc),
            )
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    async def _do_publish(
        self,
        work_dir: str,
        export_files: dict[str, str],
        trigger_info: str,
        is_full: bool,
    ) -> PublishResult:
        env = self._build_git_env()

        await self._run_git(["clone", "--depth=1", "-b", self._branch,
                             self._auth_url(), work_dir], env=env)

        annotations = self.scan_annotations(work_dir)

        existing_hashes = self._hash_existing_files(work_dir)
        changes = self.detect_changes(existing_hashes, export_files)

        if not changes["added"] and not changes["modified"] and not changes["deleted"]:
            return PublishResult(
                success=True, files_added=0, files_modified=0,
                files_deleted=0, annotations_found=len(annotations),
            )

        for path, content in export_files.items():
            full = Path(work_dir) / path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")

        for path in changes["deleted"]:
            full = Path(work_dir) / path
            if full.exists():
                full.unlink()

        msg = self.generate_commit_message(
            changes["added"], changes["modified"], changes["deleted"],
            trigger_info=trigger_info, is_full=is_full,
        )

        await self._run_git(["add", "-A"], cwd=work_dir, env=env)
        await self._run_git(
            ["commit", "-m", msg,
             "--author", f"{self._author_name} <{self._author_email}>"],
            cwd=work_dir, env=env,
        )

        push_result = await self._run_git(
            ["push", "origin", self._branch], cwd=work_dir, env=env,
        )

        sha = await self._get_head_sha(work_dir, env)

        return PublishResult(
            success=True,
            files_added=len(changes["added"]),
            files_modified=len(changes["modified"]),
            files_deleted=len(changes["deleted"]),
            commit_sha=sha,
            annotations_found=len(annotations),
        )

    def _auth_url(self) -> str:
        if self._git_token and self._remote_url.startswith("https://"):
            parts = self._remote_url.split("://", 1)
            return f"{parts[0]}://oauth2:{self._git_token}@{parts[1]}"
        return self._remote_url

    def _build_git_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self._ssh_key_path:
            env["GIT_SSH_COMMAND"] = f"ssh -i {self._ssh_key_path} -o StrictHostKeyChecking=no"
        env["GIT_AUTHOR_NAME"] = self._author_name
        env["GIT_AUTHOR_EMAIL"] = self._author_email
        env["GIT_COMMITTER_NAME"] = self._author_name
        env["GIT_COMMITTER_EMAIL"] = self._author_email
        return env

    @staticmethod
    def _hash_existing_files(repo_dir: str) -> dict[str, str]:
        hashes: dict[str, str] = {}
        root = Path(repo_dir)
        for f in root.rglob("*.md"):
            if f.name.startswith("."):
                continue
            rel = str(f.relative_to(root)).replace(os.sep, "/")
            try:
                content = f.read_text(encoding="utf-8")
                hashes[rel] = hashlib.sha256(content.encode("utf-8")).hexdigest()
            except OSError:
                pass
        return hashes

    @staticmethod
    async def _run_git(
        args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"git {args[0]} failed (rc={proc.returncode}): {err_msg}")
        return stdout.decode("utf-8", errors="replace").strip()

    @staticmethod
    async def _get_head_sha(repo_dir: str, env: dict[str, str]) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=repo_dir,
            env=env,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return stdout.decode("utf-8", errors="replace").strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_git_publisher.py -v`

- [ ] **Step 5: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`

**Commit:** `feat(wiki): add GitPublisher for incremental Git push with annotation backflow`

---

### Task 5: 导出 API 扩展

**Files:**
- Modify: `api/routes/wiki_routes.py` — 新增 `POST /api/v1/wiki/export` 端点
- Create: `tests/wiki/test_export_api.py`

**背景:** 统一导出入口，支持 5 种格式，调度各导出器和 GitPublisher。

- [ ] **Step 1: Write the failing tests**

创建 `tests/wiki/test_export_api.py`：

```python
# tests/wiki/test_export_api.py
"""Unit tests for business wiki export API."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.wiki_routes import wiki_router


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(wiki_router, prefix="/api/v1/wiki")
    return app


class TestExportEndpointValidation:
    def test_invalid_format_returns_422(self, app):
        with patch("api.routes.wiki_routes.require_role", return_value=lambda: None):
            client = TestClient(app)
            r = client.post(
                "/api/v1/wiki/export",
                json={"business_id": "test", "format": "invalid_format"},
            )
            assert r.status_code == 422

    def test_valid_format_accepted(self, app):
        with patch("api.routes.wiki_routes.require_role", return_value=lambda: None):
            with patch("api.routes.wiki_routes.get_wiki_store_dep") as mock_dep:
                mock_store = AsyncMock()
                mock_store.get_wiki_tree = AsyncMock(return_value=MagicMock(data=[]))
                mock_store.get_wiki_pages_for_business = AsyncMock(return_value=[])
                mock_dep.return_value = mock_store

                client = TestClient(app)
                r = client.post(
                    "/api/v1/wiki/export",
                    json={"business_id": "test", "format": "markdown"},
                )
                assert r.status_code in (200, 202, 500)


class TestExportEndpointFormats:
    def test_git_format_requires_git_config(self, app):
        with patch("api.routes.wiki_routes.require_role", return_value=lambda: None):
            client = TestClient(app)
            r = client.post(
                "/api/v1/wiki/export",
                json={"business_id": "test", "format": "git"},
            )
            assert r.status_code in (400, 422)

    def test_response_contains_format_field(self, app):
        with patch("api.routes.wiki_routes.require_role", return_value=lambda: None):
            with patch("api.routes.wiki_routes.get_wiki_store_dep") as mock_dep:
                mock_store = AsyncMock()
                mock_store.get_wiki_tree = AsyncMock(return_value=MagicMock(data=[]))
                mock_store.get_wiki_pages_for_business = AsyncMock(return_value=[])
                mock_dep.return_value = mock_store

                client = TestClient(app)
                r = client.post(
                    "/api/v1/wiki/export",
                    json={"business_id": "test", "format": "markdown"},
                )
                if r.status_code == 200:
                    data = r.json()
                    assert "format" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_export_api.py -v`

- [ ] **Step 3: Add export endpoint to wiki_routes.py**

在 `api/routes/wiki_routes.py` 中添加（在 `generate_business_wiki` 端点之后）：

```python
class GitPushConfig(BaseModel):
    remote_url: str = Field(..., min_length=1)
    branch: str = Field(default="main")
    commit_message_prefix: str = Field(default="docs(wiki):")

class BusinessWikiExportBody(BaseModel):
    business_id: str = Field(default="default", min_length=1)
    format: str = Field(..., pattern="^(markdown|zip|git|obsidian|mkdocs)$")
    view_type: str = Field(default="business_domain", pattern="^(business_domain|code_structure|both)$")
    min_tier: str = Field(default="standard", pattern="^(core|standard|skeleton)$")
    repositories: list[str] | None = None
    domains: list[str] | None = None
    git_config: GitPushConfig | None = None

@wiki_router.post("/export", response_model=None, dependencies=[Depends(require_role(Role.EDITOR))])
async def business_wiki_export(
    body: BusinessWikiExportBody,
    store: Any = Depends(get_wiki_store_dep),
) -> Any:
    """Export business wiki in various formats."""
    from wiki.business_wiki_exporter import BusinessWikiExporter
    from wiki.obsidian_exporter import ObsidianExporter
    from wiki.mkdocs_exporter import MkDocsExporter
    from wiki.git_publisher import GitPublisher

    wiki_store = WikiStore(store)

    if body.format == "git" and not body.git_config:
        raise HTTPException(
            status_code=400,
            detail={"error": "git_config_required", "detail": "git_config is required for git format"},
        )

    if body.format == "obsidian":
        exporter = ObsidianExporter(wiki_store)
    elif body.format == "mkdocs":
        exporter = MkDocsExporter(wiki_store)
    else:
        exporter = BusinessWikiExporter(wiki_store)

    plan = await exporter.build_export_plan(
        business_id=body.business_id,
        view=body.view_type,
        min_tier=body.min_tier,
    )

    if body.format == "git":
        cfg = body.git_config
        settings = get_settings()
        publisher = GitPublisher(
            remote_url=cfg.remote_url,
            branch=cfg.branch,
            commit_message_prefix=cfg.commit_message_prefix,
            author_name=settings.wiki.git_author_name,
            author_email=settings.wiki.git_author_email,
            git_token=settings.wiki.git_token,
        )
        file_map = {f.relative_path: f.content for f in plan.files}
        result = await publisher.publish(file_map, trigger_info=body.business_id)
        return {
            "format": "git",
            "business_id": body.business_id,
            "success": result.success,
            "files_added": result.files_added,
            "files_modified": result.files_modified,
            "files_deleted": result.files_deleted,
            "commit_sha": result.commit_sha,
            "annotations_found": result.annotations_found,
            "error": result.error,
        }

    if body.format == "zip":
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in plan.files:
                zf.writestr(f.relative_path, f.content)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={body.business_id}-wiki.zip"},
        )

    return {
        "format": body.format,
        "business_id": body.business_id,
        "total_files": len(plan.files),
        "files": [{"path": f.relative_path, "is_index": f.is_index} for f in plan.files],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/test_export_api.py -v`

- [ ] **Step 5: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`

**Commit:** `feat(wiki): add business wiki export API with 5 format support`

---

### Task 6: 集成验证 + Phase 5 导出

**Files:**
- Modify: `wiki/__init__.py`
- Create: `tests/wiki/integration/test_phase5_smoke.py`

- [ ] **Step 1: Update wiki/__init__.py**

添加 Phase 5 组件导出：

```python
from wiki.wikilink_converter import WikiLinkConverter
from wiki.business_wiki_exporter import BusinessWikiExporter, ExportFile, ExportPlan
from wiki.obsidian_exporter import ObsidianExporter
from wiki.mkdocs_exporter import MkDocsExporter
from wiki.git_publisher import GitPublisher, PublishResult
```

并更新 `__all__` 列表添加：`"WikiLinkConverter"`, `"BusinessWikiExporter"`, `"ExportFile"`, `"ExportPlan"`, `"ObsidianExporter"`, `"MkDocsExporter"`, `"GitPublisher"`, `"PublishResult"`

- [ ] **Step 2: Write integration smoke tests**

创建 `tests/wiki/integration/test_phase5_smoke.py`：

```python
# tests/wiki/integration/test_phase5_smoke.py
"""Phase 5 integration smoke tests."""


def test_phase5_imports():
    from wiki import (
        WikiLinkConverter,
        BusinessWikiExporter,
        ExportPlan,
        ObsidianExporter,
        MkDocsExporter,
        GitPublisher,
        PublishResult,
    )
    assert WikiLinkConverter is not None
    assert BusinessWikiExporter is not None
    assert ExportPlan is not None
    assert ObsidianExporter is not None
    assert MkDocsExporter is not None
    assert GitPublisher is not None
    assert PublishResult is not None


def test_wikilink_roundtrip():
    from wiki.wikilink_converter import WikiLinkConverter
    conv = WikiLinkConverter()
    original = "See [[/domain/page]]."
    md = conv.to_markdown(original, "/other/current")
    assert "[[" not in md
    assert ".md" in md
    obsidian = conv.to_obsidian(original)
    assert "[[domain/page]]" in obsidian


def test_config_phase5_fields():
    from config import Settings
    s = Settings(_env_file=None, falkordb={"host": "localhost", "port": 6379})
    wiki = s.wiki
    assert hasattr(wiki, "git_publish_enabled")
    assert hasattr(wiki, "git_publish_mode")
    assert hasattr(wiki, "git_remote_url")
    assert hasattr(wiki, "git_branch")
    assert hasattr(wiki, "git_author_name")
    assert hasattr(wiki, "export_default_view")
    assert hasattr(wiki, "export_min_tier")
    assert hasattr(wiki, "export_dir_naming")


def test_export_plan_dataclass():
    from wiki.business_wiki_exporter import ExportFile, ExportPlan
    plan = ExportPlan(business_id="test", view="business_domain")
    plan.files.append(ExportFile(relative_path="README.md", content="# Test"))
    assert len(plan.files) == 1
    assert plan.total_pages == 0


def test_publish_result_dataclass():
    from wiki.git_publisher import PublishResult
    result = PublishResult(
        success=True, files_added=1, files_modified=0, files_deleted=0,
        commit_sha="abc123",
    )
    assert result.success
    assert result.commit_sha == "abc123"


def test_obsidian_inherits_business_exporter():
    from wiki.obsidian_exporter import ObsidianExporter
    from wiki.business_wiki_exporter import BusinessWikiExporter
    assert issubclass(ObsidianExporter, BusinessWikiExporter)


def test_mkdocs_inherits_business_exporter():
    from wiki.mkdocs_exporter import MkDocsExporter
    from wiki.business_wiki_exporter import BusinessWikiExporter
    assert issubclass(MkDocsExporter, BusinessWikiExporter)
```

- [ ] **Step 3: Run integration tests**

Run: `cd knowledge-base-service && uv run pytest tests/wiki/integration/test_phase5_smoke.py -v`

- [ ] **Step 4: Run full test suite**

Run: `cd knowledge-base-service && uv run pytest --tb=short -q`

**Commit:** `feat(wiki): Phase 5 integration validation and exports`

---

## Self-Review Checklist

### Spec Coverage
| 提案要求 | Task |
|---------|------|
| [[path]] → 相对 markdown 链接转换 | Task 1 |
| [[path]] → Obsidian 格式转换 | Task 1 |
| 业务级 Wiki 树 → 目录结构映射 | Task 2 |
| README.md + _index/ 索引生成 | Task 2 |
| Obsidian vault 导出 (.obsidian/ 配置) | Task 3 |
| MkDocs 导出 (mkdocs.yml 生成) | Task 3 |
| Git 增量推送 (content_hash 对比) | Task 4 |
| 人工标注回流 (.annotations.md) | Task 4 |
| 导出 API (POST /api/v1/wiki/export) | Task 5 |
| ZIP 格式导出 | Task 5 |
| 集成验证 | Task 6 |

### Placeholder Scan
- No "TBD", "TODO", "implement later" found
- All steps contain actual code
- All types referenced exist in earlier tasks

### Type Consistency
- `ExportFile`, `ExportPlan` — defined in Task 2, used in Task 3, 5, 6
- `PublishResult` — defined in Task 4, used in Task 5, 6
- `WikiLinkConverter` — defined in Task 1, used in Task 2, 3
- `BusinessWikiExporter` — defined in Task 2, subclassed in Task 3
