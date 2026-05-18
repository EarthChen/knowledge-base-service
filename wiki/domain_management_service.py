"""Domain hierarchy management service."""

from __future__ import annotations

import json
import uuid
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

_ROOT_SENTINEL = "__root__"


def _clear_user_modified_recursive(nodes: list[dict]) -> None:
    for node in nodes:
        node.pop("user_modified", None)
        _clear_user_modified_recursive(node.get("children", []))


class DomainManagementService:
    """Domain hierarchy management with graph-primary + JSON sync."""

    def __init__(self, wiki_store: Any) -> None:
        self._wiki_store = wiki_store

    def _validate_ownership(self, business_id: str, *uids: str) -> None:
        """Verify all UIDs belong to the given business."""
        for uid in uids:
            if f":{business_id}:" not in uid:
                raise ValueError(
                    f"Section {uid} does not belong to business {business_id}"
                )

    def _is_root(self, uid: str) -> bool:
        return _ROOT_SENTINEL in uid

    async def rename_domain(
        self,
        business_id: str,
        section_uid: str,
        new_title: str,
        new_description: str | None = None,
    ) -> dict[str, Any]:
        self._validate_ownership(business_id, section_uid)
        if self._is_root(section_uid):
            raise ValueError("Cannot modify root section")
        props: dict[str, Any] = {"title": new_title, "user_modified": True}
        if new_description is not None:
            props["description"] = new_description
        await self._wiki_store.update_section_properties(section_uid, props)
        await self._try_sync_json(business_id)
        log.info("domain_renamed", section_uid=section_uid, new_title=new_title)
        return {"success": True, "section_uid": section_uid}

    async def delete_domain(
        self,
        business_id: str,
        section_uid: str,
        promote_children: bool = True,
    ) -> dict[str, Any]:
        self._validate_ownership(business_id, section_uid)
        if self._is_root(section_uid):
            raise ValueError("Cannot modify root section")
        if promote_children:
            parent_uid = await self._wiki_store.get_section_parent(
                section_uid, "business_domain"
            )
            if parent_uid:
                await self._wiki_store.reparent_children(
                    section_uid, parent_uid, "business_domain"
                )
        await self._wiki_store.delete_wiki_section_cascade(
            section_uid, "business_domain",
        )
        await self._try_sync_json(business_id)
        log.info("domain_deleted", section_uid=section_uid, promote=promote_children)
        return {"success": True, "section_uid": section_uid}

    async def create_subdomain(
        self,
        business_id: str,
        parent_uid: str,
        title: str,
        description: str = "",
    ) -> dict[str, Any]:
        self._validate_ownership(business_id, parent_uid)
        section_uid = (
            f"WikiSection:{business_id}:domain:user_{uuid.uuid4().hex[:8]}"
        )
        await self._wiki_store.upsert_wiki_section(
            uid=section_uid,
            title=title,
            description=description,
            section_type="business_domain",
            sort_order=-1,
            auto_generated=False,
        )
        await self._wiki_store.add_has_child_edge(
            parent_uid=parent_uid,
            parent_label="WikiSection",
            child_uid=section_uid,
            child_label="WikiSection",
            view_type="business_domain",
            sort_order=-1,
        )
        await self._wiki_store.update_section_properties(
            section_uid, {"user_modified": True}
        )
        await self._try_sync_json(business_id)
        log.info(
            "subdomain_created", section_uid=section_uid, parent_uid=parent_uid
        )
        return {"success": True, "section_uid": section_uid}

    async def move_domain(
        self,
        business_id: str,
        section_uid: str,
        target_parent_uid: str,
    ) -> dict[str, Any]:
        self._validate_ownership(business_id, section_uid, target_parent_uid)
        if section_uid == target_parent_uid:
            raise ValueError("Cannot move domain to itself")
        if self._is_root(section_uid):
            raise ValueError("Cannot modify root section")
        descendants = await self._wiki_store.get_section_descendants(
            section_uid, "business_domain"
        )
        if target_parent_uid in descendants:
            raise ValueError("Cannot move domain into its own subtree")
        current_parent = await self._wiki_store.get_section_parent(
            section_uid, "business_domain"
        )
        if current_parent:
            await self._wiki_store.remove_has_child_edge(
                current_parent, section_uid, "business_domain"
            )
        await self._wiki_store.add_has_child_edge(
            parent_uid=target_parent_uid,
            parent_label="WikiSection",
            child_uid=section_uid,
            child_label="WikiSection",
            view_type="business_domain",
            sort_order=-1,
        )
        await self._wiki_store.update_section_properties(
            section_uid, {"user_modified": True}
        )
        await self._try_sync_json(business_id)
        log.info("domain_moved", section_uid=section_uid, target=target_parent_uid)
        return {
            "success": True,
            "section_uid": section_uid,
            "new_parent_uid": target_parent_uid,
        }

    async def merge_domains(
        self,
        business_id: str,
        source_uid: str,
        target_uid: str,
    ) -> dict[str, Any]:
        self._validate_ownership(business_id, source_uid, target_uid)
        if source_uid == target_uid:
            raise ValueError("Source and target must differ")
        if self._is_root(source_uid) or self._is_root(target_uid):
            raise ValueError("Cannot modify root section")
        source_descendants = await self._wiki_store.get_section_descendants(
            source_uid, "business_domain",
        )
        if target_uid in source_descendants:
            raise ValueError("Cannot merge domain into its own subtree")
        await self._wiki_store.reparent_children(
            source_uid, target_uid, "business_domain"
        )
        await self._wiki_store.delete_wiki_section_cascade(
            source_uid, "business_domain",
        )
        await self._wiki_store.update_section_properties(
            target_uid, {"user_modified": True}
        )
        await self._try_sync_json(business_id)
        log.info("domains_merged", source=source_uid, target=target_uid)
        return {"success": True, "target_uid": target_uid}

    async def reorganize_domains(
        self,
        business_id: str,
        *,
        reset_user_edits: bool = False,
        llm: Any = None,
    ) -> dict[str, Any]:
        """Manually trigger domain theme aggregation on existing tree."""
        from wiki.domain_merger import aggregate_domains_recursive

        tree_json = await self._wiki_store.execute_query(
            "MATCH (ws:WikiSpace {business_id: $biz}) "
            "RETURN ws.pipeline_domain_tree AS tree",
            {"biz": business_id},
        )
        rows = tree_json.data if hasattr(tree_json, "data") else []
        raw = rows[0].get("tree", "[]") if rows else "[]"
        tree_data = json.loads(raw) if isinstance(raw, str) else raw
        if not tree_data:
            return {"success": False, "message": "No domain tree found"}

        if reset_user_edits:
            _clear_user_modified_recursive(tree_data)

        before_count = len(tree_data)
        result_tree = await aggregate_domains_recursive(tree_data, llm, max_tree_depth=5)

        await self._wiki_store.execute_query(
            "MATCH (ws:WikiSpace {business_id: $biz}) "
            "SET ws.pipeline_domain_tree = $tree",
            {"biz": business_id, "tree": json.dumps(result_tree, ensure_ascii=False)},
        )
        log.info("reorganize_domains_done", business_id=business_id, before=before_count, after=len(result_tree))
        return {"success": True, "domains_before": before_count, "domains_after": len(result_tree)}

    async def move_module_domain(
        self,
        business_id: str,
        module_uid: str,
        target_domain: str,
    ) -> dict[str, Any]:
        await self._wiki_store.update_module_business_domain(
            module_uid, target_domain
        )
        log.info(
            "module_domain_changed", module_uid=module_uid, domain=target_domain
        )
        return {"success": True, "module_uid": module_uid, "domain": target_domain}

    async def _try_sync_json(self, business_id: str) -> None:
        try:
            tree = await self._rebuild_tree_from_graph(business_id)
            await self._wiki_store.execute_query(
                "MATCH (ws:WikiSpace {business_id: $biz}) "
                "SET ws.pipeline_domain_tree = $tree",
                {"biz": business_id, "tree": json.dumps(tree, ensure_ascii=False)},
            )
        except Exception:
            log.warning(
                "domain_json_sync_failed", business_id=business_id, exc_info=True
            )

    async def _rebuild_tree_from_graph(self, business_id: str) -> list[dict[str, Any]]:
        root_uid = f"WikiSection:{business_id}:domain:__root__"
        return await self._build_subtree(root_uid)

    async def _build_subtree(self, parent_uid: str) -> list[dict[str, Any]]:
        children = await self._wiki_store.get_section_children(
            parent_uid, "business_domain"
        )
        result = []
        for child in children:
            if "WikiSection" in str(child.get("labels", [])):
                sub = await self._build_subtree(child["uid"])
                result.append(
                    {
                        "name": child.get("title", ""),
                        "uid": child["uid"],
                        "children": sub,
                    }
                )
        return result
