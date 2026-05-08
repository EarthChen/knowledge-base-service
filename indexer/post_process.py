"""Post-processing to supplement graph relationships after indexing."""
from __future__ import annotations

from core.log import get_logger

log = get_logger(__name__)


def match_functions_to_modules(
    modules: list[dict],
    functions: list[dict],
) -> list[tuple[str, str]]:
    """Match functions to modules by FQN prefix first, then file_path.

    Returns list of (module_name, function_name) pairs.
    """
    fqn_to_module: dict[str, str] = {}
    path_to_modules: dict[str, list[str]] = {}

    for m in modules:
        fqn = m.get("fqn", "")
        if fqn:
            fqn_to_module[fqn] = m["name"]
        fp = m.get("file_path", "")
        if fp:
            path_to_modules.setdefault(fp, []).append(m["name"])

    matches: list[tuple[str, str]] = []
    for f in functions:
        fn_fqn = f.get("fqn", "")
        fn_name = f["name"]
        matched = False

        if fn_fqn:
            for mod_fqn, mod_name in fqn_to_module.items():
                if fn_fqn.startswith(mod_fqn + "."):
                    matches.append((mod_name, fn_name))
                    matched = True
                    break

        if not matched:
            fp = f.get("file_path", "")
            if fp and fp in path_to_modules:
                matches.append((path_to_modules[fp][0], fn_name))
                matched = True

        if not matched:
            log.debug("unmatched_function", function=fn_name, fqn=fn_fqn)

    return matches


async def supplement_contains_relationships(graph_store, graph_name: str) -> int:
    """Query all Functions and Modules, create missing CONTAINS relationships."""
    functions_query = "MATCH (f:Function) RETURN f.name AS name, coalesce(f.fqn, '') AS fqn, coalesce(f.file, f.file_path, '') AS file_path"
    modules_query = "MATCH (m:Module) RETURN m.name AS name, coalesce(m.fqn, '') AS fqn, coalesce(m.file, m.file_path, '') AS file_path"

    fn_result = await graph_store.execute_query(functions_query, {}, graph_name=graph_name)
    mod_result = await graph_store.execute_query(modules_query, {}, graph_name=graph_name)

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
        for mod_name, fn_name in batch:
            cypher = """
            MATCH (m:Module {name: $mod_name}), (f:Function {name: $fn_name})
            WHERE NOT (m)-[:CONTAINS]->(f)
            CREATE (m)-[:CONTAINS]->(f)
            """
            await graph_store.execute_query(
                cypher, {"mod_name": mod_name, "fn_name": fn_name}, graph_name=graph_name
            )
            attempted += 1

    log.info("supplement_contains_done", attempted=attempted, total_functions=len(functions))
    return attempted
