"""Business flow inference — identifies business flows from call chains using LLM."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from store.indexer_store import IndexerStore

if TYPE_CHECKING:
    from llm.provider import LLMProvider
    from store.falkordb_store import FalkorDBStore

logger = logging.getLogger(__name__)

_FLOW_INFERENCE_PROMPT = """以下是一条代码调用链。请分析它实现的业务流程。

调用链:
{chain_text}

请输出 JSON:
{{
  "flow_name": "业务流程名称",
  "description": "流程描述",
  "category": "分类（如交易、用户、内容、系统）",
  "steps": [
    {{"function": "函数名", "role": "entry_point|processor|validator|notifier|persistence|external_call", "order": 1}}
  ],
  "sub_flows": [
    {{"name": "子流程名", "description": "描述", "steps": [...]}}
  ]
}}"""


class BusinessFlowInferencer:
    """Infers business flows from code call chains."""

    def __init__(
        self,
        llm: LLMProvider,
        store: FalkorDBStore,
        *,
        business_flow_enabled: bool | None = None,
        indexer_store: IndexerStore | None = None,
    ) -> None:
        self._llm = llm
        self._store = store
        self._idx = indexer_store or IndexerStore(store)
        if business_flow_enabled is None:
            from config import get_settings

            business_flow_enabled = get_settings().llm.business_flow_enabled
        self._business_flow_enabled = business_flow_enabled

    async def infer_from_chain(self, chain: list[dict[str, str]]) -> dict[str, Any] | None:
        """Infer a business flow from a call chain."""
        if not self._business_flow_enabled:
            return None
        chain_text = "\n".join(
            f"  {'→ ' if i > 0 else ''}{item['name']} ({item.get('business_summary', 'N/A')}) [{item.get('file', '')}]"
            for i, item in enumerate(chain)
        )
        prompt = _FLOW_INFERENCE_PROMPT.format(chain_text=chain_text)
        try:
            return await self._llm.complete_json(
                [{"role": "user", "content": prompt}],
                schema={"type": "object"},
            )
        except Exception:
            logger.warning("Failed to infer flow from chain starting with %s", chain[0].get("name"), exc_info=True)
            return None

    async def find_entry_points(self) -> list[dict[str, Any]]:
        """Find entry point functions in the graph.

        Entry points are:
        1. Strong: Functions with HTTP/RPC/Kafka annotations
        2. Weak: Functions with no CALLS inbound but having CALLS outbound
        """

        def _props_from_row(node: Any) -> dict[str, Any]:
            if hasattr(node, "properties"):
                return dict(node.properties)
            if isinstance(node, dict):
                return dict(node)
            return {}

        strong_rows: list[Any] = []
        try:
            strong_func_result = await self._idx.entry_points_semantic_functions()
            strong_class_result = await self._idx.entry_points_semantic_controller_classes()
            for d in (strong_func_result.data or []) + (strong_class_result.data or []):
                strong_rows.append(d.get("f"))
        except Exception:
            logger.warning(
                "Semantic entry-point queries failed; falling back to signature-based matching",
                exc_info=True,
            )

        if not strong_rows:
            legacy_result = await self._idx.entry_points_legacy_signatures()
            strong_rows = [d.get("f") for d in (legacy_result.data or [])]

        weak_result = await self._idx.entry_points_weak_leaf_functions()

        entries = []
        seen: set[str] = set()
        for node in strong_rows:
            if node is None:
                continue
            props = _props_from_row(node)
            uid = props.get("uid", props.get("name", ""))
            if uid not in seen:
                seen.add(uid)
                entries.append({**props, "_entry_type": "strong"})

        for row in weak_result.data or []:
            node = row.get("f")
            if node is None:
                continue
            props = _props_from_row(node)
            uid = props.get("uid", props.get("name", ""))
            if uid not in seen:
                seen.add(uid)
                entries.append({**props, "_entry_type": "weak"})

        return entries
