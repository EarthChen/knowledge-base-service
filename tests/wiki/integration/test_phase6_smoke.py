# tests/wiki/integration/test_phase6_smoke.py
"""Phase 6 integration smoke tests — import verification and basic wiring."""


class TestPhase6Imports:
    def test_coverage_analyzer_importable(self):
        from wiki import WikiCoverageAnalyzer, CoverageReport

        assert WikiCoverageAnalyzer is not None
        assert CoverageReport is not None

    def test_suggested_questions_importable(self):
        from wiki import SuggestedQuestionsGenerator, PageContext

        assert SuggestedQuestionsGenerator is not None
        assert PageContext is not None

    def test_all_phase6_in_public_api(self):
        import wiki

        phase6_names = [
            "WikiCoverageAnalyzer",
            "CoverageReport",
            "SuggestedQuestionsGenerator",
            "PageContext",
        ]
        for name in phase6_names:
            assert name in wiki.__all__, f"{name} missing from wiki.__all__"
            assert hasattr(wiki, name), f"{name} not accessible on wiki module"


class TestPhase6BasicWiring:
    def test_coverage_report_to_dict(self):
        from wiki import CoverageReport

        report = CoverageReport(
            total_modules=10,
            covered_modules=8,
            stale_pages=[],
            knowledge_gaps=[],
        )
        d = report.to_dict()
        assert d["coverage_percentage"] == 80.0
        assert d["stale_page_count"] == 0
        assert d["knowledge_gap_count"] == 0

    def test_suggested_questions_generator_basic(self):
        from wiki import SuggestedQuestionsGenerator, PageContext

        gen = SuggestedQuestionsGenerator(max_questions=3)
        ctx = PageContext(entity_name="TestService", domain="TestDomain")
        questions = gen.generate(ctx)
        assert isinstance(questions, list)
        assert len(questions) >= 1
        assert len(questions) <= 3
