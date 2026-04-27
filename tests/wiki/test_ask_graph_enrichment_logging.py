import inspect

from wiki.ask import WikiAskService


def test_graph_enrichment_failure_is_logged():
    """Graph enrichment failure should log a warning, not silently pass."""
    source = inspect.getsource(WikiAskService.ask_stream)
    assert "except Exception:\n                pass" not in source, (
        "GraphEnhancedContextCollector failure is silently swallowed"
    )
