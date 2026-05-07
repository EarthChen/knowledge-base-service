"""Method-level call chain builder using BFS over FalkorDB graph."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from core.log import get_logger
from wiki.cypher_queries import FUNCTION_CALLS_CY

log = get_logger(__name__)


@dataclass
class CallChainNode:
    func_name: str
    module_name: str
    file_path: str
    signature: str


@dataclass
class MethodCallChain:
    entry_method: str
    entry_module: str
    chain: list[CallChainNode]
    depth: int


class CallChainBuilder:
    MAX_DEPTH = 5
    MAX_CHAINS = 20

    def __init__(self, graph_store: Any) -> None:
        self._graph = graph_store

    async def build_chains(
        self,
        module_names: list[str],
        max_depth: int | None = None,
        max_chains: int | None = None,
    ) -> list[MethodCallChain]:
        if not module_names:
            return []

        effective_depth = min(max(1, max_depth or self.MAX_DEPTH), self.MAX_DEPTH)
        effective_chains = min(max(1, max_chains or self.MAX_CHAINS), 100)

        try:
            result = await self._graph.execute_query(
                FUNCTION_CALLS_CY,
                {"names": module_names},
            )
        except Exception:
            log.warning("call_chain_query_failed", exc_info=True)
            return []

        rows = getattr(result, "data", None) or []
        if not rows:
            return []

        # Build adjacency list with composite keys: "module.func"
        adjacency: dict[str, list[tuple[str, CallChainNode]]] = {}
        all_callees: set[str] = set()
        node_cache: dict[str, CallChainNode] = {}

        for row in rows:
            if not isinstance(row, dict):
                continue
            caller_method = str(row.get("caller_method", "") or "")
            callee_method = str(row.get("callee_method", "") or "")
            caller_module = str(row.get("caller_module", "") or "")
            callee_module = str(row.get("callee_module", "") or "")

            if not caller_method or not callee_method:
                continue

            caller_key = f"{caller_module}.{caller_method}"
            callee_key = f"{callee_module}.{callee_method}"

            caller_node = CallChainNode(
                func_name=caller_method,
                module_name=caller_module,
                file_path=str(row.get("caller_file", "") or ""),
                signature=str(row.get("caller_sig", "") or ""),
            )
            callee_node = CallChainNode(
                func_name=callee_method,
                module_name=callee_module,
                file_path=str(row.get("callee_file", "") or ""),
                signature=str(row.get("callee_sig", "") or ""),
            )

            node_cache[caller_key] = caller_node
            node_cache[callee_key] = callee_node

            if caller_key not in adjacency:
                adjacency[caller_key] = []
            adjacency[caller_key].append((callee_key, callee_node))
            all_callees.add(callee_key)

        # Entry methods: callers that are NOT called by anyone
        entry_keys = [k for k in adjacency if k not in all_callees]
        if not entry_keys:
            # Fallback: use all callers
            entry_keys = list(adjacency.keys())

        # BFS from each entry method
        chains: list[MethodCallChain] = []
        for entry_key in entry_keys:
            if len(chains) >= effective_chains:
                break
            entry_node = node_cache.get(entry_key)
            if not entry_node:
                continue
            bfs_chains = self._bfs(
                entry_key, entry_node, adjacency, effective_depth,
            )
            for c in bfs_chains:
                if len(chains) >= effective_chains:
                    break
                chains.append(c)

        chains.sort(key=lambda c: c.depth, reverse=True)
        return chains[:effective_chains]

    def _bfs(
        self,
        start_key: str,
        start_node: CallChainNode,
        adjacency: dict[str, list[tuple[str, CallChainNode]]],
        max_depth: int,
    ) -> list[MethodCallChain]:
        # BFS: each queue item is (current_key, path_so_far)
        queue: deque[tuple[str, list[CallChainNode]]] = deque()
        queue.append((start_key, [start_node]))

        results: list[MethodCallChain] = []

        while queue:
            current_key, path = queue.popleft()
            neighbors = adjacency.get(current_key, [])

            extended = False
            if len(path) - 1 < max_depth:
                visited_keys = {f"{n.module_name}.{n.func_name}" for n in path}
                for next_key, next_node in neighbors:
                    if next_key in visited_keys:
                        continue
                    extended = True
                    new_path = path + [next_node]
                    queue.append((next_key, new_path))

            if not extended and len(path) > 1:
                results.append(MethodCallChain(
                    entry_method=start_node.func_name,
                    entry_module=start_node.module_name,
                    chain=path,
                    depth=len(path) - 1,
                ))

        return results

    def format_for_prompt(self, chains: list[MethodCallChain]) -> str:
        if not chains:
            return "（无方法级调用链数据）"
        lines: list[str] = []
        for i, chain in enumerate(chains, 1):
            arrow_parts = []
            for node in chain.chain:
                label = (
                    f"{node.module_name}.{node.func_name}"
                    if node.module_name
                    else node.func_name
                )
                arrow_parts.append(label)
            chain_str = " → ".join(arrow_parts)
            lines.append(
                f"{i}. [{chain.entry_module}] {chain_str} (depth={chain.depth})",
            )
        return "\n".join(lines)
