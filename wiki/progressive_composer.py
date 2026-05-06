"""Multi-round wiki generation for domains whose prompts exceed token limits."""

from __future__ import annotations

import re
from typing import Any

from wiki.content_context_builder import EnrichedDomainContext, EntityDetail
from wiki.json_robust import parse_json_robust_sync

_ROUND1_PLACEHOLDER = "__PROGRESSIVE_ROUND1__"
_PRIOR_MERGED_PLACEHOLDER = "__PRIOR_ROUNDS_MERGED__"

_ENTITY_BATCH_SIZE = 4

_ROUND1_JSON_TAIL = (
    "\n\nReturn ONLY valid JSON (no markdown fences) with this shape:\n"
    '  {"executive_summary": "<string, 150-300 chars>", '
    '"content": "<Markdown: ## 业务概述; ## 架构全景图 或 ## 核心业务流程 必含 Mermaid>"}\n'
    "Do not add detailed per-entity service sections in this round — names only in architecture.\n"
)

_ENTITY_JSON_TAIL = (
    "\n\nReturn ONLY valid JSON (no markdown fences) with this shape:\n"
    '  {"executive_summary": "<string, may repeat domain gist>", '
    '"content": "<Markdown: focus on ## 核心服务详解 for the listed entities only>"}\n'
)

_FINAL_JSON_TAIL = (
    "\n\nReturn ONLY valid JSON (no markdown fences) with this shape:\n"
    '  {"executive_summary": "<string>", '
    '"content": "<Markdown: ## 设计要点与注意事项; ## 数据模型 (table if models exist)>"}\n'
)


def _llm_uses_generate_method(llm: Any) -> bool:
    if llm is None:
        return False
    if getattr(type(llm), "generate", None) is not None:
        return True
    inst = getattr(llm, "__dict__", None)
    return isinstance(inst, dict) and "generate" in inst


