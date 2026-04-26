# tests/wiki/test_suggested_questions.py
"""Unit tests for SuggestedQuestionsGenerator."""

from wiki.suggested_questions import SuggestedQuestionsGenerator, PageContext


class TestSuggestedQuestionsGenerator:
    def test_generates_questions_for_hub(self):
        gen = SuggestedQuestionsGenerator()
        ctx = PageContext(
            entity_name="UserService",
            domain="用户管理",
            callers=["OrderController", "AuthService", "AdminPanel"],
            callees=["UserDAO", "CacheService"],
            cross_domain_callers=["OrderController"],
        )
        questions = gen.generate(ctx)
        assert len(questions) >= 3
        assert any("UserService" in q for q in questions)

    def test_generates_questions_for_cross_domain(self):
        gen = SuggestedQuestionsGenerator()
        ctx = PageContext(
            entity_name="CacheService",
            domain="基础设施",
            callers=["UserService", "OrderService", "PaymentService"],
            callees=["RedisClient"],
            cross_domain_callers=["UserService", "OrderService", "PaymentService"],
        )
        questions = gen.generate(ctx)
        assert any("跨域" in q or "领域" in q for q in questions)

    def test_generates_questions_for_leaf(self):
        gen = SuggestedQuestionsGenerator()
        ctx = PageContext(
            entity_name="UserDTO",
            domain="用户管理",
            callers=[],
            callees=[],
            cross_domain_callers=[],
        )
        questions = gen.generate(ctx)
        assert len(questions) >= 1

    def test_question_count_limit(self):
        gen = SuggestedQuestionsGenerator(max_questions=3)
        ctx = PageContext(
            entity_name="BigService",
            domain="Domain",
            callers=[f"Caller{i}" for i in range(20)],
            callees=[f"Callee{i}" for i in range(10)],
            cross_domain_callers=[f"XCaller{i}" for i in range(5)],
        )
        questions = gen.generate(ctx)
        assert len(questions) <= 3

    def test_empty_context(self):
        gen = SuggestedQuestionsGenerator()
        ctx = PageContext(
            entity_name="Unknown",
            domain="",
            callers=[],
            callees=[],
            cross_domain_callers=[],
        )
        questions = gen.generate(ctx)
        assert isinstance(questions, list)
        assert len(questions) >= 1

    def test_no_duplicate_questions(self):
        gen = SuggestedQuestionsGenerator()
        ctx = PageContext(
            entity_name="Service",
            domain="Domain",
            callers=["A", "B", "C"],
            callees=["X", "Y"],
            cross_domain_callers=["A"],
        )
        questions = gen.generate(ctx)
        assert len(questions) == len(set(questions))

    def test_all_questions_contain_entity_name(self):
        gen = SuggestedQuestionsGenerator()
        ctx = PageContext(
            entity_name="SpecificName",
            domain="D",
            callers=["C1", "C2", "C3"],
            callees=["E1"],
            cross_domain_callers=[],
        )
        questions = gen.generate(ctx)
        for q in questions:
            assert "SpecificName" in q


    def test_negative_max_questions_returns_empty(self):
        gen = SuggestedQuestionsGenerator(max_questions=-1)
        ctx = PageContext(
            entity_name="Foo",
            domain="D",
            callers=["A", "B", "C"],
            callees=["X"],
            cross_domain_callers=["A"],
        )
        questions = gen.generate(ctx)
        assert questions == []

    def test_zero_max_questions_returns_empty(self):
        gen = SuggestedQuestionsGenerator(max_questions=0)
        ctx = PageContext(
            entity_name="Foo",
            domain="D",
            callers=["A", "B", "C"],
            callees=["X"],
            cross_domain_callers=[],
        )
        questions = gen.generate(ctx)
        assert questions == []


class TestPageContext:
    def test_dataclass_fields(self):
        ctx = PageContext(
            entity_name="Test",
            domain="D",
            callers=["A"],
            callees=["B"],
            cross_domain_callers=["A"],
        )
        assert ctx.entity_name == "Test"
        assert ctx.domain == "D"
        assert len(ctx.callers) == 1

    def test_defaults(self):
        ctx = PageContext(entity_name="Test", domain="D")
        assert ctx.callers == []
        assert ctx.callees == []
        assert ctx.cross_domain_callers == []
