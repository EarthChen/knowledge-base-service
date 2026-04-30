"""Tests for LangChain-based prompt management."""


def test_versioned_prompt_attaches_metadata():
    from langchain_core.prompts import ChatPromptTemplate
    from wiki.prompts import versioned_prompt

    template = ChatPromptTemplate.from_messages([
        ("system", "You are helpful."),
        ("human", "Hello {name}"),
    ])
    vp = versioned_prompt("test_prompt", template, version="2.0")
    assert vp.metadata["name"] == "test_prompt"
    assert vp.metadata["version"] == "2.0"


def test_prompt_hash_changes_with_version():
    from langchain_core.prompts import ChatPromptTemplate
    from wiki.prompts import versioned_prompt, prompt_hash

    template = ChatPromptTemplate.from_messages([
        ("human", "Classify: {modules}"),
    ])
    v1 = versioned_prompt("classify", template, version="1.0")
    v2 = versioned_prompt("classify", template, version="2.0")

    h1 = prompt_hash(v1, modules="[mod_a, mod_b]")
    h2 = prompt_hash(v2, modules="[mod_a, mod_b]")
    assert h1 != h2


def test_prompt_hash_changes_with_input():
    from langchain_core.prompts import ChatPromptTemplate
    from wiki.prompts import versioned_prompt, prompt_hash

    template = ChatPromptTemplate.from_messages([
        ("human", "Classify: {modules}"),
    ])
    vp = versioned_prompt("classify", template, version="1.0")

    h1 = prompt_hash(vp, modules="[mod_a]")
    h2 = prompt_hash(vp, modules="[mod_a, mod_b]")
    assert h1 != h2


def test_domain_classify_prompt_defined():
    from wiki.prompts import DOMAIN_CLASSIFY_PROMPT
    assert DOMAIN_CLASSIFY_PROMPT is not None
    assert DOMAIN_CLASSIFY_PROMPT.metadata["name"] == "domain_classify"
