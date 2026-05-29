from __future__ import annotations

import re
from dataclasses import dataclass, field

COMPACTION_SYSTEM_PROMPT = """你是一个代码知识库的上下文管理器。你的任务是将工具调用历史浓缩为结构化摘要。

重要规则：
1. 不要调用任何工具，仅输出文本摘要
2. 不要编造事实——只记录已发现的信息
3. 保留因果推理链（因为X所以判断Y）
4. 保留具体的实体名、文件路径、方法签名
5. 不保留原始代码全文，仅保留关键签名和行号"""

COMPACTION_USER_PROMPT = """请将以下 Agent 工具调用历史浓缩为结构化摘要。使用以下 9 个标准段落：

## 1. Primary Objective — 主要目标与当前进展
## 2. Key Discoveries — 关键技术发现
格式：`- EntityName (path): 作用描述`
## 3. Call Chains & Dependencies — 调用链与依赖
格式：`- A → B → C: 功能链描述`
## 4. Reasoning Chain — 推理链
格式：`- 因为发现X，所以判断Y`
## 5. Variables & State — 变量与状态
## 6. Completed Steps — 已完成步骤
## 7. Pending Actions — 待办事项
## 8. Errors & Solutions — 错误与解决方案
## 9. Next Action — 下一步行动

---
以下是工具调用历史（轮次 {start_round}-{end_round}）：

{history}"""

_SECTION_NAMES = [
    "Primary Objective",
    "Key Discoveries",
    "Call Chains & Dependencies",
    "Reasoning Chain",
    "Variables & State",
    "Completed Steps",
    "Pending Actions",
    "Errors & Solutions",
    "Next Action",
]

_SECTION_HEADER = re.compile(r"^##\s*\d+\.\s*(.+)", re.MULTILINE)


@dataclass
class CompactionResult:
    summary: str
    key_findings: list[str] = field(default_factory=list)
    call_chains: list[str] = field(default_factory=list)
    covered_entities: list[str] = field(default_factory=list)
    source_round_range: tuple[int, int] = (0, 0)
    original_chars: int = 0
    compressed_chars: int = 0


class ExploreCompactor:
    """Framework-level LLM-driven context compactor."""

    _MAX_HISTORY_CHARS = 30_000
    _MAX_TOOL_RESULT_CHARS = 2_000

    def __init__(self, llm_port, *, model: str | None = None):
        self._llm = llm_port
        self._model = model

    async def compact(self, messages: list[dict], start_idx: int, end_idx: int) -> CompactionResult:
        history = self._format_history(messages, start_idx, end_idx)
        original_chars = sum(len(m.get("content", "")) for m in messages[start_idx:end_idx])

        prompt = COMPACTION_USER_PROMPT.format(
            start_round=start_idx,
            end_round=end_idx,
            history=history,
        )
        summary = await self._llm.complete(
            system_prompt=COMPACTION_SYSTEM_PROMPT,
            user_prompt=prompt,
            model=self._model,
        )
        if not isinstance(summary, str):
            summary = str(summary)

        sections = self._parse_sections(summary)
        key_findings = self._extract_list(sections.get("Key Discoveries", ""))
        call_chains = self._extract_list(sections.get("Call Chains & Dependencies", ""))
        entities = [line.split("(")[0].strip().lstrip("- ") for line in key_findings if "(" in line]

        return CompactionResult(
            summary=summary,
            key_findings=key_findings,
            call_chains=call_chains,
            covered_entities=entities,
            source_round_range=(start_idx, end_idx),
            original_chars=original_chars,
            compressed_chars=len(summary),
        )

    def _format_history(self, messages: list[dict], start_idx: int, end_idx: int) -> str:
        parts = []
        total = 0
        for msg in messages[start_idx:end_idx]:
            if msg.get("role") == "system":
                continue
            content = msg.get("content", "")
            if len(content) > self._MAX_TOOL_RESULT_CHARS:
                content = content[: self._MAX_TOOL_RESULT_CHARS] + "...[truncated]"
            line = f"[{msg.get('role', '?')}] {content}"
            if total + len(line) > self._MAX_HISTORY_CHARS:
                break
            parts.append(line)
            total += len(line)
        return "\n".join(parts)

    def _parse_sections(self, summary: str) -> dict[str, str]:
        sections: dict[str, str] = {}
        matches = list(_SECTION_HEADER.finditer(summary))
        for i, match in enumerate(matches):
            header_title = match.group(1).strip()
            canonical = next(
                (name for name in _SECTION_NAMES if name.lower() == header_title.lower()),
                None,
            )
            if not canonical:
                continue
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(summary)
            sections[canonical] = summary[start:end].strip()
        return sections

    @staticmethod
    def _extract_list(text: str) -> list[str]:
        return [line.strip() for line in text.split("\n") if line.strip().startswith("- ")]


def micro_compact(messages: list[dict], *, keep_recent_n: int = 3) -> list[dict]:
    """L1: Clear old tool results, keep recent N. Remove orphan tool_calls."""
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    keep_set = set(tool_indices[-keep_recent_n:]) if len(tool_indices) > keep_recent_n else set(tool_indices)

    result: list[dict] = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "tool":
            if i in keep_set:
                result.append(msg)
            else:
                n_chars = len(msg.get("content", ""))
                result.append({**msg, "content": f"[已压缩: tool result, {n_chars} chars]"})
        else:
            result.append(msg)

    all_tool_result_ids = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
    cleaned: list[dict] = []
    for msg in result:
        if tcs := msg.get("tool_calls"):
            valid = [tc for tc in tcs if tc.get("id") in all_tool_result_ids]
            if valid:
                cleaned.append({**msg, "tool_calls": valid})
            elif msg.get("content"):
                cleaned.append({k: v for k, v in msg.items() if k != "tool_calls"})
        else:
            cleaned.append(msg)

    return cleaned


def snip_compact(messages: list[dict], *, max_tool_chars: int = 2000) -> list[dict]:
    """L2: Truncate long tool results to head+tail format."""
    result: list[dict] = []
    for msg in messages:
        if msg.get("role") == "tool" and len(msg.get("content", "")) > max_tool_chars:
            content = msg["content"]
            head = content[:500]
            tail = content[-500:]
            result.append({**msg, "content": f"{head}\n...[snipped {len(content)} chars]...\n{tail}"})
        else:
            result.append(msg)

    return result
