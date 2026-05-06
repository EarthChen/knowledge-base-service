"""Unified system and user prompt templates for wiki page generation (Phase 2 U2)."""

from __future__ import annotations

from wiki.content_context_builder import (
    CallChainStep,
    EntityDetail,
    EnrichedDomainContext,
    MethodDetail,
)

UNIFIED_WIKI_SYSTEM_PROMPT = """你是企业级代码知识库与 Wiki 生成助手，面向业务与工程读者撰写高质量页面。

## 写作与视角
- 以**业务价值与系统职责**为第一视角，用中文阐述；涉及类名、方法名、文件路径、仓库名等技术标识保持**英文原文**引用。
- 每个正文大节（以 ## 开头的章节）至少包含 **2～3 段**完整段落，避免只列 bullet 而无解释。
- 说明「是谁、在什么场景、做什么、与上下游如何协作」，不要写成框架通识课。

## Mermaid 图表
- 仅当上下文数据中**确有**调用链、模块或依赖关系时，再绘制 Mermaid（flowchart / graph / sequenceDiagram 等）。
- **禁止凭空空想**节点与边；图中模块/服务名须与提供的数据一致。若无足够数据，明确写「数据不足，不生成图」并在正文中用文字说明。

## 源码溯源（source://）
- 任何关键断言（入口方法、核心调用、DTO 定义等）须在正文适当位置附带 `source://仓库名/文件路径:行号` 形式的链接（行号来自上下文；无行号时可省略 `:行号`）。
- 禁止编造不存在的路径或行号。

## 跨仓库标注
- 明确写出**仓库名（repository）**；跨域、跨仓库调用须说明调用方向与业务含义（谁依赖谁、为何调用）。

## 禁止事项
- 不要复述 Spring / gRPC /「分层架构」等**与当前域无粘性的框架科普**。
- 禁止使用「可能」「一般来说」「通常」等**空洞措辞**代替基于上下文的判断；若信息不足，直接写明缺失点。

## 输出格式（严格遵守）
仅输出一个 JSON 对象，不要 Markdown 代码围栏，不要前后解释：
{"executive_summary": "<150-300 字中文摘要>", "content": "<完整 Wiki 正文，Markdown，须包含任务要求的 ## 章节结构>"}
"""


def _format_method_lines(methods: list[MethodDetail]) -> list[str]:
    lines: list[str] = []
    for m in methods:
        sig = (m.signature or "").strip() or m.name
        loc = f"{m.file_path}:{m.start_line}" if m.file_path and m.start_line else (m.file_path or "")
        repo = m.repository or ""
        src = f"`source://{repo}/{loc}`" if repo and loc else (f"`source://{loc}`" if loc else "")
        doc = (m.docstring or "").strip()
        extra = f" — {doc}" if doc else ""
        lines.append(f"  - `{m.name}`: {sig} {src}{extra}".rstrip())
    return lines


def build_entity_section(entities: list[EntityDetail]) -> str:
    if not entities:
        return "（无实体数据）"
    blocks: list[str] = []
    for e in entities:
        methods = _format_method_lines(e.methods)
        methods_txt = "\n".join(methods) if methods else "  - （无方法签名数据）"
        fp = e.file_path or ""
        repo = e.repository or ""
        src = f"`source://{repo}/{fp}`" if repo and fp else (f"`source://{fp}`" if fp else "")
        summary = (e.business_summary or "").strip() or "（无业务摘要）"
        block = (
            f"- **{e.name}**（{e.entity_type}，仓库 `{repo}`）{src}\n"
            f"  - 业务摘要：{summary}\n"
            f"  - 方法：\n{methods_txt}"
        )
        blocks.append(block)
    return "\n".join(blocks)


def _format_call_steps(steps: list[CallChainStep], title: str) -> str:
    if not steps:
        return f"### {title}\n（无）"
    lines = [f"### {title}"]
    for s in steps:
        cm = s.caller_method or "?"
        cem = s.callee_method or "?"
        lines.append(
            f"- `{s.caller}` —({s.relationship})→ `{s.callee}` "
            f"（调用方方法: {cm} → 被调方法: {cem}）",
        )
    return "\n".join(lines)


def build_call_chain_section(
    intra_calls: list[CallChainStep],
    cross_calls: list[CallChainStep],
) -> str:
    return "\n\n".join([
        _format_call_steps(intra_calls, "域内调用链（Intra-domain）"),
        _format_call_steps(cross_calls, "跨域调用链（Cross-domain）"),
    ])


def build_data_model_section(models: list[dict]) -> str:
    if not models:
        return "（无 DTO/实体字段表数据）"
    lines: list[str] = []
    for m in models:
        name = str(m.get("name", "") or "")
        mtype = str(m.get("type", "DTO") or "DTO")
        fields = m.get("fields") or []
        if not isinstance(fields, list):
            fields = []
        field_txt = "、".join(str(f) for f in fields) if fields else "（无字段列表）"
        uid = str(m.get("uid", "") or "")
        lines.append(f"- **{name}**（{mtype}，uid `{uid}`）\n  - 字段：{field_txt}")
    return "\n".join(lines)


def build_enum_constants_section(items: list[dict]) -> str:
    if not items:
        return "（无枚举/常量数据）"
    lines: list[str] = []
    for it in items:
        name = str(it.get("name", "") or "")
        file = str(it.get("file", "") or "")
        labels = it.get("labels") or []
        if not isinstance(labels, list):
            labels = [str(labels)]
        lab = "/".join(str(x) for x in labels)
        loc = f"`source://{file}`" if file else "（无文件路径）"
        lines.append(f"- **{name}** [{lab}] {loc}")
    return "\n".join(lines)


