from __future__ import annotations

import asyncio
from typing import Any

from core.log import get_logger
from store.falkordb_common import _graph_executor

from .schema import NodeLabel

log = get_logger("store.falkordb_store")


class FalkorDBSearchMixin:
    async def vector_search(
        self,
        label: NodeLabel,
        embedding: list[float],
        k: int = 10,
        attribute: str = "embedding",
        *,
        repository: str | None = None,
        language: str | None = None,
    ) -> list[tuple[Any, float]]:
        loop = asyncio.get_running_loop()
        vec_str = ", ".join(str(v) for v in embedding)

        where_parts: list[str] = []
        params: dict[str, Any] = {}
        if repository:
            where_parts.append("node.repository = $repo")
            params["repo"] = repository
        if language:
            where_parts.append("node.language = $lang")
            params["lang"] = language

        fetch_k = k * 3 if where_parts else k
        where_clause = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""

        query = (
            f"CALL db.idx.vector.queryNodes('{label}', '{attribute}', {fetch_k}, "
            f"vecf32([{vec_str}])) YIELD node, score"
            f"{where_clause} "
            f"RETURN node, score ORDER BY score DESC LIMIT {k}"
        )
        result = await loop.run_in_executor(
            _graph_executor,
            lambda: self._graph.query(query, params=params),  # type: ignore[union-attr]
        )
        return [(row[0], row[1]) for row in result.result_set]

    async def keyword_search(
        self,
        keyword: str,
        k: int = 10,
        *,
        exact_only: bool = False,
        repository: str | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find nodes by name, FQN, or fuzzy CONTAINS match.

        Supports:
        - Simple name: ``checkGeetest``
        - FQN with ``#``: ``com.immomo...EsClient#insert``
        - FQN class only: ``com.immomo...EsClient``

        Returns results sorted by relevance (exact > fqn > fuzzy).
        """
        loop = asyncio.get_running_loop()
        results: list[dict[str, Any]] = []
        seen_uids: set[str] = set()

        extra_filters: list[str] = []
        filter_params: dict[str, Any] = {}
        if repository:
            extra_filters.append("n.repository = $repo")
            filter_params["repo"] = repository
        if language:
            extra_filters.append("n.language = $lang")
            filter_params["lang"] = language
        _kw_filter = (" AND " + " AND ".join(extra_filters)) if extra_filters else ""

        return_clause = (
            "RETURN n.uid AS uid, n.name AS name, n.file AS file, "
            "n.start_line AS line, labels(n)[0] AS type, "
            "coalesce(n.signature, '') AS signature, "
            "coalesce(n.docstring, '') AS docstring, "
            "coalesce(n.fqn, '') AS fqn"
        )

        if "#" in keyword or (keyword.count(".") >= 2 and " " not in keyword):
            fqn_q = (
                "MATCH (n) "
                f"WHERE (n:Function OR n:Class OR n:Module) AND n.fqn = $fqn{_kw_filter} "
                f"{return_clause} LIMIT $k"
            )
            try:
                fqn_params = {"fqn": keyword, "k": k, **filter_params}
                rows = await loop.run_in_executor(
                    _graph_executor,
                    lambda: self._graph.query(fqn_q, params=fqn_params),  # type: ignore[union-attr]
                )
                for row in rows.result_set or []:
                    uid = row[0]
                    if uid and uid not in seen_uids:
                        seen_uids.add(uid)
                        results.append({
                            "uid": uid, "name": row[1], "file": row[2],
                            "line": row[3], "type": row[4], "signature": row[5],
                            "docstring": row[6], "fqn": row[7], "score": 1.0,
                        })
            except Exception as exc:
                log.warning("keyword_fqn_search_error", error=str(exc))

            if results:
                return results[:k]

            if "#" in keyword:
                parts = keyword.rsplit("#", 1)
                method_name = parts[1].split("(")[0].strip() if len(parts) > 1 else ""
                class_fqn = parts[0]
                class_simple = class_fqn.rsplit(".", 1)[-1] if "." in class_fqn else class_fqn
                if method_name:
                    combo_class_filter = _kw_filter.replace("n.", "c.")
                    combo_func_filter = _kw_filter.replace("n.", "f.")
                    combo_q = (
                        "MATCH (c:Class)-[:CONTAINS]->(f:Function {name: $method}) "
                        f"WHERE c.name = $class_name{combo_class_filter}{combo_func_filter} "
                        f"WITH f AS n {return_clause} LIMIT $k"
                    )
                    try:
                        combo_params = {
                            "method": method_name,
                            "class_name": class_simple,
                            "k": k,
                            **filter_params,
                        }
                        rows = await loop.run_in_executor(
                            _graph_executor,
                            lambda: self._graph.query(  # type: ignore[union-attr]
                                combo_q, params=combo_params,
                            ),
                        )
                        for row in rows.result_set or []:
                            uid = row[0]
                            if uid and uid not in seen_uids:
                                seen_uids.add(uid)
                                results.append({
                                    "uid": uid, "name": row[1], "file": row[2],
                                    "line": row[3], "type": row[4], "signature": row[5],
                                    "docstring": row[6], "fqn": row[7], "score": 0.95,
                                })
                    except Exception as exc:
                        log.warning("keyword_combo_search_error", error=str(exc))

            if results:
                return results[:k]

        exact_q = (
            "MATCH (n) "
            f"WHERE (n:Function OR n:Class OR n:Module) AND n.name = $name{_kw_filter} "
            f"{return_clause} LIMIT $k"
        )
        try:
            exact_params = {"name": keyword, "k": k, **filter_params}
            rows = await loop.run_in_executor(
                _graph_executor,
                lambda: self._graph.query(exact_q, params=exact_params),  # type: ignore[union-attr]
            )
            for row in rows.result_set or []:
                uid = row[0]
                if uid and uid not in seen_uids:
                    seen_uids.add(uid)
                    results.append({
                        "uid": uid, "name": row[1], "file": row[2],
                        "line": row[3], "type": row[4], "signature": row[5],
                        "docstring": row[6], "fqn": row[7], "score": 1.0,
                    })
        except Exception as exc:
            log.warning("keyword_exact_search_error", error=str(exc))

        if exact_only or len(results) >= k:
            return results[:k]

        fuzzy_q = (
            "MATCH (n) "
            "WHERE (n:Function OR n:Class OR n:Module) "
            "AND toLower(n.name) CONTAINS toLower($keyword) "
            f"AND n.name <> $keyword{_kw_filter} "
            f"{return_clause} "
            "ORDER BY size(n.name) "
            "LIMIT $k"
        )
        try:
            fuzzy_params = {"keyword": keyword, "k": k, **filter_params}
            rows = await loop.run_in_executor(
                _graph_executor,
                lambda: self._graph.query(  # type: ignore[union-attr]
                    fuzzy_q, params=fuzzy_params,
                ),
            )
            for row in rows.result_set or []:
                uid = row[0]
                if uid and uid not in seen_uids:
                    seen_uids.add(uid)
                    results.append({
                        "uid": uid, "name": row[1], "file": row[2],
                        "line": row[3], "type": row[4], "signature": row[5],
                        "docstring": row[6], "fqn": row[7], "score": 0.9,
                    })
        except Exception as exc:
            log.warning("keyword_fuzzy_search_error", error=str(exc))

        return results[:k]
