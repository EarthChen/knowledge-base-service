#!/usr/bin/env python3
"""POC: Agent-Driven Wiki generation for a single domain.

Usage:
    uv run scripts/poc_agent_wiki.py --business-id <id> [--domain <name>] [--output-dir ./poc_output]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ENTRY_KEYWORDS = ("Controller", "Handler", "Consumer", "Listener", "Endpoint", "Resource")


def build_structured_baseline(
    domain_name: str,
    module_names: list[str],
    module_summaries: dict[str, str],
) -> str:
    entry = [m for m in module_names if any(k in m for k in ENTRY_KEYWORDS)]
    other = [m for m in module_names if m not in entry]

    parts = [
        f"## 域信息",
        f"域名: {domain_name}",
        f"模块数: {len(module_names)}",
    ]
    if entry:
        parts.append("\n## 入口模块（优先查询调用链）")
        for m in entry:
            summary = module_summaries.get(m, "")
            line = f"- `{m}`"
            if summary:
                line += f" — {summary[:200]}"
            parts.append(line)
    if other:
        parts.append("\n## 其他模块")
        for m in other:
            summary = module_summaries.get(m, "")
            line = f"- `{m}`"
            if summary:
                line += f" — {summary[:200]}"
            parts.append(line)
    return "\n".join(parts)


def select_poc_domain(
    domains: dict[str, list[str]],
    min_size: int = 5,
    max_size: int = 15,
) -> tuple[str, list[str]]:
    candidates = []
    for name, modules in domains.items():
        if min_size <= len(modules) <= max_size:
            has_entry = any(any(k in m for k in ENTRY_KEYWORDS) for m in modules)
            candidates.append((name, modules, has_entry))

    if not candidates:
        by_size = sorted(domains.items(), key=lambda x: abs(len(x[1]) - 10))
        return by_size[0]

    with_entry = [c for c in candidates if c[2]]
    if with_entry:
        best = sorted(with_entry, key=lambda c: abs(len(c[1]) - 10))[0]
        return best[0], best[1]

    best = sorted(candidates, key=lambda c: abs(len(c[1]) - 10))[0]
    return best[0], best[1]


async def run_poc(business_id: str, domain_name: str | None, output_dir: str) -> None:
    # Add project root to sys.path for imports
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from core.config import get_settings
    from store.falkordb_store import FalkorDBStore
    from wiki.llm_port import LLMPort
    from wiki.model_strategy import get_model_strategy
    from wiki.page_agent import WikiPageAgent
    from wiki.quality_report import evaluate_quality

    settings = get_settings()
    graph = FalkorDBStore(settings)
    await graph.connect()

    strategy = get_model_strategy(settings)
    llm: LLMPort = await strategy.get_llm_port("wiki_compose")

    # Step 1: Test function calling
    print("=== Step 1: LLM Function Calling Test ===")
    test_messages = [
        {"role": "system", "content": "You are a test assistant."},
        {"role": "user", "content": "Call the test_tool with name='hello'."},
    ]
    test_tools = [{
        "type": "function",
        "function": {
            "name": "test_tool",
            "description": "A test tool",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    }]
    try:
        response = await llm.complete_with_tools(test_messages, test_tools)
        tool_calls = response.get("tool_calls", [])
        print(f"  Function calling: {'SUPPORTED' if tool_calls else 'NOT SUPPORTED (no tool_calls)'}")
        print(f"  Response keys: {list(response.keys())}")
        if tool_calls:
            print(f"  Tool calls: {json.dumps(tool_calls, ensure_ascii=False, default=str)[:500]}")
    except Exception as e:
        print(f"  Function calling: FAILED — {e}")

    # Step 2: Get domain list
    print("\n=== Step 2: Domain Selection ===")
    domain_cy = (
        "MATCH (m:Module) WHERE m.repository STARTS WITH $biz "
        "AND m.business_domain IS NOT NULL "
        "RETURN m.business_domain AS domain, collect(m.name) AS modules"
    )
    result = await graph.execute_query(domain_cy, {"biz": business_id})
    rows = getattr(result, "data", None) or []
    domains = {str(r["domain"]): list(r["modules"]) for r in rows if isinstance(r, dict)}
    print(f"  Found {len(domains)} domains")
    for d, mods in sorted(domains.items(), key=lambda x: -len(x[1]))[:10]:
        print(f"    {d}: {len(mods)} modules")

    if domain_name and domain_name in domains:
        selected_name = domain_name
        selected_modules = domains[domain_name]
    else:
        selected_name, selected_modules = select_poc_domain(domains)
    print(f"\n  Selected: {selected_name} ({len(selected_modules)} modules)")
    print(f"  Modules: {selected_modules[:10]}{'...' if len(selected_modules) > 10 else ''}")

    # Step 3: Build baseline and run Agent
    print("\n=== Step 3: Agent Generation ===")
    baseline = build_structured_baseline(selected_name, selected_modules, {})
    agent = WikiPageAgent(llm=llm, graph_store=graph, repo_path=None)

    t0 = time.monotonic()
    content = await agent.generate(
        module_names=selected_modules,
        domain_name=selected_name,
        baseline_context=baseline,
        max_rounds=10,
    )
    elapsed = time.monotonic() - t0
    print(f"  Generation time: {elapsed:.1f}s")
    print(f"  Content length: {len(content)} chars")

    # Step 4: Quality evaluation
    print("\n=== Step 4: Quality Evaluation ===")
    report = evaluate_quality(content, selected_modules)
    print(f"  Coverage: {report.coverage:.2%}")
    print(f"  Citation density: {report.citation_density:.2f}")
    print(f"  Context gaps: {report.context_gap_count}")
    print(f"  Visual aids (Mermaid): {report.visual_aids_count}")
    print(f"  Uncovered modules: {report.uncovered_modules}")
    print(f"  Acceptable: {report.is_acceptable}")

    # Step 5: Write output
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    (out / f"{selected_name}.md").write_text(content, encoding="utf-8")
    (out / f"{selected_name}_report.json").write_text(
        json.dumps({
            "domain": selected_name,
            "modules": selected_modules,
            "elapsed_sec": round(elapsed, 1),
            "content_length": len(content),
            "coverage": report.coverage,
            "citation_density": report.citation_density,
            "context_gap_count": report.context_gap_count,
            "visual_aids_count": report.visual_aids_count,
            "uncovered_modules": report.uncovered_modules,
            "is_acceptable": report.is_acceptable,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n  Output: {out / f'{selected_name}.md'}")
    print(f"  Report: {out / f'{selected_name}_report.json'}")

    await graph.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="POC: Agent-Driven Wiki Generation")
    parser.add_argument("--business-id", required=True, help="Business ID (e.g. kb_ultron)")
    parser.add_argument("--domain", default=None, help="Specific domain name (auto-select if omitted)")
    parser.add_argument("--output-dir", default="./poc_output", help="Output directory")
    args = parser.parse_args()
    asyncio.run(run_poc(args.business_id, args.domain, args.output_dir))


if __name__ == "__main__":
    main()