def build_cross_domain_section(
    dependent: list[str],
    dependee: list[str],
    cross_calls: list[CallChainStep],
) -> str:
    dep = "、".join(f"`{d}`" for d in dependent) or "（无）"
    dee = "、".join(f"`{d}`" for d in dependee) or "（无）"
    calls = _format_call_steps(cross_calls, "跨域调用明细")
    return (
        f"- **本域依赖的外部域（dependent）**：{dep}\n"
        f"- **依赖本域的外部域（dependee）**：{dee}\n\n"
        f"{calls}"
    )


def _format_sub_topics(sub_topics: list[dict]) -> str:
    if not sub_topics:
        return "（暂无子主题数据）"
    lines: list[str] = []
    for t in sub_topics:
        name = str(t.get("name", t.get("title", "")) or "")
        desc = str(t.get("description", t.get("summary", "")) or "").strip()
        raw_count = t.get("entity_count", t.get("count", t.get("entities")))
        if raw_count is not None and raw_count != "":
            count_part = f"，实体数：{raw_count}"
        else:
            count_part = ""
        desc_txt = desc if desc else "（无描述）"
        lines.append(f"- **{name}**{count_part} — {desc_txt}")
    return "\n".join(lines)


def build_domain_overview_prompt(context: EnrichedDomainContext) -> str:
    sub_topic_block = _format_sub_topics(context.sub_topics)
    entity_block = build_entity_section(context.biz_entities)
    cross_block = build_cross_domain_section(
        context.dependent_domains,
        context.dependee_domains,
        context.cross_domain_calls,
    )
    intra_cross = build_call_chain_section(context.intra_domain_calls, context.cross_domain_calls)

    overview_siblings = "、".join(f"`{s}`" for s in context.sibling_domains) if context.sibling_domains else "无"

    return f"""请为业务域编写 **Wiki 域总览** 页面。域名称：`{context.domain_name}`；上级域：`{context.parent_domain}`；兄弟域：{overview_siblings}。

## 你必须在 JSON 的 content 中输出且仅使用以下 Markdown 章节（标题字面一致）
1. ## 业务概述 — 该域的业务目的与在系统中的角色（至少两段）
2. ## 架构全景图 — 基于下方数据绘制 Mermaid（子域/核心服务关系）；数据不足则说明原因且不强行画图
3. ## 子主题导航 — 列出子主题并附简述与实体数量线索（使用提供的数据）
4. ## 关键入口 — 突出入口/核心业务模块，附仓库名与文件路径及 source:// 引用
5. ## 跨域依赖与交互 — 结合 dependent/dependee 与跨域调用描述协作关系

## 参考数据：子主题
{sub_topic_block}

## 参考数据：核心业务实体与方法
{entity_block}

## 参考数据：域内/跨域调用（模块级）
{intra_cross}

## 参考数据：跨域依赖汇总
{cross_block}

请严格遵循系统提示中的 JSON 输出约定。"""


def build_topic_detail_prompt(context: EnrichedDomainContext) -> str:
    entity_block = build_entity_section(context.biz_entities)
    chains = build_call_chain_section(context.intra_domain_calls, context.cross_domain_calls)
    data_models = build_data_model_section(context.data_models)
    enums = build_enum_constants_section(context.enums_and_constants)
    cross_block = build_cross_domain_section(
        context.dependent_domains,
        context.dependee_domains,
        context.cross_domain_calls,
    )

    snippets_block = "\n".join(context.key_snippets) if context.key_snippets else "（无）"
    siblings = "、".join(f"`{s}`" for s in context.sibling_domains) if context.sibling_domains else "无"

    base = f"""请为 **子主题/子域详情** 编写 Wiki 页面。当前域：`{context.domain_name}`；上级域：`{context.parent_domain}`；兄弟域：{siblings}。

## 你必须在 JSON 的 content 中输出且仅使用以下 Markdown 章节（标题字面一致）
1. ## 业务概述 — 说明该子域为何存在、解决什么问题、如何嵌入父域（至少两段）
2. ## 核心业务流程 — 使用 **sequenceDiagram**，边与参与者须来自下方真实调用链；不足以支撑时说明「不生成图」
3. ## 核心服务详解 — 逐服务写清职责、关键方法签名、调用关系，并附 `source://仓库/文件:行`
4. ## 数据模型 — 若下方有 DTO/字段表则输出表格化 Markdown；若标明无数据则可写「本主题无独立数据模型」一段话
5. ## 设计要点与注意事项 — 容灾、异常、业务规则、边界条件等（基于上下文，禁止空泛）

## 参考数据：实体与方法
{entity_block}

## 参考数据：调用链
{chains}

## 参考数据：数据模型（DTO/Entity 字段）
{data_models}

## 参考数据：枚举与常量
{enums}

## 参考数据：关键代码片段
{snippets_block}

## 参考数据：跨域依赖
{cross_block}

请严格遵循系统提示中的 JSON 输出约定。"""

    tail = (context.existing_wiki_context or "").strip()
    if not tail:
        return base
    return (
        f"{base}\n\n"
        f"## 已有 Wiki 摘要（仅供对齐术语与历史描述，勿重复粘贴）\n{tail}"
    )
