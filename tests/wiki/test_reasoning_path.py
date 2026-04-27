from wiki.reasoning_path import (
    ReasoningPath,
    ReasoningStage,
    extract_entities_in_answer,
    merge_reasoning_paths,
)


def test_reasoning_path_to_dict():
    p = ReasoningPath(
        stages=[
            ReasoningStage(
                stage_name="hybrid_search", retriever="vector", entity_hits=["Foo", "Bar"], score=0.9
            ),
            ReasoningStage(stage_name="graph_expand", retriever="graph", entity_hits=["Baz"]),
        ],
        answer_entities=["Foo", "Baz"],
    )
    d = p.to_dict()
    assert len(d["stages"]) == 2
    assert d["stages"][0]["retriever"] == "vector"
    assert d["answer_entities"] == ["Foo", "Baz"]


def test_extract_entities_in_answer():
    answer = "The AuthService delegates to TokenManager for JWT validation."
    names = ["AuthService", "TokenManager", "UserRepo", "JWT"]
    found = extract_entities_in_answer(answer, names)
    assert "AuthService" in found
    assert "TokenManager" in found


def test_extract_empty():
    assert extract_entities_in_answer("", ["A"]) == []
    assert extract_entities_in_answer("text", []) == []


def test_merge_reasoning_paths():
    p1 = ReasoningPath(
        stages=[ReasoningStage("s1", "vector", ["A"])],
        answer_entities=["A"],
    )
    p2 = ReasoningPath(
        stages=[ReasoningStage("s2", "graph", ["B"])],
        answer_entities=["A", "B"],
    )
    merged = merge_reasoning_paths(p1, p2)
    assert len(merged.stages) == 2
    assert merged.answer_entities == ["A", "B"]