class ProgressiveComposer:
    """Handles large domain contexts by splitting into multiple LLM calls.

    Strategy:
    1. Estimate total token count of the prompt
    2. If under threshold, return single prompt (delegate to normal composer)
    3. If over threshold, split into rounds:
       - Round 1: Business overview + architecture diagram (using all entities but summarized)
       - Round 2+: Detailed sections for entity groups (core services, data models, etc.)
       - Final merge: Combine all round outputs into coherent page
    """

    def __init__(self, llm: Any | None, *, threshold_tokens: int = 6000) -> None:
        self._llm = llm
        self._threshold = threshold_tokens

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation: ~1.5 chars per token for mixed Chinese/English."""
        return max(1, int(len(text) / 1.5))

    def needs_progressive(self, prompt: str) -> bool:
        """Check if prompt exceeds threshold and needs multi-round generation."""
        return self.estimate_tokens(prompt) > self._threshold

    @staticmethod
    def _format_entity_block(entities: list[EntityDetail]) -> str:
        lines: list[str] = []
        for e in entities:
            methods = ", ".join(m.name for m in (e.methods or [])[:12])
            chains = ", ".join(
                f"{s.caller}->{s.callee}" for s in (e.call_chains or [])[:6]
            )
            lines.append(
                f"- **{e.name}** [{e.repository}] ({e.entity_type}) `{e.file_path}`\n"
                f"  - 摘要: {e.business_summary}\n"
                f"  - 方法: {methods or 'none'}\n"
                f"  - 调用: {chains or 'none'}"
            )
        return "\n".join(lines)

    @staticmethod
    def _domain_preamble(ctx: EnrichedDomainContext) -> str:
        parts = [
            f"域名称: **{ctx.domain_name}**",
            f"父域: {ctx.parent_domain}",
        ]
        if ctx.sibling_domains:
            parts.append("Sibling 域: " + ", ".join(ctx.sibling_domains[:10]))
        if ctx.cross_domain_calls:
            parts.append(
                "跨域调用 (摘录): "
                + "; ".join(
                    f"{s.caller}->{s.callee}" for s in ctx.cross_domain_calls[:8]
                )
            )
        return "\n".join(parts)

    def split_into_rounds(
        self,
        system_prompt: str,
        full_prompt: str,
        context: EnrichedDomainContext,
    ) -> list[dict]:
        """Split a large prompt into multiple rounds.

        Returns list of dicts: [{"system": str, "user": str, "focus": str}, ...]
        Each round focuses on a subset of the content.
        """
        if not self.needs_progressive(full_prompt):
            return [
                {
                    "system": system_prompt,
                    "user": full_prompt,
                    "focus": "full",
                },
            ]

        entities = list(context.biz_entities)
        entity_names_lines = "\n".join(f"- {e.name}" for e in entities)

        round1_user = (
            f"{self._domain_preamble(context)}\n\n"
            "以下是与本域相关的原始生成指令摘录（供上下文对齐，输出仍须遵守 JSON 约束）:\n"
            f"---\n{full_prompt[:4000]}...\n---\n"
            "全量实体名称（仅名称列表，用于架构感知；勿在本轮展开实现细节）:\n"
            f"{entity_names_lines or '（无实体）'}\n\n"
            "本轮输出要求：\n"
            "1. ## 业务概述 — 为什么需要此域、解决什么问题\n"
            "2. ## 架构全景图 — 或 ## 核心业务流程 — 必须包含 Mermaid 图；图中应体现上述实体名称之间的关系\n"
            + _ROUND1_JSON_TAIL
        )

        rounds: list[dict] = [
            {"system": system_prompt, "user": round1_user, "focus": "overview"},
        ]

        for i in range(0, len(entities), _ENTITY_BATCH_SIZE):
            batch = entities[i : i + _ENTITY_BATCH_SIZE]
            batch_user = (
                "参考第一轮已生成的概览与架构（生成时将插入在下方）：\n"
                f"{_ROUND1_PLACEHOLDER}\n\n"
                f"本轮仅围绕以下 {len(batch)} 个实体撰写 ## 核心服务详解（可含子标题）。\n"
                f"{self._format_entity_block(batch)}\n"
                + _ENTITY_JSON_TAIL
            )
            rounds.append(
                {
                    "system": system_prompt,
                    "user": batch_user,
                    "focus": f"entities_batch_{i // _ENTITY_BATCH_SIZE + 1}",
                },
            )

        models_summary = ""
        if context.data_models:
            models_summary = "\n".join(
                str(m) for m in context.data_models[:_ENTITY_BATCH_SIZE]
            )
        final_user = (
            "以下是前几轮产出的合并草稿（生成时将插入）；请在一致前提下补充设计与数据视角。\n"
            f"{_PRIOR_MERGED_PLACEHOLDER}\n\n"
            f"数据模型原始条目（可为空，需整理进 ## 数据模型）：\n{models_summary or '（无）'}\n\n"
            "本轮输出：## 设计要点与注意事项；## 数据模型（若有字段请用表格）。\n"
            + _FINAL_JSON_TAIL
        )
        rounds.append(
            {
                "system": system_prompt,
                "user": final_user,
                "focus": "design_final",
            },
        )

        return rounds

    async def _invoke_llm(self, system: str, user: str) -> str:
        if self._llm is None:
            raise ValueError("llm is required for progressive composition")
        if _llm_uses_generate_method(self._llm):
            gen = self._llm.generate
            return await gen(user, system=system, max_tokens=8192)
        return await self._llm(system, user)

    @staticmethod
    def _extract_executive_summary(raw: str) -> str:
        parsed = parse_json_robust_sync((raw or "").strip())
        if isinstance(parsed, dict):
            s = parsed.get("executive_summary")
            if isinstance(s, str) and s.strip():
                return s.strip()
        return ""

    @staticmethod
    def _extract_markdown_body(raw: str) -> str:
        stripped = (raw or "").strip()
        if not stripped:
            return ""
        parsed = parse_json_robust_sync(stripped)
        if isinstance(parsed, dict):
            body = parsed.get("content")
            if isinstance(body, str) and body.strip():
                return body.strip()
        return stripped

    @staticmethod
    def merge_round_outputs(outputs: list[str]) -> str:
        """Merge multiple round outputs into a single coherent page."""
        bodies: list[str] = []
        for raw in outputs:
            body = ProgressiveComposer._extract_markdown_body(raw)
            if body.strip():
                bodies.append(body.strip())
        combined = "\n\n".join(bodies)
        return ProgressiveComposer._dedupe_markdown_headers(combined)

    @staticmethod
    def _dedupe_markdown_headers(text: str) -> str:
        lines = text.splitlines()
        seen: set[str] = set()
        out: list[str] = []
        skipping = False
        for line in lines:
            if re.match(r"^##\s+\S", line):
                header = line.strip()
                if header in seen:
                    skipping = True
                    continue
                seen.add(header)
                skipping = False
                out.append(line)
                continue
            if skipping:
                continue
            out.append(line)
        return "\n".join(out).strip()

    async def compose_progressive(
        self,
        system_prompt: str,
        full_prompt: str,
        context: EnrichedDomainContext,
    ) -> tuple[str, str]:
        """Execute multi-round generation and merge results.

        Returns (executive_summary, merged_content).
        """
        if not self.needs_progressive(full_prompt):
            raw = await self._invoke_llm(system_prompt, full_prompt)
            summary = self._extract_executive_summary(raw)
            content = self._extract_markdown_body(raw)
            return summary, content

        plans = self.split_into_rounds(system_prompt, full_prompt, context)
        raw_rounds: list[str] = []

        for idx, spec in enumerate(plans):
            user = spec["user"]
            if _ROUND1_PLACEHOLDER in user and raw_rounds:
                r1_body = self._extract_markdown_body(raw_rounds[0])
                user = user.replace(_ROUND1_PLACEHOLDER, r1_body)
            if _PRIOR_MERGED_PLACEHOLDER in user and raw_rounds:
                prior_merged = self.merge_round_outputs(raw_rounds)
                user = user.replace(_PRIOR_MERGED_PLACEHOLDER, prior_merged)

            raw = await self._invoke_llm(spec["system"], user)
            raw_rounds.append(raw)

        executive = self._extract_executive_summary(raw_rounds[0]) if raw_rounds else ""
        merged = self.merge_round_outputs(raw_rounds)
        return executive, merged
