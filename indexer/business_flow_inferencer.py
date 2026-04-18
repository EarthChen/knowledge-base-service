"""Business flow inference — identifies business flows from call chains using LLM."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

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
    ) -> None:
        self._llm = llm
        self._store = store
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
        loop = asyncio.get_running_loop()

        strong_func_query = (
            "MATCH (f:Function) "
            "WHERE f.semantic_roles IS NOT NULL AND "
            "ANY(r IN f.semantic_roles WHERE r IN "
            "['http_endpoint', 'rpc_consumer', 'message_listener', 'scheduled_task']) "
            "RETURN f"
        )

        strong_class_query = (
            "MATCH (c:Class)-[:CONTAINS]->(f:Function) "
            "WHERE c.semantic_roles IS NOT NULL AND "
            "ANY(r IN c.semantic_roles WHERE r IN "
            "['http_controller', 'rpc_provider']) "
            "RETURN f"
        )

        legacy_strong_query = (
            "MATCH (f:Function) "
            "WHERE f.signature CONTAINS '@RequestMapping' "
            "OR f.signature CONTAINS '@GetMapping' "
            "OR f.signature CONTAINS '@PostMapping' "
            "OR f.signature CONTAINS '@PutMapping' "
            "OR f.signature CONTAINS '@DeleteMapping' "
            "OR f.signature CONTAINS '@MoaProvider' "
            "OR f.signature CONTAINS '@KafkaListener' "
            "OR f.signature CONTAINS '@KafkaHandler' "
            "OR f.signature CONTAINS '@app.route' "
            "OR f.signature CONTAINS '@Scheduled' "
            "RETURN f"
        )

        weak_query = (
            "MATCH (f:Function)-[:CALLS]->() "
            "WHERE NOT ()-[:CALLS]->(f) "
            "RETURN DISTINCT f"
        )

        strong_rows = []
        try:
            strong_func_result = await loop.run_in_executor(
                None, lambda: self._store._graph.query(strong_func_query)
            )
            strong_class_result = await loop.run_in_executor(
                None, lambda: self._store._graph.query(strong_class_query)
            )
            strong_rows = (strong_func_result.result_set or []) + (strong_class_result.result_set or [])
        except Exception:
            logger.warning(
                "Semantic entry-point queries failed; falling back to signature-based matching",
                exc_info=True,
            )

        if not strong_rows:
            legacy_result = await loop.run_in_executor(
                None, lambda: self._store._graph.query(legacy_strong_query)
            )
            strong_rows = legacy_result.result_set or []

        weak_result = await loop.run_in_executor(
            None, lambda: self._store._graph.query(weak_query)
        )

        entries = []
        seen: set[str] = set()
        for row in strong_rows:
            node = row[0]
            uid = node.properties.get("uid", node.properties.get("name", ""))
            if uid not in seen:
                seen.add(uid)
                entries.append({**node.properties, "_entry_type": "strong"})

        for row in weak_result.result_set or []:
            node = row[0]
            uid = node.properties.get("uid", node.properties.get("name", ""))
            if uid not in seen:
                seen.add(uid)
                entries.append({**node.properties, "_entry_type": "weak"})

        return entries
