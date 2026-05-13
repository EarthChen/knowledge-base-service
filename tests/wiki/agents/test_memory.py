class TestMemory:
    def test_add_and_retrieve(self):
        from wiki.agents.memory import Memory

        m = Memory()
        m.add("snippets", "code A")
        m.add("snippets", "code B")
        m.add("chains", "A -> B")

        assert len(m.entries["snippets"]) == 2
        assert len(m.entries["chains"]) == 1

    def test_total_chars(self):
        from wiki.agents.memory import Memory

        m = Memory()
        m.add("data", "hello")
        m.add("data", "world")
        assert m.total_chars() == 10

    def test_enforce_limit_trims(self):
        from wiki.agents.memory import Memory

        m = Memory(max_total_chars=20)
        m.add("data", "a" * 15)
        m.add("data", "b" * 10)
        m.enforce_limit()
        assert m.total_chars() <= 20

    def test_merge_combines_entries(self):
        from wiki.agents.memory import Memory

        m1 = Memory()
        m1.add("snippets", "A")
        m2 = Memory()
        m2.add("snippets", "B")
        m2.add("chains", "X")

        m1.merge(m2)
        assert len(m1.entries["snippets"]) == 2
        assert len(m1.entries["chains"]) == 1

    def test_empty_memory_total_chars_zero(self):
        from wiki.agents.memory import Memory

        m = Memory()
        assert m.total_chars() == 0
