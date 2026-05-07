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
MATCH (a:Module)-[:CALLS*1..{d}]->(b:Module)
WHERE a.name IN $names
RETURN a.name AS caller, b.name AS callee
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
