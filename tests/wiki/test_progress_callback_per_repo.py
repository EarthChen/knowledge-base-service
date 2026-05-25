# tests/wiki/test_progress_callback_per_repo.py
import ast
import inspect
import textwrap


def test_generate_passes_progress_callback():
    """Verify generate_business_wiki passes progress_callback to per-repo generate()."""
    from wiki.business_pipeline_runner import BusinessPipelineRunner
    source = textwrap.dedent(inspect.getsource(BusinessPipelineRunner.run))
    tree = ast.parse(source)

    found_generate_call = False
    has_progress_callback = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "_repo_generator":
                found_generate_call = True
                for kw in node.keywords:
                    if kw.arg == "progress_callback":
                        has_progress_callback = True

    assert found_generate_call, "Should find self._repo_generator() call"
    assert has_progress_callback, "self._repo_generator() should receive progress_callback"
