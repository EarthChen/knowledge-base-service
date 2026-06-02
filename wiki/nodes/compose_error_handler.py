"""Error handler for compose_domain_agents node.

When the compose node fails after retries (e.g., timeout), this handler
produces skeleton fallback pages so domains are not lost entirely.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Command

from core.log import get_logger
from wiki.path_conventions import domain_overview_path

log = get_logger(__name__)


def _flatten_domain_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recursively flatten domain tree to include all container + leaf nodes."""
    result: list[dict[str, Any]] = []
    for node in nodes:
        result.append(node)
        children = node.get("children", [])
        if children:
            result.extend(_flatten_domain_tree(children))
    return result


async def compose_error_fallback(state: dict[str, Any], *, error: Any) -> Command:
    """Produce skeleton pages for domains that failed to generate.

    Called by LangGraph when compose_domain_agents exhausts retries.
    Identifies which domains do NOT yet have a page in state["pages"],
    and creates minimal skeleton pages with error details.

    Args:
        state: LangGraph state dict with "pages" and "domain_tree".
        error: NodeError from LangGraph — wraps the real exception in .error attribute.
    """
    real_error = getattr(error, "error", error)
    error_type = type(real_error).__name__
    error_msg = str(real_error) or "timeout/cancelled"

    existing_pages: list[dict[str, Any]] = state.get("pages", [])
    domain_tree: list[dict[str, Any]] = state.get("domain_tree") or []

    existing_paths = {p.get("path") for p in existing_pages if p.get("path")}

    skeleton_pages: list[dict[str, Any]] = []

    for domain in _flatten_domain_tree(domain_tree):
        slug = domain.get("slug") or domain.get("name", "unknown")
        path = domain_overview_path(slug)
        if path in existing_paths:
            continue

        display = domain.get("display_name") or domain.get("name") or slug
        modules = domain.get("modules") or []
        modules_list = "\n".join(f"- `{m}`" for m in modules[:50])
        if len(modules) > 50:
            modules_list += f"\n- ... and {len(modules) - 50} more"

        content = (
            f"# {display}\n\n"
            f"> ⚠️ 文档生成失败 ({error_type}: {error_msg[:100]})\n\n"
            f"## 域内模块 ({len(modules)} 个)\n\n"
            f"{modules_list}"
        )

        skeleton_pages.append(
            {
                "page_type": "domain_overview",
                "title": display,
                "path": path,
                "content": content,
                "metadata": {
                    "generation_mode": "error_fallback",
                    "error_type": error_type,
                    "error_msg": error_msg[:200],
                },
                "__degraded__": True,
            }
        )

    if skeleton_pages:
        log.warning(
            "compose_error_fallback_produced_skeletons",
            count=len(skeleton_pages),
            error_type=error_type,
            paths=[p["path"] for p in skeleton_pages],
        )

    return Command(
        update={"pages": existing_pages + skeleton_pages},
        goto="quality_gate",
    )
