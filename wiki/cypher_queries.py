"""Shared Cypher query templates for FalkorDB / Neo4j-style graph access."""

METHODS_CY = """
MATCH (m:Module)-[:CONTAINS*1..3]->(f:Function)
WHERE m.name IN $names AND f.name IS NOT NULL
RETURN m.name AS module_name, f.name AS func_name,
       coalesce(f.signature, '') AS signature,
       coalesce(f.file, '') AS file_path,
       coalesce(f.start_line, 0) AS start_line,
       coalesce(f.repository, '') AS repository,
       coalesce(f.docstring, '') AS docstring
""".strip()


def call_chain_cypher(depth: int) -> str:
    d = max(1, int(depth))
    return f"""
MATCH (m1:Module)-[:CONTAINS]->(f1:Function)-[:CALLS*1..{d}]->(f2:Function)<-[:CONTAINS]-(m2:Module)
WHERE m1.name IN $names AND m1 <> m2
RETURN DISTINCT m1.name AS caller, m2.name AS callee,
       collect(DISTINCT f1.name)[..5] AS caller_functions,
       collect(DISTINCT f2.name)[..5] AS callee_functions
ORDER BY caller, callee
""".strip()


METHOD_CALL_CHAIN_CY = """
MATCH (m:Module)-[:CONTAINS*1..3]->(cf:Function)-[:CALLS]->(ct:Function)
WHERE m.name IN $names
  AND cf.name IS NOT NULL AND ct.name IS NOT NULL
RETURN cf.name AS caller_method,
       ct.name AS callee_method,
       coalesce(cf.file, '') AS caller_file,
       coalesce(ct.file, '') AS callee_file,
       m.name AS module_name
LIMIT 80
""".strip()


ENUMS_CY = """
MATCH (m:Module)-[:CONTAINS]->(c)
WHERE m.name IN $names AND (c:Enum OR c.is_constant = true)
RETURN c.name AS name, c.file AS file, labels(c) AS labels
""".strip()

SNIPPETS_CY = """
MATCH (m:Module)-[:CONTAINS*1..2]->(f:Function)
WHERE m.name IN $names AND f.code_snippet IS NOT NULL AND f.code_snippet <> ''
RETURN f.name AS func_name, left(f.code_snippet, 600) AS snippet,
       coalesce(f.file, '') AS file_path, coalesce(f.start_line, 0) AS start_line
LIMIT 10
""".strip()

CHUNK_SNIPPETS_CY = """
MATCH (m:Module)-[:CONTAINS*1..3]->(e)<-[:PART_OF]-(c:Chunk)
WHERE m.name IN $names AND c.text IS NOT NULL AND c.text <> ''
RETURN e.name AS entity_name, left(c.text, 800) AS snippet,
       coalesce(c.file, coalesce(e.file, '')) AS file_path,
       coalesce(c.start_line, coalesce(e.start_line, 0)) AS start_line,
       coalesce(c.end_line, coalesce(e.end_line, 0)) AS end_line
ORDER BY c.chunk_index
LIMIT 15
""".strip()

IMPLEMENTS_CY = """
MATCH (m:Module)-[:CONTAINS*1..2]->(impl:Class)-[:IMPLEMENTS]->(intf:Class)
WHERE m.name IN $names
RETURN impl.name AS impl_name, intf.name AS interface_name,
       coalesce(impl.repository, '') AS impl_repo,
       coalesce(intf.repository, '') AS intf_repo,
       m.name AS module_name
""".strip()

CALLERS_CY = """
MATCH (caller:Module)-[:CALLS]->(target:Module)
WHERE target.name IN $names AND NOT caller.name IN $names
RETURN caller.name AS caller_name, target.name AS target_name,
       coalesce(caller.repository, '') AS caller_repo
LIMIT 30
""".strip()

SNIPPET_BY_FUNC_CY = """
MATCH (f:Function)
WHERE f.name IN $names AND f.code_snippet IS NOT NULL AND f.code_snippet <> ''
RETURN f.name AS func_name, left(f.code_snippet, 600) AS snippet,
       coalesce(f.file, '') AS file_path, coalesce(f.start_line, 0) AS start_line
LIMIT 5
""".strip()

IMPLEMENTS_BY_INTERFACE_CY = """
MATCH (impl:Class)-[:IMPLEMENTS]->(intf:Class)
WHERE intf.name IN $names
RETURN impl.name AS impl_name, intf.name AS interface_name,
       coalesce(impl.repository, '') AS impl_repo,
       coalesce(intf.repository, '') AS intf_repo
LIMIT 10
""".strip()

