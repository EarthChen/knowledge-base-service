from wiki.ask import ConversationStore as LegacyConversationStore


def test_legacy_store_still_works():
    """Ensure the in-memory store still functions as fallback."""
    store = LegacyConversationStore()
    h = store.create("test-repo")
    assert h.conversation_id
    assert store.get(h.conversation_id) is not None
