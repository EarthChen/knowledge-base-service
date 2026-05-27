from __future__ import annotations


class TestSplitGluedSegment:
    """Tests for F5: dictionary-based glued segment splitting."""

    def test_relationfamily_split(self):
        from wiki.path_conventions import _split_glued_segment

        assert _split_glued_segment("relationfamily") == ["relation", "family"]

    def test_managementhandler_split(self):
        from wiki.path_conventions import _split_glued_segment

        assert _split_glued_segment("managementhandler") == ["management", "handler"]

    def test_paymentsearch_split(self):
        from wiki.path_conventions import _split_glued_segment

        assert _split_glued_segment("paymentsearch") == ["payment", "search"]

    def test_getservice_no_split(self):
        from wiki.path_conventions import _split_glued_segment

        # "get" is only 3 chars, below min_split_word=4 threshold
        assert _split_glued_segment("getservice") == ["getservice"]

    def test_short_segment_skip(self):
        from wiki.path_conventions import _split_glued_segment

        # < 8 chars, don't attempt splitting
        assert _split_glued_segment("task") == ["task"]

    def test_known_word_no_split(self):
        from wiki.path_conventions import _split_glued_segment

        # Already a known word in dictionary
        assert _split_glued_segment("management") == ["management"]

    def test_non_alpha_skip(self):
        from wiki.path_conventions import _split_glued_segment

        # Contains hyphen, not pure alpha
        assert _split_glued_segment("user-auth") == ["user-auth"]

    def test_7char_skip(self):
        from wiki.path_conventions import _split_glued_segment

        # < 8 chars, don't attempt splitting
        assert _split_glued_segment("service") == ["service"]


class TestDesegmentGluedSlug:

    def test_full_slug_desegment(self):
        from wiki.path_conventions import _desegment_glued_slug

        assert _desegment_glued_slug("relationfamily-member-service") == "relation-family-member-service"

    def test_no_change_needed(self):
        from wiki.path_conventions import _desegment_glued_slug

        assert _desegment_glued_slug("user-authentication") == "user-authentication"

    def test_multiple_glued_segments(self):
        from wiki.path_conventions import _desegment_glued_slug

        result = _desegment_glued_slug("paymentsearch-handler")
        assert result == "payment-search-handler"

    def test_single_segment_no_change(self):
        from wiki.path_conventions import _desegment_glued_slug

        assert _desegment_glued_slug("authentication") == "authentication"
