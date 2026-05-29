from __future__ import annotations

from wiki.agents.memory import AgentMemory


def test_working_memory_implements_agent_memory():
    from wiki.page_agent import WorkingMemory

    mem = WorkingMemory()
    assert isinstance(mem, AgentMemory)


def test_working_memory_has_required_methods():
    from wiki.page_agent import WorkingMemory

    mem = WorkingMemory()
    assert hasattr(mem, "incorporate")
    assert hasattr(mem, "to_prompt")
    assert hasattr(mem, "merge")
    assert hasattr(mem, "slice")
    assert hasattr(mem, "inject_findings")


def test_merge_deduplicates():
    from wiki.page_agent import WorkingMemory

    mem1 = WorkingMemory()
    mem1.facts = ["fact A"]
    mem1.discovered_call_chains = ["A→B"]

    mem2 = WorkingMemory()
    mem2.facts = ["fact A", "fact B"]
    mem2.discovered_call_chains = ["A→B", "C→D"]

    mem1.merge(mem2)
    assert "fact A" in mem1.facts
    assert "fact B" in mem1.facts
    assert mem1.facts.count("fact A") == 1


def test_slice_returns_subset():
    from wiki.page_agent import WorkingMemory

    mem = WorkingMemory()
    mem.facts = ["f1"]
    mem.code_snippets = ["code"]
    mem.relevant_modules = ["mod"]

    sliced = mem.slice({"facts", "relevant_modules"})
    assert "f1" in sliced.facts
    assert "mod" in sliced.relevant_modules
    assert len(sliced.code_snippets) == 0


def test_slice_does_not_modify_original():
    from wiki.page_agent import WorkingMemory

    mem = WorkingMemory()
    mem.facts = ["f1", "f2"]
    sliced = mem.slice({"facts"})
    sliced.facts.append("f3")
    assert "f3" not in mem.facts


def test_inject_findings():
    from wiki.page_agent import WorkingMemory

    mem = WorkingMemory()
    mem.inject_findings(["finding 1", "finding 2"])
    assert "finding 1" in mem.facts
    assert "finding 2" in mem.facts


def test_inject_findings_deduplicates():
    from wiki.page_agent import WorkingMemory

    mem = WorkingMemory()
    mem.facts = ["finding 1"]
    mem.inject_findings(["finding 1", "finding 2"])
    assert mem.facts.count("finding 1") == 1
    assert "finding 2" in mem.facts
