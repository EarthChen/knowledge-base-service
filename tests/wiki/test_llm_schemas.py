from __future__ import annotations


class TestLLMSchemas:
    """Tests for wiki/llm_schemas.py Pydantic models."""

    def test_topic_plan_output_schema(self):
        from wiki.llm_schemas import TopicPlanOutput

        schema = TopicPlanOutput.model_json_schema()
        assert "should_split" in schema["properties"]
        assert "topics" in schema["properties"]

    def test_domain_merge_output_schema(self):
        from wiki.llm_schemas import DomainMergeOutput

        schema = DomainMergeOutput.model_json_schema()
        assert "merge_groups" in schema["properties"]

    def test_domain_review_output_schema(self):
        from wiki.llm_schemas import DomainReviewOutput

        schema = DomainReviewOutput.model_json_schema()
        assert "overall_quality" in schema["properties"]
        assert "issues" in schema["properties"]

    def test_wiki_page_output_schema_exists(self):
        from wiki.structured_output import WikiPageOutput

        schema = WikiPageOutput.model_json_schema()
        assert "title" in schema["properties"]
        assert "sections" in schema["properties"]

    def test_topic_plan_output_validates(self):
        from wiki.llm_schemas import TopicPlanOutput

        data = {
            "should_split": True,
            "topics": [
                {"title": "Auth", "slug": "auth", "module_keys": ["UserService"]},
            ],
            "reasoning": "Large domain",
        }
        output = TopicPlanOutput.model_validate(data)
        assert output.should_split is True
        assert len(output.topics) == 1

    def test_domain_merge_output_validates(self):
        from wiki.llm_schemas import DomainMergeOutput

        data = {"merge_groups": [["auth", "login"]]}
        output = DomainMergeOutput.model_validate(data)
        assert len(output.merge_groups) == 1
