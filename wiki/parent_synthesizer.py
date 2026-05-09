"""Synthesize parent module documentation from child documents."""
from __future__ import annotations

from typing import Any

from core.log import get_logger
from wiki.models.module_tree import ModuleNode

log = get_logger(__name__)

_SYNTHESIS_SYSTEM = (
    "你是代码文档架构师。基于子模块文档综合生成父模块概览。"
    "输出纯 Markdown。包含：职责概述、子模块协作关系、架构图（Mermaid）。"
)


class ParentSynthesizer:
    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def synthesize(
        self,
        parent: ModuleNode,
        child_contents: list[str],
    ) -> str:
        child_sections = []
        n_children = min(len(parent.children), len(child_contents))
        if n_children < len(parent.children):
            log.warning(
                "parent_synthesizer_child_mismatch",
                parent=parent.canonical_key,
                children=len(parent.children),
                contents=len(child_contents),
            )
        for i, (child, content) in enumerate(
            zip(parent.children[:n_children], child_contents[:n_children])
        ):
            child_sections.append(
                f"### 子模块 {i + 1}: {child.title or child.canonical_key}\n"
                f"canonical_key: {child.canonical_key}\n"
                f"文件: {', '.join(child.file_paths[:5])}\n\n"
                f"{content[:3000]}"
            )

        prompt = (
            f"基于以下子模块文档，综合生成父模块「{parent.title or parent.canonical_key}」的概览文档。\n\n"
            "要求:\n"
            "1. 概述每个子模块的核心职责\n"
            "2. 说明子模块之间的协作关系\n"
            "3. 生成架构图（Mermaid graph TD）\n"
            "4. 使用 [[子模块canonical_key]] 链接到子页面\n\n"
            "子模块文档:\n\n"
            + "\n\n---\n\n".join(child_sections)
        )

        try:
            result = await self._llm.generate(
                prompt, system=_SYNTHESIS_SYSTEM, max_tokens=3000,
            )
            return result
        except Exception:
            log.warning("parent_synthesizer_failed", parent=parent.canonical_key, exc_info=True)
            titles = "\n".join(
                f"- [[{c.canonical_key}|{c.title or c.canonical_key}]]"
                for c in parent.children
            )
            return f"# {parent.title or parent.canonical_key}\n\n## 子模块\n\n{titles}"
