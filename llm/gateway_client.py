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
from typing import Any

import httpx
import websockets
import websockets.asyncio.client

logger = logging.getLogger(__name__)

_MAX_ENTITIES_PER_ROUND = 10

_ENRICHMENT_PROMPT = """\
你是一个代码业务语义标注助手。我会分批向你提供代码实体（函数/类），你需要为每个实体生成简洁的中文业务语义描述。

## 要求
1. 为每个代码实体生成业务语义描述（中文，不超过200字）
2. 描述包含：所属业务领域、在业务流程中的角色、业务用途
3. 不要描述技术实现细节
4. 输出格式必须是严格的 JSON 数组：
```json
[{{"name": "<实体名>", "summary": "<描述>"}}]
```

## 当前批次（共 {count} 个实体）
{entities}

请分析以上实体并生成 JSON 格式的业务语义描述。完成后，请通过 request_feedback 工具提交你的分析结果，在 summary 字段中放入完整的 JSON 数组。等待我的反馈以获取下一批实体。
"""


def _format_entity(idx: int, item: dict[str, str]) -> str:
    parts = [f"### 实体 {idx + 1}: {item.get('name', 'unknown')}"]
    if item.get("file"):
        parts.append(f"文件: {item['file']}")
    if item.get("signature"):
        parts.append(f"签名: {item['signature']}")
    if item.get("docstring"):
        parts.append(f"文档: {item['docstring'][:500]}")
    if item.get("code_snippet"):
        parts.append(f"代码:\n```\n{item['code_snippet'][:1000]}\n```")
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

        results: list[str] = [""] * len(items)
        self._msg_id = 0

        batches = [
            items[i : i + _MAX_ENTITIES_PER_ROUND]
            for i in range(0, len(items), _MAX_ENTITIES_PER_ROUND)
        ]

        ws = await websockets.asyncio.client.connect(
            self._ws_url,
            additional_headers={"Authorization": f"Bearer {self._api_key}"},
        )

        try:
            session_id = await self._create_session(ws)
            logger.info("Gateway session created (agent mode): %s", session_id)

            first_batch = batches[0]
            entities_text = "\n\n".join(
                _format_entity(i, item) for i, item in enumerate(first_batch)
            )
            prompt = _ENRICHMENT_PROMPT.format(
                count=len(first_batch), entities=entities_text,
            )
            await self._send_prompt(ws, session_id, prompt)
            logger.info("Enrichment prompt sent (%d entities in first batch)", len(first_batch))

            global_idx = 0
            batch_idx = 0

            while batch_idx < len(batches):
                current_batch = batches[batch_idx]

                task_id, summary_text, text_chunks = await self._wait_for_response(ws)

                response_text = summary_text or "".join(text_chunks)
                summaries_map = _parse_json_summaries(response_text)

                for i, item in enumerate(current_batch):
                    name = item.get("name", "")
                    if name in summaries_map:
                        results[global_idx + i] = summaries_map[name]

                matched = sum(1 for item in current_batch if item.get("name", "") in summaries_map)
                logger.info(
                    "Batch %d/%d: %d/%d entities enriched",
                    batch_idx + 1, len(batches), matched, len(current_batch),
                )

                global_idx += len(current_batch)
                batch_idx += 1

                if batch_idx < len(batches) and task_id:
                    next_batch = batches[batch_idx]
                    next_entities_text = "\n\n".join(
                        _format_entity(i, item) for i, item in enumerate(next_batch)
                    )
                    feedback_text = (
                        f"上一批处理完成。请继续处理下一批 {len(next_batch)} 个实体，"
                        f"同样以 JSON 数组格式输出：\n\n{next_entities_text}"
                    )
                    await self._submit_feedback(task_id, feedback_text, action="continue")
                elif task_id:
                    await self._submit_feedback(task_id, "全部完成，谢谢！", action="complete")
                else:
                    break

            logger.info("All %d entities processed in one task", len(items))

        except Exception:
            logger.exception("Gateway task enrichment failed")
        finally:
            await ws.close()

        return results

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
