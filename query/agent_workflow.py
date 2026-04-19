"""P2 Agent workflow service: PR Review context and Smart Context builder.

Provides composite query APIs optimized for AI agent consumption during
code review and feature development tasks.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from log import get_logger
from store.analysis_store import AnalysisStore

if TYPE_CHECKING:
    from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)

_MAX_CHANGED_FUNCTIONS = 200
_MAX_CONTEXT_ITEMS = 50


# ─── Data Models ────────────────────────────────────────────────────────

@dataclass
class ChangedEntity:
    file: str
    name: str
    entity_type: str  # "function" | "class"
    start_line: int = 0
    end_line: int = 0


@dataclass
class ReviewImpact:
    """Impact summary for a single changed entity."""
    entity_name: str
    entity_file: str
    direct_callers: list[dict[str, Any]] = field(default_factory=list)
    affected_endpoints: list[dict[str, Any]] = field(default_factory=list)
    cross_repo_impacts: list[dict[str, Any]] = field(default_factory=list)
    affected_layers: list[str] = field(default_factory=list)


@dataclass
class ReviewContext:
    """Structured review context for a PR diff."""
    changed_files: list[str]
    changed_entities: list[dict[str, Any]]
    impacts: list[dict[str, Any]]
    affected_endpoints_summary: list[dict[str, Any]]
    cross_repo_summary: list[dict[str, Any]]
    affected_layers: list[str]
    suggestions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_files": self.changed_files,
            "changed_entities": self.changed_entities,
            "impacts": self.impacts,
            "affected_endpoints_summary": self.affected_endpoints_summary,
            "cross_repo_summary": self.cross_repo_summary,
            "affected_layers": list(set(self.affected_layers)),
            "suggestions": self.suggestions,
            "summary": {
                "total_changed_files": len(self.changed_files),
                "total_changed_entities": len(self.changed_entities),
                "total_affected_endpoints": len(self.affected_endpoints_summary),
                "total_cross_repo_impacts": len(self.cross_repo_summary),
            },
        }


@dataclass
class SmartContext:
    """Optimal context package for a code entity."""
    target: dict[str, Any]
    callers: list[dict[str, Any]]
    callees: list[dict[str, Any]]
    parent_class: dict[str, Any] | None
    sibling_methods: list[dict[str, Any]]
    cross_repo_deps: list[dict[str, Any]]
    entity_tables: list[dict[str, Any]]
    di_dependencies: list[dict[str, Any]]
    architecture_layer: str
    related_interfaces: list[dict[str, Any]]
    rpc_interface_contracts: list[dict[str, Any]]
    event_context: dict[str, list[str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "callers": self.callers,
            "callees": self.callees,
            "parent_class": self.parent_class,
            "sibling_methods": self.sibling_methods,
            "cross_repo_deps": self.cross_repo_deps,
            "entity_tables": self.entity_tables,
            "di_dependencies": self.di_dependencies,
            "architecture_layer": self.architecture_layer,
            "related_interfaces": self.related_interfaces,
            "rpc_interface_contracts": self.rpc_interface_contracts,
            "event_context": self.event_context,
        }


# ─── Diff Parser ────────────────────────────────────────────────────────

def parse_diff_changed_files(diff_text: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    files: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                files.append(path)
        elif line.startswith("diff --git"):
            m = re.search(r"b/(.+)$", line)
            if m:
                path = m.group(1).strip()
                if path not in files:
                    files.append(path)
    return list(dict.fromkeys(files))


def parse_diff_changed_lines(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Extract changed line ranges per file from a unified diff.

    Returns {file_path: [(start_line, end_line), ...]}.
    """
    result: dict[str, list[tuple[int, int]]] = {}
    current_file: str | None = None

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            if current_file and current_file != "/dev/null":
                result.setdefault(current_file, [])
            else:
                current_file = None
        elif line.startswith("@@ ") and current_file:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) else 1
                end = start + count - 1
                result[current_file].append((start, end))
    return result


# ─── Service ────────────────────────────────────────────────────────────

