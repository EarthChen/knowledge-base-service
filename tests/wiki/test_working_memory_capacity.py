"""Tests for P1.3: WorkingMemory capacity increase."""
from __future__ import annotations

from wiki.page_agent import WorkingMemory


class TestWorkingMemoryCapacity:
    def test_max_chars_is_200000(self):
        assert WorkingMemory.MAX_TOTAL_CHARS == 200_000

    def test_can_store_more_data_than_before(self):
        """Memory should hold at least 40000 chars without eviction."""
        mem = WorkingMemory()
        for i in range(40):
            mem.code_snippets.append("x" * 1000)
        mem._enforce_limit()
        total = mem._total_chars()
        assert total == 40000

    def test_evicts_when_over_limit(self):
        """Memory should still evict when over MAX_TOTAL_CHARS."""
        mem = WorkingMemory()
        for i in range(250):
            mem.code_snippets.append("x" * 1000)
        mem._enforce_limit()
        total = mem._total_chars()
        assert total <= WorkingMemory.MAX_TOTAL_CHARS

    def test_eviction_removes_oldest_first(self):
        """FIFO eviction: oldest items removed first."""
        mem = WorkingMemory()
        mem.code_snippets.append("FIRST")
        for i in range(200):
            mem.code_snippets.append("y" * 1000)  # total > MAX_TOTAL_CHARS
        mem._enforce_limit()
        assert "FIRST" not in mem.code_snippets
