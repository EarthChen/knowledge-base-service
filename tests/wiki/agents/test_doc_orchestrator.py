import pytest
from unittest.mock import AsyncMock, MagicMock


class TestDocOrchestrator:
    @pytest.mark.asyncio
    async def test_generate_calls_hooks_in_order(self):
        """generate() should call pre_fill → explore → write → evaluate → post_process."""
        from wiki.agents.doc_orchestrator import DocOrchestrator

        class TestOrchestrator(DocOrchestrator):
            call_order: list[str] = []

            async def pre_fill(self, memory, module_names):
                self.call_order.append("pre_fill")

            async def evaluate(self, content, module_names):
                self.call_order.append("evaluate")
                from wiki.agents.doc_orchestrator import QualityResult
                return QualityResult(
                    coverage=1.0, citation_density=1.0,
                    context_gap_count=0, uncovered_modules=[],
                )

            def is_acceptable(self, quality, iteration):
                self.call_order.append("is_acceptable")
                return True

            def post_process(self, content, module_names, memory):
                self.call_order.append("post_process")
                return [{"content": content, "type": "test"}]

        mock_agent = MagicMock()
        mock_memory = MagicMock()
        mock_memory.code_snippets = []
        mock_agent.create_memory = MagicMock(return_value=mock_memory)
        mock_agent.run_tool_loop = AsyncMock(return_value=mock_memory)
        mock_agent.run_generation = AsyncMock(return_value="# Test Content")
        mock_agent.memory_to_prompt = MagicMock(return_value="memory text")

        orch = TestOrchestrator(agent=mock_agent, name="test-domain")
        result = await orch.generate(
            module_names=["ModA"],
            baseline_context="## Test baseline",
        )

        assert orch.call_order == ["pre_fill", "evaluate", "is_acceptable", "post_process"]
        assert len(result) == 1
        assert result[0]["content"] == "# Test Content"

    @pytest.mark.asyncio
    async def test_quality_loop_iterates_on_failure(self):
        """If evaluate returns unacceptable, should re-explore and retry."""
        from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult

        iteration_count = 0

        class IteratingOrchestrator(DocOrchestrator):
            async def pre_fill(self, memory, module_names):
                pass

            async def evaluate(self, content, module_names):
                nonlocal iteration_count
                iteration_count += 1
                return QualityResult(
                    coverage=0.5 if iteration_count < 2 else 1.0,
                    citation_density=0.5,
                    context_gap_count=1 if iteration_count < 2 else 0,
                    uncovered_modules=["X"] if iteration_count < 2 else [],
                )

            def is_acceptable(self, quality, iteration):
                return quality.coverage >= 0.9 and quality.context_gap_count == 0

            def post_process(self, content, module_names, memory):
                return [{"content": content}]

        mock_agent = MagicMock()
        mock_memory = MagicMock()
        mock_memory.code_snippets = []
        mock_agent.create_memory = MagicMock(return_value=mock_memory)
        mock_agent.run_tool_loop = AsyncMock(return_value=mock_memory)
        mock_agent.run_generation = AsyncMock(return_value="content")
        mock_agent.memory_to_prompt = MagicMock(return_value="")

        orch = IteratingOrchestrator(agent=mock_agent, name="test", max_iterations=5)
        await orch.generate(module_names=["M"], baseline_context="ctx")

        assert iteration_count == 2
        assert mock_agent.run_tool_loop.call_count == 2  # initial + supplemental


class TestDocOrchestratorVerification:
    @pytest.mark.asyncio
    async def test_generate_verifies_code_blocks(self):
        """generate() should verify code blocks between write and evaluate."""
        from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult

        class VerifyingOrchestrator(DocOrchestrator):
            async def pre_fill(self, memory, module_names):
                pass

            async def evaluate(self, content, module_names):
                return QualityResult(
                    coverage=1.0, citation_density=1.0,
                    context_gap_count=0, uncovered_modules=[],
                )

            def is_acceptable(self, quality, iteration):
                return True

            def post_process(self, content, module_names, memory):
                return [{"content": content}]

        mock_agent = MagicMock()
        mock_memory = MagicMock()
        mock_memory.code_snippets = [
            "[processOrder @ Order.java]\npublic void processOrder() { real(); }",
        ]
        mock_agent.create_memory = MagicMock(return_value=mock_memory)
        mock_agent.run_tool_loop = AsyncMock(return_value=mock_memory)
        mock_agent.run_generation = AsyncMock(
            return_value="Text\n\n<!-- CODE_REF: processOrder -->\n\nMore."
        )
        mock_agent.memory_to_prompt = MagicMock(return_value="memo")

        orch = VerifyingOrchestrator(agent=mock_agent, name="test")
        result = await orch.generate(module_names=["Mod"], baseline_context="ctx")

        # CODE_REF should be replaced with real code
        assert "```java" in result[0]["content"]
        assert "processOrder" in result[0]["content"]
        assert "<!-- CODE_REF:" not in result[0]["content"]
