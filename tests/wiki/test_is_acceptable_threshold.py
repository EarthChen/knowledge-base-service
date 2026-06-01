from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeQuality:
    coverage: float = 0.5
    citation_density: float = 0.1
    context_gap_count: int = 3


class TestDomainDocIsAcceptable:
    def test_high_quality_accepted(self):
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        quality = FakeQuality(coverage=0.96, citation_density=0.6, context_gap_count=0)
        assert agent.is_acceptable(quality, 0) is True

    def test_iteration_2_moderate_quality_accepted(self):
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        quality = FakeQuality(coverage=0.92, citation_density=0.4, context_gap_count=1)
        assert agent.is_acceptable(quality, 2) is True

    def test_iteration_3_low_quality_rejected(self):
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        quality = FakeQuality(coverage=0.5, citation_density=0.1, context_gap_count=3)
        assert agent.is_acceptable(quality, 3) is False

    def test_iteration_3_minimum_threshold_pass(self):
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        quality = FakeQuality(coverage=0.75, citation_density=0.2, context_gap_count=1)
        assert agent.is_acceptable(quality, 3) is True


class TestTopicDocIsAcceptable:
    def test_iteration_3_low_quality_rejected(self):
        from wiki.agents.topic_doc_agent import TopicDocAgent

        agent = TopicDocAgent.__new__(TopicDocAgent)
        quality = FakeQuality(coverage=0.5, citation_density=0.1, context_gap_count=3)
        assert agent.is_acceptable(quality, 3) is False

    def test_iteration_3_minimum_threshold_pass(self):
        from wiki.agents.topic_doc_agent import TopicDocAgent

        agent = TopicDocAgent.__new__(TopicDocAgent)
        quality = FakeQuality(coverage=0.75, citation_density=0.2, context_gap_count=1)
        assert agent.is_acceptable(quality, 3) is True
