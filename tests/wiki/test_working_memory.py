"""Tests for WorkingMemory entity UID tracking."""

from wiki.page_agent import WorkingMemory, ToolResult


class TestDiscoveredEntityUids:
    def test_incorporate_extracts_uid_from_read_code(self):
        """incorporate() should extract uid from read_code tool results."""
        memory = WorkingMemory()
        result = ToolResult(
            tool="read_code",
            data={
                "name": "UserService",
                "code": "class UserService { ... }",
                "file": "src/user/UserService.java",
                "uid": "Function:repo:UserService",
                "repository": "ultron",
            },
        )
        memory.incorporate([result])
        assert "Function:repo:UserService" in memory.discovered_entity_uids

    def test_incorporate_extracts_uid_from_ambiguous_read_code(self):
        """incorporate() should extract uids from ambiguous read_code matches."""
        memory = WorkingMemory()
        result = ToolResult(
            tool="read_code",
            data={
                "name": "process",
                "ambiguous": True,
                "matches": [
                    {"name": "process", "uid": "Function:repo:A.process", "code": "x"},
                    {"name": "process", "uid": "Function:repo:B.process", "code": "y"},
                ],
            },
        )
        memory.incorporate([result])
        assert "Function:repo:A.process" in memory.discovered_entity_uids
        assert "Function:repo:B.process" in memory.discovered_entity_uids

    def test_incorporate_extracts_uid_from_search_entities(self):
        """incorporate() should extract uids from search_entities results."""
        memory = WorkingMemory()
        result = ToolResult(
            tool="search_entities",
            data={
                "results": [
                    {"name": "Foo", "type": "Class", "file": "foo.py", "uid": "Class:repo:Foo"},
                    {"name": "bar", "type": "Function", "file": "bar.py", "uid": "Function:repo:bar"},
                ],
            },
        )
        memory.incorporate([result])
        assert "Class:repo:Foo" in memory.discovered_entity_uids
        assert "Function:repo:bar" in memory.discovered_entity_uids

    def test_incorporate_skips_empty_uid(self):
        """incorporate() should not add empty strings to discovered_entity_uids."""
        memory = WorkingMemory()
        result = ToolResult(
            tool="read_code",
            data={"name": "X", "code": "...", "uid": "", "file": ""},
        )
        memory.incorporate([result])
        assert "" not in memory.discovered_entity_uids

    def test_merge_combines_entity_uids(self):
        """merge() should union discovered_entity_uids from both memories."""
        m1 = WorkingMemory()
        m1.discovered_entity_uids.add("uid-1")
        m1.discovered_entity_uids.add("uid-2")

        m2 = WorkingMemory()
        m2.discovered_entity_uids.add("uid-2")
        m2.discovered_entity_uids.add("uid-3")

        m1.merge(m2)
        assert m1.discovered_entity_uids == {"uid-1", "uid-2", "uid-3"}

    def test_to_prompt_section_excludes_entity_uids(self):
        """Entity UIDs are internal metadata, not included in prompt output."""
        memory = WorkingMemory()
        memory.discovered_entity_uids.add("some-uid")
        memory.code_snippets.append("[Test]\nsome code")
        section = memory.to_prompt_section()
        assert "some-uid" not in section
        assert "some code" in section
