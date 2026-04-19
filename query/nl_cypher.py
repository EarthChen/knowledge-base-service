"""Natural language to Cypher query translator using LLM.

Given a natural language question about the code knowledge graph, this module:
1. Constructs a prompt with the graph schema (node types, edge types, properties)
2. Asks the LLM to generate a Cypher query
3. Validates the query is read-only (no CREATE/DELETE/SET/MERGE)
4. Executes the query against FalkorDB
5. Returns results (with optional retry on Cypher syntax errors)
"""
from __future__ import annotations

import re
from typing import Any

from llm.provider import LLMProvider
from log import get_logger
from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)

_MUTATING_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH\s+DELETE|SET|REMOVE|DROP|CALL\s+\{)\b",
    re.IGNORECASE,
)

_ALLOWED_FENCE_LANGS = frozenset({
    "cypher", "cql", "sql", "graphql", "plaintext", "",
})

GRAPH_SCHEMA_PROMPT = """You are a Cypher query generator for a code knowledge graph stored in FalkorDB (RedisGraph compatible).

## Node Types and Properties
- Function(name, file, start_line, end_line, code_snippet, docstring, language, signature, annotations, semantic_roles, repository, fqn)
- Class(name, file, start_line, end_line, docstring, language, base_classes, annotations, semantic_roles, repository, fqn, architecture_layer, table_name)
- Module(name, path, language, imports, repository)
- Document(title, path, content_hash, repository)
- BusinessFlow(name, description, category, trigger, steps, repository)
- BusinessConcept(name, description, category, repository)
- WikiPage(title, path, scope, content, repository)
- Chunk(text, parent_uid, parent_label, parent_name, chunk_index, file, start_line, end_line, repository)

## Edge Types
- CALLS(caller → callee): Function calls another Function
- INHERITS(child → parent): Class extends another Class
- IMPORTS(importer → imported): Module imports another Module
- CONTAINS(parent → child): Module contains Function/Class, Class contains method
- REFERENCES(Document → code entity)
- CROSS_REPO_CALLS(consumer → provider): Cross-repository RPC calls
- DEPENDS_ON(bean → injected bean): Spring DI dependency
- ACCESSES_TABLE(DAO class → entity class): Database access pattern
- EVENT_PRODUCES(function → Kafka topic module)
- EVENT_CONSUMES(function → Kafka topic module)
- PROVIDES_RPC(provider class → module)
- CONSUMES_RPC(consumer function → module)
- PART_OF(child → parent): Chunk belongs to entity, or entity belongs to flow

## Rules
1. Generate ONLY a single read-only Cypher query, no explanation
2. ONLY use MATCH, OPTIONAL MATCH, WHERE, WITH, RETURN, ORDER BY, SKIP, LIMIT, UNION
3. NEVER use CREATE, MERGE, DELETE, SET, REMOVE, DROP or any write operations
4. Always add LIMIT (max 50) to prevent huge result sets
5. Return useful properties (name, file, type, repository) not just nodes
6. For text matching use CONTAINS (case-insensitive: toLower())
7. The graph is FalkorDB (RedisGraph) — no apoc functions available
8. Property access: use n.property syntax
"""


class CypherValidationError(ValueError):
    """Raised when generated Cypher contains forbidden operations."""


class NLCypherService:
    """Translates natural language questions into Cypher and executes them."""

    def __init__(
        self,
        store: FalkorDBStore,
        llm: LLMProvider,
        *,
        max_retries: int = 2,
    ) -> None:
        self._store = store
        self._llm = llm
        self._max_retries = max(1, max_retries)

    async def query(self, question: str, *, repository: str | None = None) -> dict[str, Any]:
        """Execute a natural language query against the knowledge graph."""
        try:
            cypher = await self._generate_cypher(question, repository=repository)
            self._validate_read_only(cypher)
        except CypherValidationError as exc:
            return {
                "question": question,
                "cypher": "",
                "error": str(exc),
                "results": [],
                "total": 0,
            }
        except Exception as exc:
            log.error("nl_cypher_generation_failed", error=str(exc))
            return {
                "question": question,
                "cypher": "",
                "error": f"Failed to generate query: {str(exc)[:200]}",
                "results": [],
                "total": 0,
            }

        for attempt in range(1, self._max_retries + 1):
            try:
                result = await self._store.execute_query(cypher, {})
                return {
                    "question": question,
                    "cypher": cypher,
                    "results": result.data,
                    "total": len(result.data),
                    "attempt": attempt,
                }
            except Exception as exc:
                error_msg = str(exc)
                log.warning(
                    "nl_cypher_execution_failed",
                    error=error_msg[:300],
                    attempt=attempt,
                )
                if attempt < self._max_retries:
                    try:
                        cypher = await self._fix_cypher(
                            question, cypher, error_msg, repository=repository,
                        )
                        self._validate_read_only(cypher)
                    except (CypherValidationError, Exception) as fix_exc:
                        return {
                            "question": question,
                            "cypher": cypher,
                            "error": f"Query repair failed: {str(fix_exc)[:200]}",
                            "results": [],
                            "total": 0,
                        }
                else:
                    return {
                        "question": question,
                        "cypher": cypher,
                        "error": f"Query failed after {self._max_retries} attempts: {error_msg[:200]}",
                        "results": [],
                        "total": 0,
                    }
        return {"question": question, "cypher": cypher, "results": [], "total": 0}

    @staticmethod
    def _validate_read_only(cypher: str) -> None:
        """Reject Cypher containing any mutating keyword."""
        if _MUTATING_KEYWORDS.search(cypher):
            raise CypherValidationError(
                "Generated query contains write operations which are not allowed"
            )

    async def _generate_cypher(self, question: str, *, repository: str | None = None) -> str:
        repo_hint = ""
        if repository:
            repo_hint = (
                f"\nIMPORTANT: Always filter results by the repository property. "
                f"Use WHERE clauses like `n.repository = $repo` with parameter $repo."
            )

        messages = [
            {"role": "system", "content": GRAPH_SCHEMA_PROMPT + repo_hint},
            {"role": "user", "content": f"Generate a Cypher query for: {question[:2000]}"},
        ]
        raw = await self._llm.complete(messages, temperature=0.0)
        return self._extract_cypher(raw)

    async def _fix_cypher(
        self, question: str, failed_cypher: str, error: str, *, repository: str | None = None
    ) -> str:
        repo_hint = ""
        if repository:
            repo_hint = "\nFilter by repository using $repo parameter."

        messages = [
            {"role": "system", "content": GRAPH_SCHEMA_PROMPT + repo_hint},
            {"role": "user", "content": (
                f"The following Cypher query failed:\n```\n{failed_cypher[:1000]}\n```\n"
                f"Error: {error[:500]}\n\n"
                f"Original question: {question[:500]}\n"
                f"Fix the query and return only the corrected Cypher."
            )},
        ]
        raw = await self._llm.complete(messages, temperature=0.0)
        return self._extract_cypher(raw)

    @staticmethod
    def _extract_cypher(raw: str) -> str:
        """Extract Cypher from LLM response, stripping markdown fences."""
        text = raw.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts[1:]:
                lines = part.strip().split("\n")
                if lines:
                    first_lower = lines[0].strip().lower()
                    if first_lower in _ALLOWED_FENCE_LANGS or not first_lower.isalpha():
                        lines = lines[1:]
                candidate = "\n".join(lines).strip()
                if candidate:
                    return candidate
        match = re.search(r"(MATCH\b.*)", text, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return text
