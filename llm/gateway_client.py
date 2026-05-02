"""ACP Gateway task-based client — feedback-loop enrichment in one task.

Connects via WebSocket (agent mode), sends a single prompt with ALL code
entities + enrichment instructions.  The gateway auto-injects feedback-tool
instructions (curl).  The agent processes the entities, calls
``request_feedback`` once done, and the KB service responds via the HTTP
feedback API.

For large entity lists this still uses only **one** ACP task (one billing
unit), because subsequent entities are fed through the feedback loop.

Fallback: if the agent fails to call the feedback tool (e.g. for very
small prompts), the text response is parsed directly for JSON summaries.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from typing import Any

import httpx
import websockets
import websockets.asyncio.client
import websockets.exceptions

from indexer.enrichment import ENRICHMENT_SUMMARY_MAX_ZH, truncate_enrichment_item

logger = logging.getLogger(__name__)

_MAX_ENTITIES_PER_ROUND = 50

_ENRICHMENT_PROMPT = f"""\
你是一个代码业务语义标注助手。我会分批向你提供代码实体（函数/类），你需要为每个实体生成简洁的中文业务语义描述。

## 要求
1. 为每个代码实体生成业务语义描述（中文，不超过{ENRICHMENT_SUMMARY_MAX_ZH}字）
2. 描述包含：所属业务领域、在业务流程中的角色、业务用途
3. 不要描述技术实现细节
4. 输出格式必须是严格的 JSON 数组：
```json
[{{"name": "<实体名>", "summary": "<描述>"}}]
```

## 当前批次（共 {{count}} 个实体）
{{entities}}

