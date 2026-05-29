from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from typing import Any

from wiki.agents.base_agent import ToolDef
from wiki.agents.runner import LoopConfig, run_agent_loop


def agent_tool(
    agent_factory: Callable[..., Any],
    *,
    name: str,
    description: str,
    input_schema: dict[str, Any] | None = None,
    system_prompt: str = "You are a specialist agent. Complete the given task thoroughly.",
    config: LoopConfig | None = None,
    tier: int = 2,
) -> ToolDef:
    """Deprecated: use execute_delegation from wiki.agents.delegation instead.

    Register another agent as a tool on the parent agent.

    The sub-agent runs its own tool loop as a bounded subtask and returns
    a structured result to the parent agent's context.
    """
    warnings.warn(
        "agent_tool from wiki.agents.agent_tool is deprecated. Use wiki.agents.delegation instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    async def _handler(args: dict[str, Any], ctx: Any = None) -> dict[str, Any]:
        sub_agent = agent_factory()
        memory = sub_agent.create_memory()

        user_prompt = args.get("query", "") or json.dumps(args, ensure_ascii=False)
        effective_config = config or LoopConfig(max_rounds=4, max_tool_calls=15)

        loop_result = await run_agent_loop(
            sub_agent,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            memory=memory,
            config=effective_config,
        )

        output = loop_result.final_output or sub_agent.memory_to_prompt(loop_result.memory)
        return {
            "output": output,
            "tool_calls_used": loop_result.total_tool_calls,
            "rounds_used": loop_result.total_rounds,
        }

    schema = input_schema or {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The question or task for the specialist agent",
            },
        },
        "required": ["query"],
    }

    return ToolDef(
        name=name,
        description=description,
        parameters=schema,
        handler=_handler,
        tier=tier,
    )
