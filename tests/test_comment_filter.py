"""Tests for comment classification and filtering."""
import pytest
from indexer.comment_filter import CommentFilter, CommentTier


@pytest.fixture
def cf():
    return CommentFilter()


def test_license_detected(cf):
    text = "Copyright 2026 Company Inc. Licensed under the Apache License, Version 2.0"
    assert cf.classify(text) == CommentTier.NEVER


def test_trivial_comment(cf):
    assert cf.classify("increment i") == CommentTier.NEVER
    assert cf.classify("return result") == CommentTier.NEVER


def test_commented_out_code(cf):
    code = "if (user != null) { return user.getName(); }"
    assert cf.classify(code) == CommentTier.NEVER


def test_meaningful_block_comment(cf):
    text = "This service handles cross-border transaction settlement flows using the SWIFT network"
    tier = cf.classify(text)
    assert tier in (CommentTier.BLOCK_COMMENT, CommentTier.FILE_HEADER)


def test_short_comment_is_never(cf):
    assert cf.classify("ok") == CommentTier.NEVER
    assert cf.classify("") == CommentTier.NEVER