class AgentWorkflowService:
    """Composite queries for AI agent workflows."""

    def __init__(
        self,
        store: FalkorDBStore,
        analysis_store: AnalysisStore | None = None,
    ) -> None:
        self._store = store
        self._analysis = analysis_store or AnalysisStore(store)

    _GIT_DIFF_TIMEOUT_SECONDS = 30
    _SAFE_REF_PATTERN = re.compile(r"^[\w./-]+$")

    async def _get_diff_from_branch(
        self, repo_path: str, branch: str, base_branch: str = "master"
    ) -> str:
        """Run ``git diff base_branch...branch`` in the specified repo path."""
        for ref_name in (branch, base_branch):
            if not self._SAFE_REF_PATTERN.match(ref_name):
                raise ValueError(f"Invalid git ref name: {ref_name}")

        root = Path(repo_path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"Repository path not found or not a directory: {repo_path}")
        if not (root / ".git").exists():
            raise ValueError(f"Not a git repository (no .git): {root}")

        spec = f"{base_branch}...{branch}"
        env = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": "/dev/null"}
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "diff",
                spec,
                cwd=str(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**__import__("os").environ, **env},
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "git executable not found; ensure Git is installed and on PATH",
            ) from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._GIT_DIFF_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(
                f"git diff timed out after {self._GIT_DIFF_TIMEOUT_SECONDS}s"
            )

        out = stdout.decode("utf-8", errors="replace")
        err_txt = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            detail = err_txt or out.strip() or f"exit code {proc.returncode}"
            raise RuntimeError(
                f"git diff {spec} failed: {detail}",
            )
        return out

    # ─── P2-2: PR Review Context ────────────────────────────────────

    async def build_review_context(
        self,
        diff_text: str | None = None,
        repository: str | None = None,
        max_depth: int = 3,
        *,
        repo_path: str | None = None,
        branch: str | None = None,
        base_branch: str | None = None,
    ) -> ReviewContext:
        """Build a comprehensive review context from a git diff or a local branch range."""
        if diff_text is not None and diff_text.strip():
            resolved = diff_text
        elif repo_path and branch and branch.strip():
            bb = (base_branch or "").strip() or "master"
            resolved = await self._get_diff_from_branch(
                repo_path, branch.strip(), bb
            )
        else:
            raise ValueError(
                "Provide either non-empty diff_text, or both repo_path and branch",
            )

        changed_files = parse_diff_changed_files(resolved)
        changed_lines = parse_diff_changed_lines(resolved)

        changed_entities = await self._find_changed_entities(changed_files, changed_lines, repository)

        impacts: list[dict[str, Any]] = []
        all_affected_endpoints: list[dict[str, Any]] = []
        all_cross_repo: list[dict[str, Any]] = []
        all_layers: list[str] = []
        suggestions: list[str] = []

        func_names = [
            e["name"] for e in changed_entities
            if e.get("entity_type") == "function"
        ][:_MAX_CHANGED_FUNCTIONS]

        if func_names:
            impact_data = await self._batch_impact_analysis(func_names, max_depth)
            for item in impact_data:
                impacts.append(item)
                all_affected_endpoints.extend(item.get("affected_endpoints", []))
                all_cross_repo.extend(item.get("cross_repo_impacts", []))
                all_layers.extend(item.get("affected_layers", []))

        endpoint_map: dict[str, dict[str, Any]] = {}
        for ep in all_affected_endpoints:
            key = ep.get("uid") or ep.get("name", "")
            if key and key not in endpoint_map:
                endpoint_map[key] = ep

        cross_repo_map: dict[str, dict[str, Any]] = {}
        for cr in all_cross_repo:
            key = f"{cr.get('source_repo', '')}→{cr.get('target_repo', '')}"
            if key not in cross_repo_map:
                cross_repo_map[key] = cr

        if endpoint_map:
            suggestions.append(
                f"This PR affects {len(endpoint_map)} API endpoint(s). "
                "Consider testing these endpoints."
            )
        if cross_repo_map:
            suggestions.append(
                f"This PR has cross-repository impact on {len(cross_repo_map)} service link(s). "
                "Consider coordinating with the dependent service teams."
            )
        rpc_providers_changed = any(
            "rpc_provider" in (e.get("semantic_roles") or [])
            for e in changed_entities
        )
        if rpc_providers_changed:
            suggestions.append(
                "RPC provider interface changed — this may break downstream consumers. "
                "Check CROSS_REPO_CALLS edges for affected consumers."
            )

        return ReviewContext(
            changed_files=changed_files,
            changed_entities=changed_entities,
            impacts=impacts,
            affected_endpoints_summary=list(endpoint_map.values()),
            cross_repo_summary=list(cross_repo_map.values()),
            affected_layers=all_layers,
            suggestions=suggestions,
        )

    async def _find_changed_entities(
        self,
        changed_files: list[str],
        changed_lines: dict[str, list[tuple[int, int]]],
        repository: str | None,
    ) -> list[dict[str, Any]]:
        """Find graph entities that overlap with changed file regions."""
        if not changed_files:
            return []

        entities: list[dict[str, Any]] = []
        seen_uids: set[str] = set()

        for file_path in changed_files[:50]:
            try:
                res = await self._analysis.agent_find_changed_entities(file_path, repository)
            except Exception as exc:
                log.warning("find_changed_entities_query_failed", file=file_path, error=str(exc))
                continue

            line_ranges = changed_lines.get(file_path, [])

            for row in res.data:
                uid = row.get("uid") or ""
                if uid in seen_uids:
                    continue

                if line_ranges:
                    start = row.get("start_line")
                    end = row.get("end_line")
                    if start is not None and end is not None:
                        try:
                            s = int(start)
                            e = int(end)
                            overlaps = any(
                                s <= lr_end and e >= lr_start
                                for lr_start, lr_end in line_ranges
                            )
                            if not overlaps:
                                continue
                        except (TypeError, ValueError):
                            pass

                seen_uids.add(uid)
                entities.append({
                    "uid": uid,
                    "name": row.get("name"),
                    "file": row.get("file"),
                    "start_line": row.get("start_line"),
                    "end_line": row.get("end_line"),
                    "entity_type": (row.get("entity_type") or "").lower(),
                    "semantic_roles": row.get("semantic_roles"),
                    "architecture_layer": row.get("architecture_layer"),
                    "signature": row.get("signature"),
                })

        return entities

    async def _batch_impact_analysis(
        self,
        func_names: list[str],
        max_depth: int,
    ) -> list[dict[str, Any]]:
        """Run impact analysis and collect cross-repo impacts."""
        results: list[dict[str, Any]] = []
        depth_cap = max(1, min(max_depth, 20))

        try:
            res = await self._analysis.agent_batch_impact_analysis(func_names, depth_cap)
        except Exception as exc:
            log.error("batch_impact_analysis_failed", error=str(exc))
            return results

        by_target: dict[str, list[dict[str, Any]]] = {}
        for row in res.data:
            target = row.get("target_name") or ""
            by_target.setdefault(target, []).append(row)

        _ENTRY_FUNC_ROLES = frozenset({"http_endpoint", "rpc_consumer", "message_listener", "scheduled_task"})
        _ENTRY_CLASS_ROLES = frozenset({"http_controller", "rpc_provider"})

        for target_name, rows in by_target.items():
            callers: list[dict[str, Any]] = []
            endpoints: list[dict[str, Any]] = []
            layers: set[str] = set()

            for row in rows:
                layer = row.get("caller_architecture_layer")
                if isinstance(layer, str) and layer.strip():
                    layers.add(layer)

                caller_info = {
                    "uid": row.get("caller_uid"),
                    "name": row.get("caller_name"),
                    "file": row.get("caller_file"),
                    "depth": row.get("depth"),
                    "parent_class": row.get("parent_class_name"),
                }
                callers.append(caller_info)

                func_roles = set(row.get("caller_semantic_roles") or [])
                cls_roles = set(row.get("parent_class_semantic_roles") or [])
                if func_roles & _ENTRY_FUNC_ROLES or cls_roles & _ENTRY_CLASS_ROLES:
                    endpoints.append(caller_info)

            results.append({
                "target_name": target_name,
                "direct_callers": [c for c in callers if (c.get("depth") or 0) == 1],
                "affected_endpoints": endpoints,
                "affected_layers": list(layers),
                "cross_repo_impacts": [],
            })

        try:
            cross_repo_res = await self._analysis.agent_cross_repo_impact_by_names(func_names)
            cross_repo_by_name: dict[str, list[dict[str, Any]]] = {}
            for row in cross_repo_res.data:
                name = row.get("consumer_name") or ""
                cross_repo_by_name.setdefault(name, []).append({
                    "source_repo": row.get("source_repo"),
                    "target_repo": row.get("target_repo"),
                    "provider": row.get("provider_name"),
                    "interface": row.get("interface"),
                })

            for item in results:
                target = item["target_name"]
                if target in cross_repo_by_name:
                    item["cross_repo_impacts"] = cross_repo_by_name[target]

        except Exception as exc:
            log.warning("cross_repo_impact_query_failed", error=str(exc))

        return results

    # ─── P2-3: Smart Context Builder ────────────────────────────────

    async def build_smart_context(
        self,
        entity_name: str,
        entity_type: str = "function",
        repository: str | None = None,
    ) -> SmartContext:
        """Build an optimal context package for a function or class."""

        target = await self._find_target_entity(entity_name, entity_type, repository)
        if not target:
            return SmartContext(
                target={"name": entity_name, "error": "Entity not found"},
                callers=[], callees=[], parent_class=None,
                sibling_methods=[], cross_repo_deps=[], entity_tables=[],
                di_dependencies=[], architecture_layer="unknown",
                related_interfaces=[],
                rpc_interface_contracts=[],
                event_context={"consumes": [], "produces": []},
            )

        target_uid = target.get("uid", "")
        target_label = target.get("entity_type", "Function")

        callers = await self._get_callers(target_uid, target_label)
        callees = await self._get_callees(target_uid, target_label)
        parent_class, siblings = await self._get_class_context(target_uid, target_label)
        cross_repo, rpc_iface_contracts = await self._get_cross_repo_context(
            target_uid, target_label, target, parent_class,
        )
        entity_tables = await self._get_entity_table_context(target_uid, target_label, parent_class)
        di_deps = await self._get_di_dependencies(target_uid, target_label, parent_class)
        interfaces = await self._get_interface_context(target_uid, target_label, parent_class)
        event_ctx = await self._get_event_context(target_uid, target_label, parent_class)

        return SmartContext(
            target=target,
            callers=callers,
            callees=callees,
            parent_class=parent_class,
            sibling_methods=siblings,
            cross_repo_deps=cross_repo,
            entity_tables=entity_tables,
            di_dependencies=di_deps,
            architecture_layer=target.get("architecture_layer", "unknown"),
            related_interfaces=interfaces,
            rpc_interface_contracts=rpc_iface_contracts,
            event_context=event_ctx,
        )

    async def _find_target_entity(
        self, name: str, entity_type: str, repository: str | None
    ) -> dict[str, Any] | None:
        label = "Function" if entity_type == "function" else "Class"

        try:
            res = await self._analysis.agent_find_target_entity(label, name, repository)
            if res.data:
                row = res.data[0]
                row["entity_type"] = label
                return row
        except Exception as exc:
            log.warning("find_target_entity_failed", name=name, error=str(exc))
        return None

    async def _get_callers(self, uid: str, label: str) -> list[dict[str, Any]]:
        try:
            res = await self._analysis.agent_get_callers(label, uid, _MAX_CONTEXT_ITEMS)
            return res.data
        except Exception as exc:
            log.warning("get_callers_failed", uid=uid, error=str(exc))
            return []

    async def _get_callees(self, uid: str, label: str) -> list[dict[str, Any]]:
        try:
            if label == "Function":
                res = await self._analysis.agent_get_callees_function(uid, _MAX_CONTEXT_ITEMS)
            else:
                res = await self._analysis.agent_get_callees_class(uid, _MAX_CONTEXT_ITEMS)
            return res.data
        except Exception as exc:
            log.warning("get_callees_failed", uid=uid, error=str(exc))
            return []

    async def _get_class_context(
        self, uid: str, label: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        if label == "Class":
            try:
                methods = await self._analysis.agent_class_methods_only(uid, _MAX_CONTEXT_ITEMS)
                return None, methods.data
            except Exception as exc:
                log.warning("get_class_methods_failed", uid=uid, error=str(exc))
                return None, []

        try:
            parent_res = await self._analysis.agent_parent_of_function(uid)
            if not parent_res.data:
                return None, []

            parent = parent_res.data[0]
            parent_uid = parent.get("uid") or ""

            siblings = await self._analysis.agent_sibling_methods(
                parent_uid, uid, _MAX_CONTEXT_ITEMS,
            )
            return parent, siblings.data

        except Exception as exc:
            log.warning("get_class_context_failed", uid=uid, error=str(exc))
            return None, []

    @staticmethod
    def _is_rpc_provider_entity(
        label: str,
        target: dict[str, Any],
        parent_class: dict[str, Any] | None,
    ) -> bool:
        if label == "Class":
            roles = target.get("semantic_roles") or []
        else:
            roles = (parent_class or {}).get("semantic_roles") or []
        return isinstance(roles, list) and "rpc_provider" in roles

    async def _get_cross_repo_context(
        self,
        uid: str,
        label: str,
        target: dict[str, Any],
        parent_class: dict[str, Any] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rpc_contracts: list[dict[str, Any]] = []
        try:
            if label == "Function":
                res = await self._analysis.agent_cross_repo_from_function(uid, _MAX_CONTEXT_ITEMS)
            else:
                res = await self._analysis.agent_cross_repo_to_class(uid, _MAX_CONTEXT_ITEMS)
            deps = res.data
        except Exception as exc:
            log.warning("get_cross_repo_context_failed", uid=uid, error=str(exc))
            deps = []

        if self._is_rpc_provider_entity(label, target, parent_class):
            class_uid = uid if label == "Class" else (parent_class or {}).get("uid")
            if class_uid:
                try:
                    cres = await self._analysis.agent_rpc_interface_contracts(
                        str(class_uid), _MAX_CONTEXT_ITEMS,
                    )
                    rpc_contracts = cres.data
                except Exception as exc:
                    log.warning(
                        "get_rpc_interface_contracts_failed",
                        uid=class_uid,
                        error=str(exc),
                    )

        return deps, rpc_contracts

    async def _get_event_context(
        self,
        uid: str,
        label: str,
        parent_class: dict[str, Any] | None,
    ) -> dict[str, list[str]]:
        func_uids: list[str] = []
        if label == "Function":
            func_uids = [uid]
        else:
            try:
                res = await self._analysis.agent_class_function_uids(uid)
                func_uids = [r["uid"] for r in res.data if r.get("uid")]
            except Exception as exc:
                log.warning("get_event_context_class_methods_failed", uid=uid, error=str(exc))
                return {"consumes": [], "produces": []}

        if not func_uids:
            return {"consumes": [], "produces": []}

        try:
            c_res = await self._analysis.agent_event_consumes(func_uids)
            p_res = await self._analysis.agent_event_produces(func_uids)
            consumes = sorted({r["topic"] for r in c_res.data if r.get("topic")})
            produces = sorted({r["topic"] for r in p_res.data if r.get("topic")})
            return {"consumes": consumes, "produces": produces}
        except Exception as exc:
            log.warning("get_event_context_failed", uid=uid, error=str(exc))
            return {"consumes": [], "produces": []}

    async def _get_entity_table_context(
        self, uid: str, label: str, parent_class: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        class_uid = uid if label == "Class" else (parent_class or {}).get("uid", "")
        if not class_uid:
            return []
        try:
            res = await self._analysis.agent_entity_tables(str(class_uid), _MAX_CONTEXT_ITEMS)
            return res.data
        except Exception as exc:
            log.warning("get_entity_table_context_failed", uid=class_uid, error=str(exc))
            return []

    async def _get_di_dependencies(
        self, uid: str, label: str, parent_class: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        class_uid = uid if label == "Class" else (parent_class or {}).get("uid", "")
        if not class_uid:
            return []
        try:
            res = await self._analysis.agent_di_dependencies(str(class_uid), _MAX_CONTEXT_ITEMS)
            return res.data
        except Exception as exc:
            log.warning("get_di_dependencies_failed", uid=class_uid, error=str(exc))
            return []

    async def _get_interface_context(
        self, uid: str, label: str, parent_class: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        class_uid = uid if label == "Class" else (parent_class or {}).get("uid", "")
        if not class_uid:
            return []
        try:
            res = await self._analysis.agent_related_interfaces(str(class_uid), _MAX_CONTEXT_ITEMS)
            return res.data
        except Exception as exc:
            log.warning("get_interface_context_failed", uid=class_uid, error=str(exc))
            return []

    _CONTROL_LINE_RE = re.compile(
        r"^\s*(if|for|while|try)\b",
        re.MULTILINE,
    )

    def _count_control_depth_proxy(self, snippet: str) -> int:
        """Approximate nested control complexity via leading-keyword lines."""
        return len(self._CONTROL_LINE_RE.findall(snippet or ""))

    @staticmethod
    def _naming_quality_ok(name: str) -> bool:
        n = (name or "").strip()
        if len(n) <= 1:
            return False
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", n):
            return False
        if "_" in n:
            return True
        if n[0].islower():
            return True
        if len(n) > 1 and n[0].isupper() and any(ch.islower() for ch in n[1:]):
            return True
        return False

    @staticmethod
    def _signature_has_type_annotations(signature: str) -> bool:
        s = signature or ""
        if "->" in s:
            return True
        if ":" in s:
            depth = 0
            for i, ch in enumerate(s):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == ":" and depth > 0:
                    return True
        return False

    async def _has_test_reference(self, entity_name: str) -> bool:
        needle = (entity_name or "").strip()
        if len(needle) < 2:
            return False
        try:
            res = await self._analysis.agent_has_test_reference(needle)
            return bool(res.data)
        except Exception as exc:
            log.warning("has_test_reference_query_failed", error=str(exc))
            return False

    async def compute_quality_score(self, uid: str, entity_type: str = "") -> dict[str, Any]:
        """Heuristic 0–100 quality score for a Function or Class node."""
        breakdown: dict[str, Any] = {}
        suggestions: list[str] = []
        et = (entity_type or "").strip().lower()

        if et == "function":
            type_clause = "n:Function"
        elif et == "class":
            type_clause = "n:Class"
        else:
            type_clause = "n:Function OR n:Class"

        try:
            res = await self._analysis.agent_quality_score_lookup(uid, type_clause)
        except Exception as exc:
            log.warning("compute_quality_score_lookup_failed", uid=uid, error=str(exc))
            return {
                "score": 0,
                "breakdown": {},
                "suggestions": [f"Lookup failed: {exc}"],
                "entity_uid": uid,
            }

        if not res.data:
            return {
                "score": 0,
                "breakdown": {},
                "suggestions": ["Entity not found or unsupported type for this uid"],
                "entity_uid": uid,
            }

        row = res.data[0]
        name = str(row.get("name") or "")
        signature = str(row.get("signature") or "")
        docstring = str(row.get("docstring") or "")
        snippet = str(row.get("code_snippet") or "")
        roles = row.get("semantic_roles")

        score = 0

        has_doc = bool(docstring.strip())
        breakdown["has_docstring"] = has_doc
        if has_doc:
            score += 20
        else:
            suggestions.append("Add a docstring describing purpose and behavior.")

        has_types = self._signature_has_type_annotations(signature)
        breakdown["has_type_annotations"] = has_types
        if has_types:
            score += 15
        else:
            suggestions.append("Add parameter and return types to the signature where possible.")

        line_count = len(snippet.splitlines()) if snippet else 0
        reasonable = line_count < 200
        breakdown["reasonable_length"] = reasonable
        breakdown["line_count"] = line_count
        if reasonable:
            score += 15
        else:
            suggestions.append("Consider splitting or refactoring: body is very long.")

        has_tests = await self._has_test_reference(name)
        breakdown["has_tests"] = has_tests
        if has_tests:
            score += 15
        else:
            suggestions.append("Add or extend tests that reference this symbol.")

        naming_ok = self._naming_quality_ok(name)
        breakdown["naming_quality"] = naming_ok
        if naming_ok:
            score += 10
        else:
            suggestions.append("Use descriptive camelCase or snake_case names (avoid single-letter identifiers).")

        has_semantic = isinstance(roles, list) and len(roles) > 0
        breakdown["has_annotations"] = has_semantic
        if has_semantic:
            score += 10
        else:
            suggestions.append("Enrich indexing so semantic_roles are set where applicable.")

        ctrl_count = self._count_control_depth_proxy(snippet)
        complexity_ok = ctrl_count < 10
        breakdown["complexity_ok"] = complexity_ok
        breakdown["control_keyword_lines"] = ctrl_count
        if complexity_ok:
            score += 15
        else:
            suggestions.append("Reduce branching/loop nesting or extract helper methods.")

        score = max(0, min(100, score))

        return {
            "score": score,
            "breakdown": breakdown,
            "suggestions": suggestions,
            "entity_uid": uid,
            "entity_name": name,
        }
