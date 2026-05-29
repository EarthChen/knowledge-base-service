from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from core.log import get_logger
from wiki.agents.base_agent import LLMGenerationError, RunConfig
from wiki.agents.review_agent import QualityVerdict, ReviewAgent

log = get_logger(__name__)

_EXPLORE_LOOP_CONFIG = RunConfig(
    enable_context_trim=True,
    enable_compaction=True,
    compaction_interval=10,
)


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
        enable_review_agent: bool = False,
        review_block_on_fail: bool = True,
        enable_crag_gate: bool = False,
        crag_coverage_threshold: float = 0.6,
        crag_max_re_explore: int = 1,
    ) -> None:
        self._agent = agent
        self._name = name
        self._max_iterations = max_iterations
        self._explore_system_prompt = explore_system_prompt
        self._write_system_prompt = write_system_prompt
        self._enable_review_agent = enable_review_agent
        self._review_block_on_fail = review_block_on_fail
        self._review_agent: ReviewAgent | None = ReviewAgent() if enable_review_agent else None
        self._enable_crag_gate = enable_crag_gate
        self._crag_coverage_threshold = crag_coverage_threshold
        self._crag_max_re_explore = crag_max_re_explore

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
            config=self._get_explore_config(),
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
                or getattr(memory, "code_snippets", None)
            )
            explore_complete = has_explore_data
            log.warning(
                "orchestrator_explore_timeout",
                name=self._name,
                timeout=explore_timeout,
                has_prefill=bool(getattr(memory, "code_snippets", None)),
                has_explore_data=has_explore_data,
            )

        if self._enable_crag_gate and memory:
            crag_result = self._check_crag_coverage(memory, module_names)
            if not crag_result["pass"]:
                log.warning(
                    "crag_gate_failed",
                    name=self._name,
                    coverage=crag_result["coverage"],
                    missing=crag_result["missing"],
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
        review_quality_flags: list[str] = []
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

            if self._enable_review_agent:
                review_metadata = {"expected_sections": len(module_names)}
                verdict = await self._run_review(content, review_metadata)
                if verdict and verdict.status == "fail" and self._review_block_on_fail:
                    log.warning(
                        "review_agent_fail",
                        name=self._name,
                        issues=len(verdict.issues),
                        heal_instructions=verdict.heal_instructions,
                    )
                    if verdict.heal_instructions:
                        content = await self._heal_content(content, verdict.heal_instructions)
                        content = await self._verify_code_blocks(content, memory)
                        verdict2 = await self._run_review(content, review_metadata)
                        if verdict2 and verdict2.status in ("fail", "warn"):
                            review_quality_flags.append("QUALITY_WARNING")
                elif verdict and verdict.status == "warn":
                    log.info("review_agent_warn", name=self._name, issues=len(verdict.issues))
                    review_quality_flags.append("QUALITY_WARNING")

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
                config=self._get_explore_config(),
            )
            memory.merge(supplemental)

        pages = self.post_process(content, module_names, memory)
        if review_quality_flags:
            for page in pages:
                page.setdefault("quality_flags", []).extend(review_quality_flags)
        return pages

    async def _run_review(self, content: str, metadata: dict) -> QualityVerdict | None:
        """Run ReviewAgent checks on generated content."""
        if not self._enable_review_agent or not self._review_agent:
            return None
        return await self._review_agent.review(content, metadata)

    async def _heal_content(self, content: str, heal_instructions: str) -> str:
        """Re-generate content applying review heal instructions."""
        heal_prompt = (
            f"Revise the following documentation to address these quality issues:\n\n"
            f"{heal_instructions}\n\n"
            f"--- Original content ---\n{content}"
        )
        try:
            return await self._agent.run_generation(
                self._write_system_prompt,
                heal_prompt,
            )
        except (LLMGenerationError, TimeoutError):
            log.warning("review_heal_failed", name=self._name, exc_info=True)
            return content

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

    def _check_crag_coverage(self, memory: Any, target_modules: list[str]) -> dict:
        """Check if WorkingMemory covers target modules sufficiently."""
        if not getattr(self, "_enable_crag_gate", False):
            return {"pass": True, "coverage": 1.0, "missing": []}

        if not target_modules:
            return {"pass": True, "coverage": 1.0, "missing": []}

        covered: set[str] = set()
        memory_modules: set[str] = set()

        if hasattr(memory, "relevant_modules"):
            raw_modules = getattr(memory, "relevant_modules", []) or []
            memory_modules = set(raw_modules)

        for target in target_modules:
            target_lower = target.lower()
            for mem_mod in memory_modules:
                mem_lower = mem_mod.lower()
                if target_lower in mem_lower or mem_lower in target_lower:
                    covered.add(target)
                    break

        coverage = len(covered) / len(target_modules) if target_modules else 1.0
        missing = [t for t in target_modules if t not in covered]
        threshold = getattr(self, "_crag_coverage_threshold", 0.6)

        return {
            "pass": coverage >= threshold,
            "coverage": round(coverage, 2),
            "missing": missing,
            "covered_count": len(covered),
            "total_count": len(target_modules),
        }

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

    def _get_explore_config(self) -> RunConfig:
        """Explore-phase RunConfig. Subclasses may override for domain-specific tuning."""
        return _EXPLORE_LOOP_CONFIG

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