FUNCTION_CALLS_CY = """
MATCH (m:Module)-[:CONTAINS*1..3]->(cf:Function)-[:CALLS]->(ct:Function)
WHERE m.name IN $names
OPTIONAL MATCH (mt:Module)-[:CONTAINS*1..3]->(ct)
RETURN cf.name AS caller_method, ct.name AS callee_method,
       m.name AS caller_module, coalesce(mt.name, '') AS callee_module,
       coalesce(cf.file, '') AS caller_file,
       coalesce(ct.file, '') AS callee_file,
       coalesce(cf.signature, '') AS caller_sig,
       coalesce(ct.signature, '') AS callee_sig
LIMIT 300
""".strip()

ENTITY_LOCATION_CY = """
MATCH (f)
WHERE (f:Function OR f:Class) AND f.name = $name
RETURN f.name AS name, coalesce(f.file, '') AS file,
       coalesce(f.start_line, 0) AS start_line,
       coalesce(f.end_line, 0) AS end_line,
       coalesce(f.code_snippet, '') AS snippet,
       labels(f)[0] AS type,
       coalesce(f.uid, '') AS uid,
       coalesce(f.repository, '') AS repository
LIMIT 3
""".strip()

ENTITY_LOCATION_BY_REPO_CY = """
MATCH (f)
WHERE (f:Function OR f:Class) AND f.name = $name AND f.repository = $repo
RETURN f.name AS name, coalesce(f.file, '') AS file,
       coalesce(f.start_line, 0) AS start_line,
       coalesce(f.end_line, 0) AS end_line,
       coalesce(f.code_snippet, '') AS snippet,
       labels(f)[0] AS type,
       coalesce(f.uid, '') AS uid,
       coalesce(f.repository, '') AS repository
LIMIT 3
""".strip()

_SEARCH_ENTITY_TEMPLATE = """
MATCH (n:{label})
WHERE toLower(n.name) CONTAINS toLower($keyword)
   OR toLower(coalesce(n.docstring, '')) CONTAINS toLower($keyword)
RETURN n.name AS name, '{label}' AS type,
       coalesce(n.file, '') AS file,
       coalesce(n.signature, '') AS signature,
       left(coalesce(n.docstring, ''), 200) AS docstring,
       coalesce(n.uid, '') AS uid
LIMIT $limit
""".strip()

SEARCH_ENTITY_LABELS = ("Function", "Class", "Module")


def search_entity_cypher(label: str) -> str:
    if label not in SEARCH_ENTITY_LABELS:
        raise ValueError(f"unsupported label: {label}")
    return _SEARCH_ENTITY_TEMPLATE.replace("{label}", label)

WIKI_PAGE_BY_QUERY_CY = """
MATCH (w:WikiPage)
WHERE w.path CONTAINS $query OR toLower(w.title) CONTAINS toLower($query)
RETURN w.title AS title, w.path AS path, left(w.content, $content_max_chars) AS content
LIMIT 3
""".strip()

MODULE_KEY_METHODS_CY = (
    "MATCH (m:Module)-[:CONTAINS*1..2]->(f:Function) "
    "WHERE m.repository IN $repos AND m.name IN $names "
    "RETURN m.name AS module_name, m.repository AS repo, "
    "collect(DISTINCT f.name)[0..5] AS key_methods"
)

MODULE_CALLEES_CY = (
    "MATCH (m1:Module)-[:CONTAINS*1..3]->(f1:Function)"
    "-[:CALLS]->(f2:Function)<-[:CONTAINS*1..3]-(m2:Module) "
    "WHERE m1.repository IN $repos AND m1 <> m2 "
    "RETURN m1.name AS source, m1.repository AS repo, "
    "collect(DISTINCT m2.name)[0..5] AS callees, "
    "count(DISTINCT m2) AS fan_out"
)

MODULE_CALLERS_CY = (
    "MATCH (m1:Module)-[:CONTAINS*1..3]->(f1:Function)"
    "-[:CALLS]->(f2:Function)<-[:CONTAINS*1..3]-(m2:Module) "
    "WHERE m2.repository IN $repos AND m1 <> m2 "
    "RETURN m2.name AS target, m2.repository AS repo, "
    "collect(DISTINCT m1.name)[0..5] AS callers, "
    "count(DISTINCT m1) AS fan_in"
)
