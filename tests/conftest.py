"""
Pytest configuration and global fixtures.
"""

import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from verboisy.storage.sqlite import DatabaseManager
from verboisy.utils.config import settings

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_html_fixture(name: str) -> str:
    return (FIXTURES_DIR / "pages" / name).read_text(encoding="utf-8")


def load_json_fixture(name: str) -> list | dict:
    return json.loads((FIXTURES_DIR / "expected" / name).read_text(encoding="utf-8"))


@pytest.fixture
async def test_db(tmp_path: pytest.TempPathFactory) -> AsyncGenerator[DatabaseManager, None]:
    """Provides an isolated database for tests."""
    # Use a temporary file for the sqlite DB
    db_file = tmp_path / "test_verboisy.db"  # type: ignore
    settings.sqlite_db_path = str(db_file)

    db_manager = DatabaseManager(db_path=str(db_file))
    await db_manager.connect()

    yield db_manager

    await db_manager.close()
