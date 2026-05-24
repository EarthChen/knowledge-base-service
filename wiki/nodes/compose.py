"""Leaf module summaries and topic / domain page composition."""

import asyncio
import os
from collections import Counter
from typing import Any

from langchain_core.runnables import RunnableConfig

from core.log import get_logger
from wiki.context_gap import CONTEXT_GAP_RE, cleanup_context_gaps
from wiki.domain_complexity import DomainComplexityScorer
from wiki.domain_overview_composer import DomainOverviewComposer
from wiki.json_robust import parse_json_robust_sync
from wiki.models import PageType
from wiki.nodes.utils import (
    _build_page_data_for_semantic_diagrams,
    _collect_leaf_domains,
    select_key_snippets,
)
from wiki.pipeline_concurrency import PipelineConcurrency
from wiki.reasoning import TaskType, select_reasoning_level
from wiki.semantic_diagram_gen import SemanticDiagramGenerator
from wiki.token_budget import TokenBudgetCalculator, TokenBudgetResolver
from wiki.topic_structure_planner import TopicBasedStructurePlanner

log = get_logger(__name__)


async def _maybe_pipeline_progress(
    configurable: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """Call optional ``progress_callback`` from LangGraph configurable; swallow errors."""
    cb = configurable.get("progress_callback")
    if not cb:
        return
    try:
        await cb(payload)
    except Exception:
        log.debug("pipeline_progress_callback_failed", exc_info=True)


_LEAF_MODULE_SUMMARY_SYSTEM = (
    "你是代码模块分析专家。根据提供的模块信息生成结构化摘要。"
    "输出纯 JSON，不要 markdown 围栏。"
    "核心约束：你的输出必须严格基于提供的代码信息。"
    "禁止编造不存在的类名、方法名、服务名或架构组件。"
    "如果某些依赖模块或外部调用的上下文不足，在 summary_text 中用 "
    "<!-- CONTEXT_GAP: 描述 --> 标记缺失部分，不要编造。"
)

_LEAF_MODULE_SUMMARY_PROMPT = (
    """分析以下代码模块并生成结构化摘要。

模块名: {module_name}
仓库: {repository}

方法签名:
{methods}

调用关系:
{calls}

接口实现:
{impls}

外部调用者:
{callers}

代码片段:
{snippets}

请输出 JSON:
"""
    + (
        '{{"summary_text": "该模块的职责和核心业务逻辑描述（200-500字）", '
        '"key_methods": ["最重要的方法名, 最多5个"], '
        '"dependencies": ["该模块依赖的其他模块名"], '
        '"callers": ["调用该模块的外部模块名"]}}'
    )
)


async def _generate_diagrams_for_pages(
    pages: list[dict[str, Any]],
    llm: Any,
    domain_name: str,
    module_names: list[str],
    module_index: dict[str, list[dict]],
) -> None:
    """Generate semantic diagrams and attach to page dicts (in-place)."""
    import wiki.pipeline_nodes as _pn

    if not llm or not pages:
        return

    diag_gen = SemanticDiagramGenerator(llm)
    page_data = _build_page_data_for_semantic_diagrams(domain_name, module_names, module_index)
    try:
        digest = diag_gen.build_entity_digest(page_data)
    except Exception:
        _pn.log.warning("diagram_digest_build_failed", domain=domain_name, exc_info=True)
        digest = ""

    for page_dict in pages:
        page_type = (
            PageType.DOMAIN_OVERVIEW
            if page_dict.get("page_type") == "domain_overview"
            else PageType.TOPIC
        )
        try:
            diagrams = await diag_gen.generate_for_page(page_data, page_type, digest, "full")
            if diagrams:
                page_dict["diagrams"] = [
                    {
                        "title": d.title,
                        "type": d.diagram_type.value if hasattr(d.diagram_type, "value") else str(d.diagram_type),
                        "content": d.content,
                    }
                    for d in diagrams
                ]
        except Exception:
            _pn.log.warning("diagram_generation_failed", page=page_dict.get("title"), exc_info=True)


async def _enrich_pages_with_agent(
    pages: list[dict[str, Any]],
    llm: Any,
    graph_store: Any,
    domain_name: str,
) -> None:
    """Run WikiPageAgent on pages with CONTEXT_GAP markers (in-place)."""
    import wiki.pipeline_nodes as _pn

    if not llm or not graph_store:
        return

    for page_dict in pages:
        raw = page_dict.get("content", "")
        gap_count = len(CONTEXT_GAP_RE.findall(raw))
        if gap_count > 0:
            try:
                from wiki.page_agent import WikiPageAgent

                agent = WikiPageAgent(llm, graph_store)
                enriched = await agent.enrich(raw, domain_name=domain_name)
                page_dict["content"] = enriched
                _pn.log.info("agent_enrichment_applied", domain=domain_name, gaps=gap_count)
            except Exception:
                _pn.log.warning("agent_enrichment_failed", domain=domain_name, exc_info=True)


async def _sanitize_pages(
    pages: list[dict[str, Any]],
    known_entities: list[dict],
    covered_entity_uids: list[str],
    llm: Any = None,
) -> None:
    """Sanitize wiki content, repair broken Mermaid via LLM, and set covered_entity_uids (in-place)."""
    from wiki.page_agent import strip_agent_artifacts
    from wiki.source_ref_validator import (
        repair_broken_mermaid_blocks,
        sanitize_wiki_content,
    )

    for page_dict in pages:
        raw_content = page_dict.get("content", "")
        raw_content = strip_agent_artifacts(raw_content)
        page_dict["content"] = sanitize_wiki_content(raw_content, known_entities)
        if llm is not None:
            page_dict["content"] = await repair_broken_mermaid_blocks(
                page_dict["content"], llm,
            )
        page_dict["content"] = cleanup_context_gaps(page_dict.get("content", ""))
        page_dict["covered_entity_uids"] = covered_entity_uids


try:
    from wiki.llm_port import LLMPort
except ImportError:  # pragma: no cover

    class _LLMPortUnavailable:  # noqa: N801
        """Placeholder when wiki.llm_port is missing; isinstance never matches."""

        pass

    LLMPort = _LLMPortUnavailable  # type: ignore[misc, assignment]


_INCREMENTAL_CHANGE_RATIO = 0.3


async def _incremental_update_pages(
    domain_name: str,
    old_pages: list[dict[str, Any]],
    new_module_summaries: dict[str, str],
    llm: Any,
    token_budget: int = 4000,
) -> list[dict[str, Any]] | None:
    """Incrementally update existing pages with new module information.

    Returns updated pages, or None if incremental update is not possible
    (caller should fallback to full rewrite).
    """
    import wiki.pipeline_nodes as _pn

    if not old_pages or not new_module_summaries or not llm:
        return None

    change_desc_lines = []
    for mod_name, summary in new_module_summaries.items():
        change_desc_lines.append(f"- **{mod_name}**: {summary[:200]}")
    change_description = "\n".join(change_desc_lines)

    updated_pages: list[dict[str, Any]] = []
    for page in old_pages:
        old_content = page.get("content", "")
        if not old_content:
            return None

        prompt = (
            f'You are a Wiki editor. The domain "{domain_name}" has received new modules.\n'
            "Update the existing page to incorporate the new information.\n"
            "Keep most existing content unchanged. Only modify/add sections related to the changes.\n\n"
            f"## Existing Page Content\n{old_content[:3000]}\n\n"
            f"## New Modules Added\n{change_description}\n\n"
            "Output the complete updated page in markdown format."
        )

        messages = [{"role": "user", "content": prompt}]
        try:
            if isinstance(llm, LLMPort):
                result = await llm.complete_json(messages, {}, max_tokens=token_budget)
                if isinstance(result, str):
                    new_content = result.strip() or old_content
                elif isinstance(result, dict):
                    new_content = (
                        result.get("content")
                        or result.get("markdown")
                        or result.get("page")
                        or ""
                    )
                    if isinstance(new_content, str):
                        new_content = new_content.strip() or old_content
                    else:
                        new_content = old_content
                else:
                    new_content = str(result).strip() if result else old_content
            else:
                new_content = old_content
        except Exception:
            _pn.log.warning("incremental_update_failed", domain=domain_name, exc_info=True)
            return None

        updated_pages.append({**page, "content": new_content})

    return updated_pages


async def _compose_single_leaf_domain(
    leaf: dict[str, Any],
    module_index: dict[str, list[dict]],
    entity_roles: dict[str, Any],
    llm: Any,
    token_budget: int,
    *,
    graph_store: Any | None = None,
    wiki_store: Any | None = None,
    domain_mapping: dict[str, list] | None = None,
    module_summaries: dict[str, dict[str, Any]] | None = None,
    repo_path: str | None = None,
    search_service: Any | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Compose pages for one leaf domain (and optional diagrams when llm is set)."""
    import wiki.pipeline_nodes as _pn

    domain_name = leaf.get("name", "unknown")
    domain_display_name = str(leaf.get("display_name") or "").strip() or domain_name
    module_names = leaf.get("modules", [])
    biz_domain = _effective_business_domain(leaf)

    # --- Step 1: Always run CCB to collect structured context ---
    context = None
    covered_entity_uids: list[str] = []
    if graph_store is not None:
        from wiki.content_context_builder import ContentContextBuilder

        try:
            ccb = ContentContextBuilder(graph_store, wiki_store=wiki_store)
            context = await ccb.build_context(
                domain_name=domain_name,
                module_names=list(module_names),
                module_index=module_index,
                entity_roles=entity_roles,  # type: ignore[arg-type]
                domain_mapping=domain_mapping or {},
                depth=2,
                parent_domain=str(leaf.get("parent") or "root"),
                display_name=domain_display_name,
            )
            if module_summaries:
                names_set = set(module_names)
                relevant = {
                    k: str(v.get("summary_text", ""))
                    for k, v in module_summaries.items()
                    if k in names_set and v.get("summary_text")
                }
                context.module_leaf_summaries = relevant
            covered_entity_uids = [e.uid for e in context.biz_entities] + [
                str(d["uid"]) for d in context.data_models if d.get("uid")
            ]
        except Exception:
            _pn.log.warning(
                "ccb_context_build_failed",
                domain=domain_name,
                exc_info=True,
            )

    # --- Step 2: Agent-Driven path (uses CCB context as rich baseline) ---
    if llm is not None and graph_store is not None:
        from wiki.agent_config import AgentConfig, HarnessConfig

        agent_cfg = AgentConfig.from_env()
        if agent_cfg.should_use_agent(len(module_names)):
            try:
                from wiki.page_agent import WikiPageAgent
                from wiki.harness import WikiGenerationHarness

                agent = WikiPageAgent(
                    llm, graph_store, repo_path=repo_path, search_service=search_service
                )
                ccb_summary = context.format_summary_for_agent(max_chars=6000) if context else ""

                harness_cfg = HarnessConfig.from_env()
                if harness_cfg.enabled:
                    harness = WikiGenerationHarness(
                        agent=agent, graph_store=graph_store, llm=llm, config=harness_cfg
                    )
                    content = await harness.run(
                        domain=domain_name,
                        modules=list(module_names),
                        ccb_context=context,
                    )
                else:
                    content = await agent.generate(
                        module_names=list(module_names),
                        domain_name=domain_name,
                        baseline_context=ccb_summary or None,
                        max_rounds=5,
                    )
                if content and len(content) > 100:
                    page = {
                        "title": domain_display_name,
                        "content": content,
                        "path": f"wiki/{domain_name}",
                        "page_type": "topic",
                        "domain": domain_name,
                        "covered_entity_uids": covered_entity_uids,
                    }
                    pages = [page]
                    known_entities = [
                        {
                            "name": e.name,
                            "repository": e.repository,
                            "file_path": e.file_path,
                            "start_line": max(m.start_line for m in e.methods) if e.methods else 0,
                        }
                        for e in context.biz_entities
                    ] if context else []
                    await _sanitize_pages(pages, known_entities, covered_entity_uids, llm=llm)
                    _attach_business_domain_to_pages(pages, biz_domain)
                    _pn.log.info("agent_driven_generation_complete", domain=domain_name)
                    return pages, [page["path"]]
            except Exception:
                _pn.log.warning(
                    "agent_driven_failed_fallback_to_composer",
                    domain=domain_name,
                    exc_info=True,
                )

    # --- Step 3: TopicPageComposer path (uses same CCB context) ---
    if context is not None and llm is not None:
        try:
            overview_composer = DomainOverviewComposer(llm=llm)
            composer = _pn.TopicPageComposer(llm, token_budget=token_budget)
            pages = await composer.compose_leaf_domain_from_context(
                context, overview_composer=overview_composer
            )
            if not pages:
                return [], []
            await _generate_diagrams_for_pages(pages, llm, domain_name, module_names, module_index)
            await _enrich_pages_with_agent(pages, llm, graph_store, domain_name)
            known_entities = [
                {
                    "name": e.name,
                    "repository": e.repository,
                    "file_path": e.file_path,
                    "start_line": max(m.start_line for m in e.methods) if e.methods else 0,
                }
                for e in context.biz_entities
            ]
            await _sanitize_pages(pages, known_entities, covered_entity_uids, llm=llm)
            _attach_business_domain_to_pages(pages, biz_domain)
            return pages, [p.get("path", "") for p in pages]
        except Exception:
            _pn.log.warning(
                "composer_failed_fallback_to_legacy",
                domain=domain_name,
                exc_info=True,
            )

    biz_entities = []
    data_models = []
    for mod_name in module_names:
        for mod_dict in module_index.get(mod_name, []):
            uid = mod_dict.get("uid", f"Module::{mod_name}:0")
            role = entity_roles.get(uid, "supporting")
            props = mod_dict.get("properties", {})

            if str(role) not in ("framework_noise", "data_model"):
                biz_entities.append({
                    "uid": uid,
                    "name": mod_name,
                    "repository": mod_dict.get("_repo", ""),
                    "file_path": str(props.get("file", "") or props.get("file_path", "") or props.get("path", "")),
                    "summary": str(props.get("business_summary", "") or props.get("docstring", "") or ""),
                    "methods": [str(m) for m in (props.get("methods", []) or [])[:10]],
                    "calls": [str(c) for c in (props.get("calls", []) or [])[:15]],
                    "loc": int(props.get("loc", 0) or props.get("line_count", 0) or 0),
                })
            elif str(role) == "data_model":
                data_models.append({
                    "uid": uid,
                    "name": mod_name,
                    "type": "DTO",
                    "fields": [str(f) for f in (props.get("fields", []) or [])[:8]],
                })

    budget_calc = TokenBudgetCalculator()
    domain_modules = [
        md for m in module_names for md in module_index.get(m, [])
    ]
    snippets = select_key_snippets(
        domain_modules,
        entity_roles,
        budget_tokens=budget_calc.budget_for_snippets(len(domain_modules)),
    )
    snippet_section = ""
    if snippets:
        lines = [s.format_for_prompt() for s in snippets]
        snippet_section = "\n## Key Code Interfaces\n" + "\n".join(lines) + "\n"

    if len(data_models) > 20:
        _pn.log.info("data_models_truncated", domain=domain_name, total=len(data_models), kept=20)

    covered_entity_uids = [e["uid"] for e in biz_entities] + [d["uid"] for d in data_models[:20]]

    domain_input = {
        "name": domain_name,
        "parent": leaf.get("parent", "root"),
        "biz_entities": biz_entities,
        "data_models": data_models[:20],
        "sibling_summaries": [],
        "snippet_section": snippet_section,
    }

    scorer = DomainComplexityScorer()
    metrics = scorer.score(domain_input)
    reasoning_level = select_reasoning_level(TaskType.COMPOSE, metrics.complexity)
    composer = _pn.TopicPageComposer(
        llm,
        token_budget=token_budget,
        reasoning_level=reasoning_level,
        complexity_scorer=scorer,
    )

    try:
        pages = await composer.compose_leaf_domain(domain_input)
        await _generate_diagrams_for_pages(pages, llm, domain_name, module_names, module_index)
        known_ents = [
            {
                "name": e.get("name", ""),
                "repository": e.get("repository", ""),
                "file_path": e.get("file_path", ""),
                "start_line": 0,
            }
            for e in biz_entities
        ]
        await _sanitize_pages(pages, known_ents, covered_entity_uids, llm=llm)
        _attach_business_domain_to_pages(pages, biz_domain)
        return pages, [p.get("path", "") for p in pages]
    except Exception:
        _pn.log.warning("compose_pages_domain_failed", domain=domain_name, exc_info=True)
        return [], []


async def _generate_single_module_summary(
    module_name: str,
    module_dicts: list[dict],
    entity_roles: dict[str, str],
    llm: Any,
    *,
    graph_store: Any | None = None,
    neighbor_summaries: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Generate a leaf summary for a single module."""
    repo = ""
    methods_lines: list[str] = []
    calls_lines: list[str] = []
    for md in module_dicts:
        uid = md.get("uid", "")
        role = str(entity_roles.get(uid, "supporting"))
        if role == "framework_noise":
            return module_name, {}
        repo = repo or md.get("_repo", "")
        props = md.get("properties", {}) or {}
        for m in (props.get("methods", []) or [])[:10]:
            methods_lines.append(f"  - {m}")
        for c in (props.get("calls", []) or [])[:10]:
            calls_lines.append(f"  - {c}")

    impls_text = "（无）"
    callers_text = "（无）"
    snippets_text = "（无）"

    if graph_store is not None and hasattr(graph_store, "execute_query"):
        from wiki.cypher_queries import (
            CALLERS_CY as _CALLERS_CY,
        )
        from wiki.cypher_queries import (
            IMPLEMENTS_CY as _IMPLEMENTS_CY,
        )
        from wiki.cypher_queries import (
            SNIPPETS_CY as _SNIPPETS_CY,
        )
        try:
            impls_r, callers_r, snippets_r = await asyncio.gather(
                graph_store.execute_query(_IMPLEMENTS_CY, {"names": [module_name]}),
                graph_store.execute_query(_CALLERS_CY, {"names": [module_name]}),
                graph_store.execute_query(_SNIPPETS_CY, {"names": [module_name]}),
                return_exceptions=True,
            )
            if not isinstance(impls_r, BaseException):
                rows = getattr(impls_r, "data", None) or []
                il = [
                    f"  - {r.get('impl_name', '')} implements {r.get('interface_name', '')}"
                    for r in rows
                    if isinstance(r, dict)
                ]
                if il:
                    impls_text = "\n".join(il)
            if not isinstance(callers_r, BaseException):
                rows = getattr(callers_r, "data", None) or []
                cl = [
                    f"  - {r.get('caller_name', '')} → {module_name}"
                    for r in rows
                    if isinstance(r, dict)
                ]
                if cl:
                    callers_text = "\n".join(cl)
            if not isinstance(snippets_r, BaseException):
                rows = getattr(snippets_r, "data", None) or []
                sl = []
                for r in rows:
                    if isinstance(r, dict):
                        sn = str(r.get("snippet", "") or "").strip()
                        fn = str(r.get("func_name", "") or "")
                        if sn:
                            sl.append(f"// {fn}\n{sn[:400]}")
                if sl:
                    snippets_text = "\n".join(sl[:3])
        except Exception:
            log.warning("leaf_module_graph_query_failed", module=module_name, exc_info=True)

    neighbor_block = ""
    if neighbor_summaries:
        deps = set()
        for c in calls_lines:
            parts = c.strip().lstrip("- ").split(".")
            if parts:
                deps.add(parts[0])
        relevant = {k: v for k, v in neighbor_summaries.items() if k in deps and k != module_name}
        if relevant:
            nb_lines = [f"  - {k}: {v[:200]}" for k, v in list(relevant.items())[:5]]
            neighbor_block = "\n\n依赖模块的摘要:\n" + "\n".join(nb_lines)

    prompt = _LEAF_MODULE_SUMMARY_PROMPT.format(
        module_name=module_name,
        repository=repo,
        methods="\n".join(methods_lines) or "（无）",
        calls="\n".join(calls_lines) or "（无）",
        impls=impls_text,
        callers=callers_text,
        snippets=snippets_text,
    ) + neighbor_block

    messages = [
        {"role": "system", "content": _LEAF_MODULE_SUMMARY_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    try:
        if hasattr(llm, "complete_json"):
            try:
                result = await llm.complete_json(messages, {}, max_tokens=2000)
            except (ValueError, Exception):
                log.warning(
                    "leaf_module_summary_complete_json_failed",
                    module=module_name,
                    exc_info=True,
                )
                return module_name, {}
            if isinstance(result, dict) and result.get("summary_text"):
                return module_name, result
            return module_name, {}
        raw = await llm.generate(prompt, system=_LEAF_MODULE_SUMMARY_SYSTEM, max_tokens=2000)
        parsed = parse_json_robust_sync(raw)
        if isinstance(parsed, dict) and parsed.get("summary_text"):
            return module_name, parsed
        return module_name, {"summary_text": (raw or "").strip()[:500]}
    except Exception:
        log.warning("leaf_module_summary_failed", module=module_name, exc_info=True)
        return module_name, {}


async def compose_leaf_modules_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Generate leaf-level summaries for individual modules (Bottom-Up Phase).

    Round 1: all modules independently in parallel.
    Round 2: modules with CONTEXT_GAP re-generated with neighbor summaries.
    """
    summaries_only = os.environ.get("USE_AGENT_COMPOSE", "false").lower() == "true"

    configurable = (config or {}).get("configurable", {}) or {}
    llm = configurable.get("llm")
    graph_store = configurable.get("graph_store")

    if not llm:
        log.info("compose_leaf_modules_skip", reason="no_llm")
        return {"module_summaries": {}}

    modules = state.get("modules", {})
    entity_roles = state.get("entity_roles", {})

    module_index: dict[str, list[dict]] = {}
    for repo_name, mod_list in modules.items():
        for mod_dict in mod_list:
            name = mod_dict.get("properties", {}).get("name", "")
            if name:
                mod_dict["_repo"] = repo_name
                module_index.setdefault(name, []).append(mod_dict)

    target_modules = []
    for name, dicts in module_index.items():
        dominated_role = "supporting"
        for d in dicts:
            uid = d.get("uid", "")
            role = str(entity_roles.get(uid, "supporting"))
            if role in ("entry_point", "has_business_logic"):
                dominated_role = role
                break
            elif role != "framework_noise":
                dominated_role = role
        if dominated_role not in ("framework_noise", "data_model"):
            target_modules.append(name)

    if not target_modules:
        return {"module_summaries": {}}

    sem = PipelineConcurrency.semaphore("compose")

    async def _bounded_r1(name: str) -> tuple[str, dict[str, Any]]:
        async with sem:
            return await _generate_single_module_summary(
                name, module_index.get(name, []), entity_roles, llm,
                graph_store=graph_store,
            )

    log.info("compose_leaf_modules_round1_start", module_count=len(target_modules))
    r1_results = await asyncio.gather(
        *[_bounded_r1(m) for m in target_modules],
        return_exceptions=True,
    )

    module_summaries: dict[str, dict[str, Any]] = {}
    total_mod = len(target_modules)
    for i, item in enumerate(r1_results, start=1):
        if isinstance(item, BaseException):
            log.warning("compose_leaf_module_failed", exc_info=item)
            continue
        name, summary = item
        if summary:
            module_summaries[name] = summary
        frac = i / max(total_mod, 1)
        await _maybe_pipeline_progress(
            configurable,
            {
                "phase": "compose_leaf_modules",
                "progress_pct": 0.10 + frac * 0.15,
                "detail": f"模块摘要 {i}/{total_mod}",
            },
        )

    r1_summary_texts = {
        k: str(v.get("summary_text", ""))
        for k, v in module_summaries.items()
        if v.get("summary_text")
    }

    def _needs_round2(name: str, s: dict[str, Any]) -> bool:
        text = str(s.get("summary_text", ""))
        if "CONTEXT_GAP" in text:
            return True
        if len(text) < 100:
            return True
        deps = s.get("dependencies") or []
        if isinstance(deps, list) and any(d in r1_summary_texts for d in deps):
            return True
        return False

    gaps = [name for name, s in module_summaries.items() if _needs_round2(name, s)]

    if gaps and r1_summary_texts:
        log.info("compose_leaf_modules_round2_start", gap_count=len(gaps))

        async def _bounded_r2(name: str) -> tuple[str, dict[str, Any]]:
            async with sem:
                return await _generate_single_module_summary(
                    name, module_index.get(name, []), entity_roles, llm,
                    graph_store=graph_store,
                    neighbor_summaries=r1_summary_texts,
                )

        r2_results = await asyncio.gather(
            *[_bounded_r2(m) for m in gaps],
            return_exceptions=True,
        )
        for item in r2_results:
            if isinstance(item, BaseException):
                continue
            name, summary = item
            if summary:
                module_summaries[name] = summary

    await _maybe_pipeline_progress(
        configurable,
        {
            "phase": "compose_leaf_modules",
            "progress_pct": 0.10
            + (len(module_summaries) / max(total_mod, 1)) * 0.15,
            "detail": f"模块摘要 {len(module_summaries)}/{total_mod}（完成）",
        },
    )

    log.info(
        "compose_leaf_modules_done",
        total_modules=len(target_modules),
        summaries_generated=len(module_summaries),
        round2_count=len(gaps),
    )
    if summaries_only:
        return {
            "module_summaries": module_summaries,
            "pages": [],
            "errors": list(state.get("errors", [])),
        }
    return {"module_summaries": module_summaries}


async def plan_topic_structure_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Plan topic-based wiki structure using LLM."""
    llm = (config or {}).get("configurable", {}).get("llm")
    if not llm:
        log.info("plan_topic_structure_skip", reason="no_llm")
        return {"topic_structure": None}

    domain_mapping = state.get("domain_mapping", {})
    if not domain_mapping:
        return {"topic_structure": None}

    modules = state.get("modules", {})
    entity_roles = state.get("entity_roles", {})

    module_metadata: dict[tuple[str, str], dict[str, Any]] = {}
    importance_tiers: dict[str, str] = {}

    for repo_name, mod_list in modules.items():
        for mod_dict in mod_list:
            props = mod_dict.get("properties", {})
            name = props.get("name", "")
            uid = mod_dict.get("uid", "")
            if not name:
                continue
            module_metadata[(repo_name, name)] = {
                "summary": props.get("business_summary", "") or props.get("docstring", ""),
                "methods": props.get("methods", []),
                "calls": props.get("calls", []),
            }
            role = str(entity_roles.get(uid, "supporting"))
            if role == "framework_noise":
                importance_tiers[name] = "skeleton"
            elif role in ("has_business_logic", "entry_point"):
                importance_tiers[name] = "core"
            else:
                importance_tiers[name] = "standard"

    language = state.get("language", "zh") or "zh"

    planner = TopicBasedStructurePlanner(llm)
    topic_pages = await planner.plan(
        domain_mapping, module_metadata, importance_tiers,
        language=language,
    )

    topic_dicts = [
        {
            "title": tp.title,
            "description": tp.description,
            "covered_modules": tp.covered_modules,
            "sub_topics": [
                {
                    "title": st.title,
                    "description": st.description,
                    "covered_modules": st.covered_modules,
                }
                for st in tp.sub_topics
            ],
        }
        for tp in topic_pages
    ]

    log.info("topic_structure_planned", topic_count=len(topic_dicts))
    return {"topic_structure": topic_dicts}


def _business_domain_for_topic_modules(
    covered_modules: list[Any],
    domain_mapping: dict[str, list],
) -> str | None:
    """Resolve canonical domain name(s) from topic ``covered_modules`` via ``domain_mapping``."""
    if not covered_modules or not domain_mapping:
        return None
    mod_to_domain: dict[tuple[str, str], str] = {}
    for dom_name, pairs in domain_mapping.items():
        for pair in pairs or []:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                mod_to_domain[(str(pair[0]), str(pair[1]))] = str(dom_name)
    votes: Counter[str] = Counter()
    for entry in covered_modules:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            d = mod_to_domain.get((str(entry[0]), str(entry[1])))
            if d:
                votes[d] += 1
    if not votes:
        return None
    return votes.most_common(1)[0][0]


def _effective_business_domain(leaf: dict[str, Any]) -> str | None:
    """Chinese business-domain label for tree linking; topic leaves set explicit ``business_domain``."""
    if "business_domain" in leaf:
        raw = leaf.get("business_domain")
        return str(raw).strip() if raw else None
    name = leaf.get("name")
    return str(name).strip() if name else None


def _attach_business_domain_to_pages(
    pages: list[dict[str, Any]], biz_domain: str | None
) -> None:
    if not biz_domain:
        return
    for p in pages:
        p["business_domain"] = biz_domain


def _topic_to_domain_dict(
    topic: dict[str, Any],
    module_index: dict[str, list[dict]],
    domain_mapping: dict[str, list] | None = None,
) -> dict[str, Any]:
    """Convert a TopicPage dict into the domain dict format expected by
    _compose_single_leaf_domain."""
    covered = topic.get("covered_modules", [])
    module_names = [name for _repo, name in covered]
    bd = _business_domain_for_topic_modules(covered, domain_mapping or {})
    return {
        "name": topic["title"],
        "modules": module_names,
        "children": [],
        "business_domain": bd,
    }


async def _compose_from_topic_structure(
    topic_structure: list[dict[str, Any]],
    module_index: dict[str, list[dict]],
    entity_roles: dict[str, Any],
    llm: Any,
    *,
    graph_store: Any | None = None,
    wiki_store: Any | None = None,
    domain_mapping: dict[str, list] | None = None,
    module_summaries: dict[str, dict[str, Any]] | None = None,
    repo_path: str | None = None,
    search_service: Any | None = None,
) -> dict[str, Any]:
    """Compose pages from TopicBasedStructurePlanner output."""
    import wiki.pipeline_nodes as _pn

    budget_resolver = TokenBudgetResolver()
    budget = budget_resolver.budget("topic_page_generate")
    sem = PipelineConcurrency.semaphore("compose")

    all_pages: list[dict[str, Any]] = []
    generated_uids: list[str] = []

    async def _compose_topic(topic: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        async with sem:
            domain_dict = _topic_to_domain_dict(topic, module_index, domain_mapping)
            return await _pn._compose_single_leaf_domain(
                domain_dict,
                module_index,
                entity_roles,
                llm,
                budget,
                graph_store=graph_store,
                wiki_store=wiki_store,
                domain_mapping=domain_mapping,
                module_summaries=module_summaries,
                repo_path=repo_path,
                search_service=search_service,
            )

    all_topics = list(topic_structure)
    for t in topic_structure:
        for sub in t.get("sub_topics", []):
            all_topics.append(sub)

    results = await asyncio.gather(
        *[_compose_topic(t) for t in all_topics],
        return_exceptions=True,
    )
    for item in results:
        if isinstance(item, BaseException):
            log.warning("compose_topic_failed", exc_info=item)
            continue
        pages, uids = item
        all_pages.extend(pages)
        generated_uids.extend(uids)

    log.info("compose_from_topics_done", total_pages=len(all_pages))
    return {"pages": all_pages, "generated_topic_pages": generated_uids}


def _merge_small_leaves(
    leaves: list[dict], min_modules: int = 3
) -> list[dict]:
    """Merge leaf domains with < min_modules into sibling or nearest leaf."""
    import wiki.pipeline_nodes as _pn

    large = [l for l in leaves if len(l.get("modules", [])) >= min_modules]
    small = [l for l in leaves if len(l.get("modules", [])) < min_modules]

    if not small:
        return large

    for sl in small:
        same_parent = [l for l in large if l.get("parent") == sl.get("parent")]
        target = same_parent[0] if same_parent else (large[0] if large else None)
        if target is None:
            large.append(sl)
            continue
        target["modules"] = list(set(target.get("modules", []) + sl.get("modules", [])))
        _pn.log.info(
            "compose_leaf_merged",
            small=sl.get("name"),
            into=target.get("name"),
            added=len(sl.get("modules", [])),
        )

    return large


async def compose_leaf_pages_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Phase 3: generate topic pages for each leaf domain."""
    import wiki.pipeline_nodes as _pn

    configurable = (config or {}).get("configurable", {}) or {}
    llm = configurable.get("llm")
    graph_store = configurable.get("graph_store")
    wiki_store = configurable.get("wiki_store")
    repo_path = state.get("repo_path") or configurable.get("repo_path")
    search_service = state.get("search_service") or configurable.get("search_service")
    domain_mapping = state.get("domain_mapping") or {}
    domain_tree = state.get("domain_tree") or []
    entity_roles = state.get("entity_roles", {})
    modules = state.get("modules", {})

    module_index: dict[str, list[dict]] = {}
    for repo_name, mod_list in modules.items():
        for mod_dict in mod_list:
            name = mod_dict.get("properties", {}).get("name", "")
            if name:
                mod_dict["_repo"] = repo_name
                module_index.setdefault(name, []).append(mod_dict)

    mod_summaries = state.get("module_summaries") or {}

    topic_structure = state.get("topic_structure")
    if topic_structure:
        all_topics = list(topic_structure)
        for t in topic_structure:
            for sub in t.get("sub_topics", []):
                all_topics.append(sub)
        out = await _compose_from_topic_structure(
            topic_structure,
            module_index,
            entity_roles,
            llm,
            graph_store=graph_store,
            wiki_store=wiki_store,
            domain_mapping=domain_mapping,
            module_summaries=mod_summaries,
            repo_path=repo_path,
            search_service=search_service,
        )
        pages_out = out.get("pages") or []

        # Ensure every leaf domain in domain_tree has at least one topic page
        if domain_tree:
            covered_modules: set[str] = set()
            for t in all_topics:
                for _repo, name in t.get("covered_modules", []):
                    covered_modules.add(name)

            leaf_domains = _collect_leaf_domains(domain_tree)
            uncovered_leaves = [
                leaf for leaf in leaf_domains
                if leaf.get("modules") and not (set(leaf.get("modules", [])) & covered_modules)
            ]

            if uncovered_leaves:
                _pn.log.info(
                    "topic_coverage_gap_detected",
                    uncovered_count=len(uncovered_leaves),
                    names=[l.get("name") for l in uncovered_leaves[:10]],
                )
                budget_resolver = TokenBudgetResolver()
                budget = budget_resolver.budget("topic_page_generate")
                sem = PipelineConcurrency.semaphore("compose")

                async def _fill_gap(leaf: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
                    async with sem:
                        return await _pn._compose_single_leaf_domain(
                            leaf, module_index, entity_roles, llm, budget,
                            graph_store=graph_store, wiki_store=wiki_store,
                            domain_mapping=domain_mapping, module_summaries=mod_summaries,
                            repo_path=repo_path, search_service=search_service,
                        )

                gap_results = await asyncio.gather(
                    *[_fill_gap(leaf) for leaf in uncovered_leaves],
                    return_exceptions=True,
                )
                for item in gap_results:
                    if isinstance(item, BaseException):
                        _pn.log.warning("compose_gap_fill_failed", exc_info=item)
                        continue
                    gap_pages, gap_uids = item
                    pages_out.extend(gap_pages)
                    out.setdefault("generated_topic_pages", []).extend(gap_uids)

                out["pages"] = pages_out
                _pn.log.info("topic_coverage_filled", extra_pages=len(pages_out) - len(out.get("pages", [])))

        await _maybe_pipeline_progress(
            configurable,
            {
                "phase": "compose_leaf",
                "progress_pct": 0.64,
                "detail": f"页面合成 {len(pages_out)} 页, {len(all_topics)} 域",
            },
        )
        return out

    budget_resolver = TokenBudgetResolver()
    budget = budget_resolver.budget("topic_page_generate")

    all_pages: list[dict[str, Any]] = []
    generated_uids: list[str] = []

    leaf_domains = _collect_leaf_domains(domain_tree)
    leaf_domains = _merge_small_leaves(leaf_domains, min_modules=3)

    # P0.1: Filter by affected domains in light reorg
    reorg_type = state.get("reorg_type", "full")
    affected_domains_list = state.get("affected_domains", [])
    affected_domains_set = set(affected_domains_list) if affected_domains_list else set()

    if reorg_type == "light" and affected_domains_set:
        original_count = len(leaf_domains)
        leaf_domains = [
            d for d in leaf_domains
            if d.get("name") in affected_domains_set or d.get("parent") in affected_domains_set
        ]
        _pn.log.info(
            "compose_leaf_pages_filtered",
            original=original_count,
            filtered=len(leaf_domains),
            reorg_type=reorg_type,
        )
    elif reorg_type == "none":
        _pn.log.info("compose_leaf_pages_skip_none_reorg")
        return {"pages": [], "generated_topic_pages": []}

    # Apply topological ordering for dependency-first generation
    from wiki.topo_sort import topological_order

    leaves = leaf_domains
    if len(leaves) > 1:
        domain_edges: dict[str, list[str]] = {}
        leaf_name_set = {leaf.get("name", ""): set(leaf.get("modules", [])) for leaf in leaves}

        for leaf in leaves:
            leaf_name = leaf.get("name", "")
            leaf_mods = leaf_name_set.get(leaf_name, set())
            deps = []
            for other_name, other_mods in leaf_name_set.items():
                if other_name != leaf_name and leaf_mods & other_mods:
                    deps.append(other_name)
            if deps:
                domain_edges[leaf_name] = deps

        if domain_edges:
            ordered_names = topological_order(domain_edges)
            name_to_leaf = {leaf.get("name", ""): leaf for leaf in leaves}
            ordered_leaves = []
            for name in ordered_names:
                if name in name_to_leaf:
                    ordered_leaves.append(name_to_leaf.pop(name))
            ordered_leaves.extend(name_to_leaf.values())
            leaf_domains = ordered_leaves

    sem = PipelineConcurrency.semaphore("compose")

    async def _bounded(leaf: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        async with sem:
            return await _pn._compose_single_leaf_domain(
                leaf,
                module_index,
                entity_roles,
                llm,
                budget,
                graph_store=graph_store,
                wiki_store=wiki_store,
                domain_mapping=domain_mapping,
                module_summaries=mod_summaries,
                repo_path=repo_path,
                search_service=search_service,
            )

    results = await asyncio.gather(
        *[_bounded(leaf) for leaf in leaf_domains],
        return_exceptions=True,
    )
    for item in results:
        if isinstance(item, BaseException):
            _pn.log.warning("compose_pages_domain_failed", exc_info=item)
            continue
        pages, uids = item
        all_pages.extend(pages)
        generated_uids.extend(uids)

    await _maybe_pipeline_progress(
        configurable,
        {
            "phase": "compose_leaf",
            "progress_pct": 0.64,
            "detail": f"页面合成 {len(all_pages)} 页, {len(leaf_domains)} 域",
        },
    )

    _pn.log.info("compose_pages_done", total_pages=len(all_pages), domains_processed=len(leaf_domains))
    return {"pages": all_pages, "generated_topic_pages": generated_uids}
