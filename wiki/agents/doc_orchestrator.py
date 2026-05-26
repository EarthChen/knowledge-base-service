from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from core.log import get_logger
from wiki.agents.base_agent import LLMGenerationError

log = get_logger(__name__)


@dataclass
class QualityResult:
    """Quality evaluation output from a doc agent."""

    coverage: float
    citation_density: float
    context_gap_count: int
    uncovered_modules: list[str]
    implementation_depth: float = 0.0


class DocOrchestrator(ABC):
    """Template Method orchestrator for document generation.

    Flow: pre_fill → explore → [write → verify_blocks → evaluate → re-explore]* → post_process
    """

    def __init__(
        self,
        agent: Any,
        *,
        name: str,
        max_iterations: int = 3,
        explore_system_prompt: str = "",
        write_system_prompt: str = "",
    ) -> None:
        self._agent = agent
        self._name = name
        self._max_iterations = max_iterations
        self._explore_system_prompt = explore_system_prompt
        self._write_system_prompt = write_system_prompt

    async def generate(
        self,
        module_names: list[str],
        baseline_context: str,
    ) -> list[dict[str, Any]]:
        """Template method: orchestrates the full generation flow."""
        memory = self._agent.create_memory()

        await self.pre_fill(memory, module_names)

        explore_coro = self._agent.run_tool_loop(
            self._explore_system_prompt,
            self._build_explore_prompt(module_names, baseline_context),
            memory,
        )
        explore_timeout = self.get_phase_timeout("explore")
        explore_complete = True
        try:
            if explore_timeout is not None:
                memory = await asyncio.wait_for(explore_coro, timeout=explore_timeout)
            else:
                memory = await explore_coro
        except TimeoutError:
            has_explore_data = bool(
                getattr(memory, "discovered_call_chains", None)
                or getattr(memory, "discovered_implementations", None)
                or getattr(memory, "search_findings", None)
            )
            explore_complete = has_explore_data
            log.warning(
                "orchestrator_explore_timeout",
                name=self._name,
                timeout=explore_timeout,
                has_prefill=bool(getattr(memory, "code_snippets", None)),
                has_explore_data=has_explore_data,
            )

        topic_plan = None
        if explore_complete:
            topic_plan = await self.plan_topics(memory, module_names)

        if topic_plan is not None:
            pages = await self._write_topics(
                topic_plan, baseline_context, memory, module_names,
            )
            if pages is not None:
                return pages

        content = ""
        for iteration in range(self._max_iterations):
            write_coro = self._agent.run_generation(
                self._write_system_prompt,
                self._build_write_prompt(baseline_context, memory),
            )
            write_timeout = self.get_phase_timeout("write")
            try:
                if write_timeout is not None:
                    content = await asyncio.wait_for(write_coro, timeout=write_timeout)
                else:
                    content = await write_coro
            except LLMGenerationError:
                log.warning("doc_run_generation_failed", name=self._name, exc_info=True)
                generate_skeleton = getattr(self._agent, "_generate_skeleton", None)
                if generate_skeleton is not None:
                    content = generate_skeleton(module_names, self._name)
                break
            except TimeoutError:
                log.warning("orchestrator_write_timeout", name=self._name, iteration=iteration)
                continue

            content = await self._verify_code_blocks(content, memory)

            quality = await self.evaluate(content, module_names)

            await self.run_guardrails(content, iteration, {"module_names": module_names})
            self.build_iteration_trace(iteration, quality)

            if self.is_acceptable(quality, iteration):
                break

            supplemental = self._agent.create_memory()
            supplemental = await self._agent.run_tool_loop(
                self._explore_system_prompt,
                self._build_focused_prompt(quality.uncovered_modules),
                supplemental,
            )
            memory.merge(supplemental)

        return self.post_process(content, module_names, memory)

    async def _verify_code_blocks(self, content: str, memory: Any) -> str:
        """Verify and inject real code blocks. All subclasses benefit automatically."""
        snippets = getattr(memory, "code_snippets", [])
        if not snippets:
            return content
        try:
            from wiki.code_block_verifier import verify_and_inject

            graph = getattr(self._agent, "_graph", None)
            result, stats = await verify_and_inject(content, snippets, graph_store=graph)
            if stats.injected > 0 or stats.replaced > 0:
                log.info(
                    "code_blocks_verified",
                    name=self._name,
                    injected=stats.injected,
                    replaced=stats.replaced,
                    verified=stats.verified,
                    unverified=stats.unverified,
                )
            return result
        except Exception:
            log.warning("code_block_verification_failed", name=self._name, exc_info=True)
            return self._mark_unverified_code_blocks(content)

    @staticmethod
    def _mark_unverified_code_blocks(content: str) -> str:
        """Prefix each fenced code block when verification could not run."""
        from wiki.code_block_verifier import extract_code_blocks

        marker = "<!-- UNVERIFIED: code block verification failed -->\n"
        blocks = extract_code_blocks(content)
        if not blocks:
            return content
        for block in sorted(blocks, key=lambda b: b.start, reverse=True):
            content = content[: block.start] + marker + content[block.start :]
        return content

    def _build_explore_prompt(
        self, module_names: list[str], baseline_context: str
    ) -> str:
        modules_str = ", ".join(module_names) if module_names else "(none)"
        return (
            f"Domain: {self._name}\nModules: {modules_str}\n\n"
            f"Baseline:\n{baseline_context[:8000]}"
        )

    def _build_write_prompt(self, baseline_context: str, memory: Any) -> str:
        memory_section = self._agent.memory_to_prompt(memory)
        return (
            f"Domain: {self._name}\n\n"
            f"Baseline:\n{baseline_context[:8000]}\n\n"
            f"Findings:\n{memory_section}"
        )

    def _build_focused_prompt(self, uncovered_modules: list[str]) -> str:
        modules_str = ", ".join(uncovered_modules)
        return f"Focus exploration on: {modules_str}"

    async def plan_topics(
        self, memory: Any, module_names: list[str],
    ) -> list[Any] | None:
        """Optional: plan topic splits before writing. Default: no splitting."""
        return None

    async def _write_topics(
        self,
        topic_plan: list[Any] | None,
        baseline_context: str,
        memory: Any,
        module_names: list[str],
    ) -> list[dict[str, Any]] | None:
        return None

    def get_phase_timeout(self, phase: str) -> float | None:
        """Optional: per-phase timeout in seconds. Default: no timeout."""
        return None

    async def run_guardrails(
        self, content: str, iteration: int, context: dict[str, Any],
    ) -> Any | None:
        """Optional: run output guardrail chain. Default: skip."""
        return None

    def build_iteration_trace(self, iteration: int, quality: Any) -> dict[str, Any] | None:
        """Optional: collect iteration trace data. Default: skip."""
        return None

    @abstractmethod
    async def pre_fill(self, memory: Any, module_names: list[str]) -> None:
        """Hook 1: Seed initial knowledge into memory before exploration."""

    @abstractmethod
    async def evaluate(
        self, content: str, module_names: list[str]
    ) -> QualityResult:
        """Hook 2: Evaluate generated content quality."""

    @abstractmethod
    def is_acceptable(self, quality: QualityResult, iteration: int) -> bool:
        """Hook 3: Determine if quality is good enough to stop iterating."""

    @abstractmethod
    def post_process(
        self, content: str, module_names: list[str], memory: Any
    ) -> list[dict[str, Any]]:
        """Hook 4: Structure the output into page dicts."""
