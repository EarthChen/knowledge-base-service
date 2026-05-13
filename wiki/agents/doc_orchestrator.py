from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from core.log import get_logger

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

        memory = await self._agent.run_tool_loop(
            self._explore_system_prompt,
            self._build_explore_prompt(module_names, baseline_context),
            memory,
        )

        content = ""
        for iteration in range(self._max_iterations):
            content = await self._agent.run_generation(
                self._write_system_prompt,
                self._build_write_prompt(baseline_context, memory),
            )

            content = await self._verify_code_blocks(content, memory)

            quality = await self.evaluate(content, module_names)

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
