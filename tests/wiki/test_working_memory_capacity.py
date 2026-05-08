"""Tests for P1.3: WorkingMemory capacity increase."""
from __future__ import annotations

from wiki.page_agent import WorkingMemory


class TestWorkingMemoryCapacity:
    def test_max_chars_is_50000(self):
        assert WorkingMemory.MAX_TOTAL_CHARS == 50000

    def test_can_store_more_data_than_before(self):
        """Memory should hold at least 40000 chars without eviction."""
        mem = WorkingMemory()
        # Add 40 snippets of 1000 chars each = 40000 chars
        for i in range(40):
            mem.code_snippets.append("x" * 1000)
        mem._enforce_limit()
        # Should retain most of them (40000 < 50000)
        total = mem._total_chars()
        assert total == 40000

    def test_evicts_when_over_limit(self):
        """Memory should still evict when over 50000."""
        mem = WorkingMemory()
        # Add 60 snippets of 1000 chars each = 60000 chars (over limit)
        for i in range(60):
            mem.code_snippets.append("x" * 1000)
        mem._enforce_limit()
        total = mem._total_chars()
        assert total <= 50000

    def test_eviction_removes_oldest_first(self):
        """FIFO eviction: oldest items removed first."""
        mem = WorkingMemory()
        mem.code_snippets.append("FIRST")
        for i in range(55):
            mem.code_snippets.append("y" * 1000)  # 55000 total > 50000
        mem._enforce_limit()
        # "FIRST" should be evicted (it was oldest)
        assert "FIRST" not in mem.code_snippets
