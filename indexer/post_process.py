"""Post-processing to supplement graph relationships after indexing."""
from __future__ import annotations

from core.log import get_logger

log = get_logger(__name__)


def match_functions_to_modules(
    modules: list[dict],
    functions: list[dict],
) -> list[tuple[str, str]]:
    """Match functions to modules by file_path first, then FQN prefix.

    Returns list of (module_uid, function_uid) pairs.
    """
    path_to_module_uid: dict[str, str] = {}
    fqn_to_module_uid: dict[str, str] = {}

    for m in modules:
        uid = m.get("uid", "")
        if not uid:
            continue
        fp = m.get("file_path", "")
        if fp:
            path_to_module_uid[fp] = uid
        fqn = m.get("fqn", "")
        if fqn:
            fqn_to_module_uid[fqn] = uid

    matches: list[tuple[str, str]] = []
    for f in functions:
        fn_uid = f.get("uid", "")
        if not fn_uid:
            continue
        matched = False

        fp = f.get("file_path", "")
        if fp and fp in path_to_module_uid:
            matches.append((path_to_module_uid[fp], fn_uid))
            matched = True

        if not matched:
            fn_fqn = f.get("fqn", "")
            if fn_fqn:
                for mod_fqn, mod_uid in fqn_to_module_uid.items():
                    if fn_fqn.startswith(mod_fqn + "."):
                        matches.append((mod_uid, fn_uid))
                        matched = True
                        break

        if not matched:
            fn_name = f.get("name", "")
            log.debug("unmatched_function", function=fn_name, fqn=f.get("fqn", ""))

    return matches


async def supplement_contains_relationships(graph_store, graph_name: str) -> int:
    """Query all Functions and Modules, create missing CONTAINS relationships."""
    functions_query = "MATCH (f:Function) RETURN f.name AS name, coalesce(f.fqn, '') AS fqn, coalesce(f.file, f.file_path, '') AS file_path, f.uid AS uid"
    modules_query = "MATCH (m:Module) RETURN m.name AS name, coalesce(m.fqn, '') AS fqn, coalesce(m.file, m.file_path, m.path, '') AS file_path, m.uid AS uid"

    fn_result = await graph_store.execute_query(functions_query, {})
    mod_result = await graph_store.execute_query(modules_query, {})

    functions = [dict(r) for r in fn_result]
    modules = [dict(r) for r in mod_result]

    pairs = match_functions_to_modules(modules, functions)

    seen: set[tuple[str, str]] = set()
    unique_pairs = []
    for pair in pairs:
        if pair not in seen:
            seen.add(pair)
            unique_pairs.append(pair)

    attempted = 0
    batch_size = 100
    for i in range(0, len(unique_pairs), batch_size):
        batch = unique_pairs[i : i + batch_size]
        for mod_uid, fn_uid in batch:
            cypher = """
            MATCH (m:Module {uid: $mod_uid}), (f:Function {uid: $fn_uid})
            WHERE NOT (m)-[:CONTAINS]->(f)
            CREATE (m)-[:CONTAINS]->(f)
            """
            await graph_store.execute_query(
                cypher, {"mod_uid": mod_uid, "fn_uid": fn_uid}
            )
            attempted += 1

    log.info("supplement_contains_done", attempted=attempted, total_functions=len(functions))
    return attempted
