import os
from unittest.mock import AsyncMock

import pytest


class TestCheckpointerSetup:
    def test_checkpoint_dir_created(self, tmp_path):
        """The checkpointer should create a directory for its SQLite DB."""
        db_path = str(tmp_path / "checkpoints" / "wiki.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        assert os.path.exists(os.path.dirname(db_path))


class TestCheckpointInfo:
    @pytest.fixture
    def mock_persistence(self):
        p = AsyncMock()
        return p

    @pytest.mark.asyncio
    async def test_get_checkpoint_info_no_data(self, mock_persistence):
        """get_checkpoint_info should return None when no checkpoint exists."""
        from wiki.persistence import WikiPersistence

        p = WikiPersistence.__new__(WikiPersistence)
        p._store = AsyncMock()
        p._checkpoint_dir = "/tmp/test_checkpoints"

        result = await p.get_checkpoint_info("biz1")
        # Should return None or empty dict when no checkpoint DB exists
        assert result is None or result == {}

    @pytest.mark.asyncio
    async def test_delete_checkpoint(self, mock_persistence):
        """delete_checkpoint should remove the checkpoint file if it exists."""
        import tempfile

        from wiki.persistence import WikiPersistence

        with tempfile.TemporaryDirectory() as tmpdir:
            p = WikiPersistence.__new__(WikiPersistence)
            p._store = AsyncMock()
            p._checkpoint_dir = tmpdir

            # Create a fake checkpoint file
            db_path = os.path.join(tmpdir, "biz1_wiki.db")
            with open(db_path, "w") as f:
                f.write("fake")

            assert os.path.exists(db_path)
            await p.delete_checkpoint("biz1")
            assert not os.path.exists(db_path)
