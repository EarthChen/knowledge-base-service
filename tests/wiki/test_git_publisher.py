# tests/wiki/test_git_publisher.py
"""Unit tests for GitPublisher."""

import hashlib
import pytest

from wiki.git_publisher import GitPublisher, PublishResult


class TestDetectChanges:
    def test_new_files_detected_as_added(self):
        pub = GitPublisher(remote_url="https://example.com/wiki.git", branch="main")
        existing: dict[str, str] = {}
        new_files = {"README.md": "# Hello", "domain/page.md": "content"}
        changes = pub.detect_changes(existing, new_files)
        assert set(changes["added"]) == {"README.md", "domain/page.md"}
        assert changes["modified"] == []
        assert changes["deleted"] == []

    def test_modified_files_detected_by_hash(self):
        pub = GitPublisher(remote_url="", branch="main")
        old_hash = hashlib.sha256(b"old content").hexdigest()
        existing = {"a.md": old_hash}
        new_files = {"a.md": "new content"}
        changes = pub.detect_changes(existing, new_files)
        assert "a.md" in changes["modified"]

    def test_unchanged_files_not_in_changes(self):
        pub = GitPublisher(remote_url="", branch="main")
        content = "same content"
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        existing = {"a.md": content_hash}
        new_files = {"a.md": content}
        changes = pub.detect_changes(existing, new_files)
        assert changes["added"] == []
        assert changes["modified"] == []

    def test_deleted_files_detected(self):
        pub = GitPublisher(remote_url="", branch="main")
        existing = {"old.md": "somehash"}
        new_files: dict[str, str] = {}
        changes = pub.detect_changes(existing, new_files)
        assert "old.md" in changes["deleted"]


class TestGenerateCommitMessage:
    def test_includes_file_names(self):
        pub = GitPublisher(remote_url="", branch="main")
        msg = pub.generate_commit_message(
            added=["domain/new.md"],
            modified=["domain/updated.md"],
            deleted=[],
            trigger_info="user-service@abc1234",
        )
        assert "docs(wiki):" in msg
        assert "new" in msg

    def test_full_regeneration_message(self):
        pub = GitPublisher(remote_url="", branch="main")
        msg = pub.generate_commit_message(
            added=[], modified=[], deleted=[],
            trigger_info="full-regeneration",
            is_full=True,
        )
        assert "full regeneration" in msg.lower()

    def test_prefix_customizable(self):
        pub = GitPublisher(
            remote_url="", branch="main",
            commit_message_prefix="docs(kb):",
        )
        msg = pub.generate_commit_message(
            added=["a.md"], modified=[], deleted=[],
        )
        assert msg.startswith("docs(kb):")

    def test_no_changes_message(self):
        pub = GitPublisher(remote_url="", branch="main")
        msg = pub.generate_commit_message(added=[], modified=[], deleted=[])
        assert "no changes" in msg.lower()

    def test_many_files_truncated(self):
        pub = GitPublisher(remote_url="", branch="main")
        added = [f"page{i}.md" for i in range(10)]
        msg = pub.generate_commit_message(added=added, modified=[], deleted=[])
        assert "+5 more" in msg


class TestPublishResult:
    def test_result_dataclass(self):
        result = PublishResult(
            success=True,
            files_added=2,
            files_modified=1,
            files_deleted=0,
            commit_sha="abc123",
        )
        assert result.success
        assert result.files_added == 2
        assert result.commit_sha == "abc123"

    def test_error_result(self):
        result = PublishResult(
            success=False,
            files_added=0,
            files_modified=0,
            files_deleted=0,
            error="Permission denied",
        )
        assert not result.success
        assert "Permission" in (result.error or "")


class TestScanAnnotations:
    def test_finds_annotation_files(self, tmp_path):
        ann_dir = tmp_path / "用户管理"
        ann_dir.mkdir()
        ann_file = ann_dir / "UserController.annotations.md"
        ann_file.write_text("## Custom Notes\nImportant detail.", encoding="utf-8")

        pub = GitPublisher(remote_url="", branch="main")
        annotations = pub.scan_annotations(str(tmp_path))
        assert len(annotations) == 1
        assert "用户管理/UserController" in annotations
        assert "Important detail" in annotations["用户管理/UserController"]

    def test_no_annotation_files(self, tmp_path):
        pub = GitPublisher(remote_url="", branch="main")
        annotations = pub.scan_annotations(str(tmp_path))
        assert annotations == {}

    def test_nested_annotation_files(self, tmp_path):
        nested = tmp_path / "domain" / "sub"
        nested.mkdir(parents=True)
        ann = nested / "Page.annotations.md"
        ann.write_text("Note", encoding="utf-8")
        pub = GitPublisher(remote_url="", branch="main")
        annotations = pub.scan_annotations(str(tmp_path))
        assert "domain/sub/Page" in annotations


class TestPublishNoRemote:
    @pytest.mark.asyncio
    async def test_publish_without_remote_url_fails(self):
        pub = GitPublisher(remote_url="", branch="main")
        result = await pub.publish({"README.md": "# Hi"})
        assert not result.success
        assert "remote_url" in (result.error or "").lower()


class TestAuthUrl:
    def test_https_token_injection(self):
        pub = GitPublisher(
            remote_url="https://github.com/org/wiki.git",
            branch="main",
            git_token="my-token",
        )
        url = pub._auth_url()
        assert "oauth2:my-token@" in url
        assert url.startswith("https://")

    def test_ssh_url_unchanged(self):
        pub = GitPublisher(
            remote_url="git@github.com:org/wiki.git",
            branch="main",
            git_token="my-token",
        )
        url = pub._auth_url()
        assert url == "git@github.com:org/wiki.git"

    def test_no_token_returns_original(self):
        pub = GitPublisher(
            remote_url="https://github.com/org/wiki.git",
            branch="main",
        )
        url = pub._auth_url()
        assert url == "https://github.com/org/wiki.git"