请分析以上实体并生成 JSON 格式的业务语义描述。完成后，请通过 request_feedback 工具提交你的分析结果，在 summary 字段中放入完整的 JSON 数组。等待我的反馈以获取下一批实体。
"""


def _format_entity(idx: int, item: dict[str, str]) -> str:
    t = truncate_enrichment_item(item)
    parts = [f"### 实体 {idx + 1}: {t.get('name', 'unknown')}"]
    if t.get("file"):
        parts.append(f"文件: {t['file']}")
    if t.get("signature"):
        parts.append(f"签名: {t['signature']}")
    if t.get("docstring"):
        parts.append(f"文档: {t['docstring']}")
    if t.get("code_snippet"):
        parts.append(f"代码:\n```\n{t['code_snippet']}\n```")
    return "\n".join(parts)


def _parse_json_summaries(text: str) -> dict[str, str]:
    """Extract name→summary mapping from text that may contain JSON."""
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    json_str = code_block.group(1).strip() if code_block else text.strip()

    array_match = re.search(r"\[.*\]", json_str, re.DOTALL)
    if array_match:
        json_str = array_match.group(0)

    try:
        items = json.loads(json_str)
        if isinstance(items, list):
            return {
                item.get("name", ""): item.get("summary", "")
                for item in items
                if isinstance(item, dict) and item.get("name")
            }
    except json.JSONDecodeError:
        pass

    return {}


class GatewayTaskClient:
    """Drives batch enrichment through the gateway's feedback loop.

    Parameters
    ----------
    gateway_ws_url:
        WebSocket URL, e.g. ``ws://localhost:9090/acp/v1/connect``
    gateway_http_url:
        HTTP base URL for feedback API, e.g. ``http://localhost:9090``
    api_key:
        Bearer token accepted by the gateway.
    model:
        LLM model name (resolved by the gateway).
    timeout:
        Per-round timeout in seconds.
    """

    def __init__(
        self,
        gateway_ws_url: str = "ws://localhost:9090/acp/v1/connect",
        gateway_http_url: str = "http://localhost:9090",
        api_key: str = "sk-admin-test",
        model: str = "gemini-3-flash",
        timeout: float = 300,
    ) -> None:
        self._ws_url = gateway_ws_url
        self._http_url = gateway_http_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout),
        )
        self._msg_id = 0

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def enrich_batch(self, items: list[dict[str, str]]) -> list[str]:
        """Enrich all code entities within one ACP task via the feedback loop.

        Returns summaries in the same order as *items*.
        """
        if not items:
            return []

        queue: asyncio.Queue[list[dict[str, str]] | None] = asyncio.Queue()
        for i in range(0, len(items), _MAX_ENTITIES_PER_ROUND):
            queue.put_nowait(items[i : i + _MAX_ENTITIES_PER_ROUND])
        queue.put_nowait(None)

        result_map: dict[str, str] = {}
        await self._run_feedback_loop(queue, result_map)

        return [result_map.get(item.get("name", ""), "") for item in items]

    async def enrich_stream(
        self,
        queue: asyncio.Queue[list[dict[str, str]] | None],
        result_callback: Callable[[str, str], Any] | None = None,
    ) -> dict[str, str]:
        """Stream enrichment: process batches from *queue* within one ACP task.

        Put batches (list of entity dicts) into *queue*; put ``None`` to signal
        end-of-stream.  Returns name→summary mapping.  Optionally calls
        *result_callback(name, summary)* for each enriched entity as results
        arrive, enabling the caller to persist results before all items finish.
        """
        result_map: dict[str, str] = {}
        await self._run_feedback_loop(queue, result_map, result_callback)
        return result_map

    async def _run_feedback_loop(
        self,
        queue: asyncio.Queue[list[dict[str, str]] | None],
        result_map: dict[str, str],
        result_callback: Callable[[str, str], Any] | None = None,
    ) -> None:
        """Core feedback loop shared by batch and streaming modes."""
        self._msg_id = 0

        first_batch = await queue.get()
        if first_batch is None:
            return

        ws = await websockets.asyncio.client.connect(
            self._ws_url,
            additional_headers={"Authorization": f"Bearer {self._api_key}"},
        )

        try:
            session_id = await self._create_session(ws)
            logger.info("Gateway session created (agent mode): %s", session_id)

            entities_text = "\n\n".join(
                _format_entity(i, item) for i, item in enumerate(first_batch)
            )
            prompt = _ENRICHMENT_PROMPT.format(
                count=len(first_batch), entities=entities_text,
            )
            await self._send_prompt(ws, session_id, prompt)
            logger.info("Enrichment prompt sent (%d entities in first batch)", len(first_batch))

            current_batch = first_batch
            round_num = 0
            total_enriched = 0

            while True:
                round_num += 1
                task_id, summary_text, text_chunks = await self._wait_for_response(ws)

                response_text = summary_text or "".join(text_chunks)
                summaries = _parse_json_summaries(response_text)
                result_map.update(summaries)
                total_enriched += len(summaries)

                matched = sum(1 for item in current_batch if item.get("name", "") in summaries)
                logger.info("Round %d: %d/%d entities enriched", round_num, matched, len(current_batch))

                if result_callback:
                    for name, summary in summaries.items():
                        result_callback(name, summary)

                next_batch = await queue.get()

                if next_batch is None:
                    if task_id:
                        try:
                            await self._submit_feedback(task_id, "全部完成，谢谢！", action="complete")
                        except httpx.HTTPStatusError:
                            logger.warning("Complete feedback rejected (task may have ended)")
                    break

                if not task_id:
                    logger.warning("Agent ended without feedback call, %d batches remaining", queue.qsize() + 1)
                    queue.put_nowait(None)
                    break

                next_entities_text = "\n\n".join(
                    _format_entity(i, item) for i, item in enumerate(next_batch)
                )
                feedback_text = (
                    f"上一批处理完成。请继续处理下一批 {len(next_batch)} 个实体，"
                    f"同样以 JSON 数组格式输出：\n\n{next_entities_text}"
                )
                try:
                    await self._submit_feedback(task_id, feedback_text, action="continue")
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "Feedback rejected (%s), stopping loop", exc.response.status_code,
                    )
                    queue.put_nowait(None)
                    break
                current_batch = next_batch

            logger.info("Feedback loop complete: %d entities enriched in %d rounds", total_enriched, round_num)

        except Exception:
            logger.exception("Gateway task enrichment failed")
            raise
        finally:
            await ws.close()

    async def _create_session(self, ws: Any) -> str:
        msg_id = self._next_id()
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "session/new",
            "params": {
                "cwd": "/tmp/kb-enrichment",
                "mode": "agent",
                "model": self._model,
                "mcpServers": [],
            },
        }))

        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=60)
            msg = json.loads(raw)
            if msg.get("id") == msg_id:
                result = msg.get("result", {})
                sid = result.get("sessionId", "")
                if not sid:
                    raise RuntimeError(f"session/new failed: {msg}")
                return sid

    async def _send_prompt(self, ws: Any, session_id: str, text: str) -> None:
        msg_id = self._next_id()
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "session/prompt",
            "params": {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": text}],
            },
        }))

    async def _wait_for_response(self, ws: Any) -> tuple[str | None, str, list[str]]:
        """Wait for either a feedback_request or end_turn.

        Returns ``(task_id_or_none, feedback_summary, text_chunks)``.
        - If agent called request_feedback: task_id is set, summary contains the agent's summary.
        - If agent ended turn without feedback: task_id is None, text_chunks contain the response.
        """
        task_id = None
        summary = ""
        text_chunks: list[str] = []
        deadline = asyncio.get_event_loop().time() + self._timeout

        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.warning("Timed out waiting for agent response")
                break

            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break

            msg = json.loads(raw)

            if msg.get("method") == "gateway/feedback_request":
                params = msg.get("params", {})
                task_id = params.get("task_id")
                summary = params.get("summary", "")
                logger.info("Agent called request_feedback (task=%s)", task_id)
                return task_id, summary, text_chunks

            if msg.get("method") == "session/update":
                text = self._extract_text(msg.get("params", {}))
                if text:
                    text_chunks.append(text)

            if msg.get("result") and isinstance(msg.get("result"), dict):
                stop_reason = msg["result"].get("stopReason", "")
                if stop_reason:
                    logger.info("Agent turn ended (stopReason=%s) without feedback call", stop_reason)
                    break

        return task_id, summary, text_chunks

    @staticmethod
    def _extract_text(params: dict[str, Any]) -> str:
        update = params.get("update", {})
        if isinstance(update, dict):
            su = update.get("sessionUpdate", "")
            if su == "agent_message_chunk":
                content = update.get("content", {})
                if isinstance(content, dict):
                    return content.get("text", "")
                if isinstance(content, str):
                    return content
        return ""

    async def _submit_feedback(
        self, task_id: str, feedback: str, *, action: str = "continue",
    ) -> None:
        url = f"{self._http_url}/api/v1/tasks/{task_id}/feedback"
        resp = await self._http.post(url, json={"feedback": feedback, "action": action})
        resp.raise_for_status()
        logger.info("Feedback submitted (action=%s)", action)

    async def close(self) -> None:
        await self._http.aclose()


class _RepoTask:
    """State for a single persistent ACP task bound to one repository."""

    __slots__ = ("ws", "session_id", "task_id", "last_active", "lock", "_msg_id", "_in_use")

    def __init__(
        self,
        ws: Any,
        session_id: str,
        task_id: str,
    ) -> None:
        self.ws = ws
        self.session_id = session_id
        self.task_id = task_id
        self.last_active: float = asyncio.get_event_loop().time()
        self.lock = asyncio.Lock()
        self._msg_id = 0
        self._in_use = False

    def next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def touch(self) -> None:
        self.last_active = asyncio.get_event_loop().time()


_STANDBY_MSG = (
    "当前索引操作完成。请待命等待下一批实体。"
    "调用 request_feedback 工具报告就绪状态，在 summary 中写 STANDBY。"
)


class RepoTaskManager:
    """Manages persistent ACP tasks keyed by repository.

    One repository always reuses a single ACP task (= 1 billing unit) across
    multiple indexing operations until the task times out or is explicitly
    closed.

    Parameters
    ----------
    gateway_ws_url / gateway_http_url / api_key / model:
        Same as :class:`GatewayTaskClient`.
    idle_timeout:
        Seconds of inactivity before an idle task is automatically closed.
    response_timeout:
        Per-round timeout for waiting on agent responses.
    """

    def __init__(
        self,
        gateway_ws_url: str = "ws://localhost:9090/acp/v1/connect",
        gateway_http_url: str = "http://localhost:9090",
        api_key: str = "sk-admin-test",
        model: str = "gemini-3-flash",
        idle_timeout: float = 3600,
        response_timeout: float = 300,
    ) -> None:
        self._ws_url = gateway_ws_url
        self._http_url = gateway_http_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._idle_timeout = idle_timeout
        self._response_timeout = response_timeout
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(response_timeout),
        )
        self._tasks: dict[str, _RepoTask] = {}
        self._global_lock = asyncio.Lock()
        self._cleanup_handle: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._cleanup_handle is None:
            self._cleanup_handle = asyncio.create_task(self._cleanup_loop())

    async def enrich(
        self,
        repo_id: str,
        items: list[dict[str, str]],
    ) -> list[str]:
        """Batch enrichment within a persistent repo task."""
        if not items:
            return []
        queue: asyncio.Queue[list[dict[str, str]] | None] = asyncio.Queue()
        for i in range(0, len(items), _MAX_ENTITIES_PER_ROUND):
            queue.put_nowait(items[i : i + _MAX_ENTITIES_PER_ROUND])
        queue.put_nowait(None)

        result_map = await self.enrich_stream(repo_id, queue)
        return [result_map.get(item.get("name", ""), "") for item in items]

    async def enrich_stream(
        self,
        repo_id: str,
        queue: asyncio.Queue[list[dict[str, str]] | None],
    ) -> dict[str, str]:
        """Stream enrichment within a persistent repo task.

        Batches arrive via *queue*; ``None`` signals end-of-stream.
        After processing, the task enters standby mode for reuse.
        """
        task = await self._get_or_create(repo_id)
        result_map: dict[str, str] = {}

        async with task.lock:
            task._in_use = True
            try:
                result_map = await self._do_enrich(repo_id, task, queue)
            except (websockets.exceptions.ConnectionClosed, OSError) as exc:
                logger.warning("[%s] WebSocket error during enrichment: %s", repo_id, exc)
                await self._evict_task(repo_id, task)
                raise
            except Exception:
                logger.exception("[%s] Enrichment failed", repo_id)
                await self._evict_task(repo_id, task)
                raise
            finally:
                task._in_use = False

        return result_map

    async def _do_enrich(
        self,
        repo_id: str,
        task: _RepoTask,
        queue: asyncio.Queue[list[dict[str, str]] | None],
    ) -> dict[str, str]:
        """Inner enrichment loop; caller holds ``task.lock``."""
        result_map: dict[str, str] = {}

        first_batch = await queue.get()
        if first_batch is None:
            return result_map

        if task.task_id:
            entities_text = "\n\n".join(
                _format_entity(i, item) for i, item in enumerate(first_batch)
            )
            feedback_text = (
                f"新的索引操作开始。请处理以下 {len(first_batch)} 个代码实体，"
                f"同样以 JSON 数组格式输出：\n\n{entities_text}"
            )
            await self._submit_feedback(task.task_id, feedback_text, action="continue")
            logger.info("[%s] Reusing existing task, sent %d entities as feedback", repo_id, len(first_batch))
        else:
            entities_text = "\n\n".join(
                _format_entity(i, item) for i, item in enumerate(first_batch)
            )
            prompt = _ENRICHMENT_PROMPT.format(count=len(first_batch), entities=entities_text)
            msg_id = task.next_id()
            await task.ws.send(json.dumps({
                "jsonrpc": "2.0", "id": msg_id,
                "method": "session/prompt",
                "params": {"sessionId": task.session_id, "prompt": [{"type": "text", "text": prompt}]},
            }))
            logger.info("[%s] New task, sent initial prompt with %d entities", repo_id, len(first_batch))

        current_batch = first_batch
        round_num = 0

        while True:
            round_num += 1
            tid, summary_text, text_chunks = await self._wait_for_response(task)

            if tid:
                task.task_id = tid

            response_text = summary_text or "".join(text_chunks)
            summaries = _parse_json_summaries(response_text)
            result_map.update(summaries)
            task.touch()

            matched = sum(1 for item in current_batch if item.get("name", "") in summaries)
            logger.info("[%s] Round %d: %d/%d enriched", repo_id, round_num, matched, len(current_batch))

            next_batch = await queue.get()
            if next_batch is None:
                break

            if not task.task_id:
                logger.warning("[%s] Agent ended without feedback, cannot continue", repo_id)
                break

            nxt_text = "\n\n".join(_format_entity(i, item) for i, item in enumerate(next_batch))
            try:
                await self._submit_feedback(
                    task.task_id,
                    f"上一批处理完成。请继续处理下一批 {len(next_batch)} 个实体，"
                    f"同样以 JSON 数组格式输出：\n\n{nxt_text}",
                    action="continue",
                )
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "[%s] Feedback rejected (%s), stopping enrichment loop",
                    repo_id, exc.response.status_code,
                )
                break
            current_batch = next_batch

        if task.task_id:
            try:
                await self._submit_feedback(task.task_id, _STANDBY_MSG, action="continue")
                tid, _, _ = await self._wait_for_response(task)
                if tid:
                    task.task_id = tid
                logger.info("[%s] Task entered standby (total %d enriched)", repo_id, len(result_map))
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "[%s] Standby feedback failed (%s), evicting task",
                    repo_id, exc.response.status_code,
                )
                await self._evict_task(repo_id, task)
        else:
            await self._evict_task(repo_id, task)

        return result_map

    async def prompt(self, tenant_id: str, text: str) -> str:
        """Send a single LLM prompt within a persistent tenant task.

        Used for deep search and other single-turn LLM calls.
        Returns the agent's text response.
        """
        task = await self._get_or_create(tenant_id)
        async with task.lock:
            task._in_use = True
            try:
                return await self._do_prompt(tenant_id, task, text)
            except (websockets.exceptions.ConnectionClosed, OSError) as exc:
                logger.warning("[%s] WebSocket error during prompt: %s", tenant_id, exc)
                await self._evict_task(tenant_id, task)
                raise
            except Exception:
                logger.exception("[%s] Prompt failed", tenant_id)
                await self._evict_task(tenant_id, task)
                raise
            finally:
                task._in_use = False

    async def _do_prompt(self, tenant_id: str, task: _RepoTask, text: str) -> str:
        """Single prompt round + standby; caller holds ``task.lock``."""
        if task.task_id:
            await self._submit_feedback(task.task_id, text, action="continue")
            logger.info("[%s] Reusing existing task, sent prompt as feedback", tenant_id)
        else:
            msg_id = task.next_id()
            await task.ws.send(json.dumps({
                "jsonrpc": "2.0",
                "id": msg_id,
                "method": "session/prompt",
                "params": {
                    "sessionId": task.session_id,
                    "prompt": [{"type": "text", "text": text}],
                },
            }))
            logger.info("[%s] New task, sent initial prompt (deep search / single-turn)", tenant_id)

        tid, summary_text, text_chunks = await self._wait_for_response(task)
        if tid:
            task.task_id = tid
        response_text = summary_text or "".join(text_chunks)
        task.touch()

        if task.task_id:
            try:
                await self._submit_feedback(task.task_id, _STANDBY_MSG, action="continue")
                tid2, _, _ = await self._wait_for_response(task)
                if tid2:
                    task.task_id = tid2
                logger.info("[%s] Task entered standby after prompt", tenant_id)
            except httpx.HTTPStatusError as exc:
                logger.warning(
                    "[%s] Standby feedback failed (%s), evicting task",
                    tenant_id, exc.response.status_code,
                )
                await self._evict_task(tenant_id, task)
        else:
            await self._evict_task(tenant_id, task)

        return response_text

    async def _evict_task(self, repo_id: str, task: _RepoTask) -> None:
        """Remove a task from the registry and close its resources."""
        async with self._global_lock:
            if self._tasks.get(repo_id) is task:
                del self._tasks[repo_id]
        await self._close_task(task)

    async def close_repo(self, repo_id: str) -> None:
        async with self._global_lock:
            task = self._tasks.pop(repo_id, None)
        if task:
            await self._close_task(task)

    async def close_all(self) -> None:
        if self._cleanup_handle:
            self._cleanup_handle.cancel()
            self._cleanup_handle = None
        async with self._global_lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for t in tasks:
            async with t.lock:
                await self._close_task(t)
        await self._http.aclose()

    async def _get_or_create(self, repo_id: str) -> _RepoTask:
        async with self._global_lock:
            if repo_id in self._tasks:
                task = self._tasks[repo_id]
                if not self._ws_closed(task):
                    return task
                logger.info("[%s] Stale connection detected, recreating", repo_id)
                del self._tasks[repo_id]
                try:
                    await task.ws.close()
                except Exception:
                    logger.debug("acp_ws_close_failed_before_recreate", exc_info=True)

            task = await self._create_new_task(repo_id)
            self._tasks[repo_id] = task
            return task

    async def _create_new_task(self, repo_id: str) -> _RepoTask:
        ws = await websockets.asyncio.client.connect(
            self._ws_url,
            additional_headers={"Authorization": f"Bearer {self._api_key}"},
        )
        task = _RepoTask(ws=ws, session_id="", task_id="")
        msg_id = task.next_id()
        await ws.send(json.dumps({
            "jsonrpc": "2.0", "id": msg_id,
            "method": "session/new",
            "params": {
                "cwd": f"/tmp/kb-enrichment/{repo_id}",
                "mode": "agent",
                "model": self._model,
                "mcpServers": [],
            },
        }))

        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=60)
            msg = json.loads(raw)
            if msg.get("id") == msg_id:
                result = msg.get("result", {})
                sid = result.get("sessionId", "")
                if not sid:
                    raise RuntimeError(f"session/new failed: {msg}")
                task.session_id = sid
                logger.info("[%s] Created new ACP session: %s", repo_id, sid)
                return task

    async def _wait_for_response(self, task: _RepoTask) -> tuple[str | None, str, list[str]]:
        tid: str | None = None
        summary = ""
        text_chunks: list[str] = []
        deadline = asyncio.get_event_loop().time() + self._response_timeout

        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(task.ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket closed while waiting for response")
                raise

            msg = json.loads(raw)

            if msg.get("method") == "gateway/feedback_request":
                params = msg.get("params", {})
                tid = params.get("task_id")
                summary = params.get("summary", "")
                return tid, summary, text_chunks

            if msg.get("method") == "session/update":
                text = GatewayTaskClient._extract_text(msg.get("params", {}))
                if text:
                    text_chunks.append(text)

            if msg.get("result") and isinstance(msg.get("result"), dict):
                if msg["result"].get("stopReason"):
                    break

        return tid, summary, text_chunks

    async def _submit_feedback(
        self, task_id: str, feedback: str, *, action: str = "continue",
    ) -> None:
        url = f"{self._http_url}/api/v1/tasks/{task_id}/feedback"
        resp = await self._http.post(url, json={"feedback": feedback, "action": action})
        resp.raise_for_status()

    async def _close_task(self, task: _RepoTask) -> None:
        try:
            if task.task_id:
                await self._submit_feedback(task.task_id, "任务关闭。", action="complete")
        except Exception:
            logger.debug("acp_feedback_complete_on_close_failed", exc_info=True)
        try:
            await task.ws.close()
        except Exception:
            logger.debug("acp_ws_close_failed", exc_info=True)

    @staticmethod
    def _ws_closed(task: _RepoTask) -> bool:
        try:
            return task.ws.close_code is not None
        except Exception:
            return True

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = asyncio.get_event_loop().time()
            to_close: list[tuple[str, _RepoTask]] = []
            async with self._global_lock:
                for rid, task in list(self._tasks.items()):
                    if task._in_use:
                        continue
                    if now - task.last_active > self._idle_timeout or self._ws_closed(task):
                        to_close.append((rid, task))
                        del self._tasks[rid]
            for rid, task in to_close:
                logger.info("[%s] Closing idle task (idle %.0fs)", rid, now - task.last_active)
                async with task.lock:
                    await self._close_task(task)
