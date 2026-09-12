"""
Pytest configuration and global fixtures.
"""

import pytest
import asyncio
from typing import AsyncGenerator

from verboisy.storage.sqlite import DatabaseManager
from verboisy.utils.config import settings


@pytest.fixture(scope="session")
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop, None]:
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db(tmp_path: pytest.TempPathFactory) -> AsyncGenerator[DatabaseManager, None]:
    """Provides an isolated database for tests."""
    # Use a temporary file for the sqlite DB
    db_file = tmp_path / "test_verboisy.db" # type: ignore
    settings.sqlite_db_path = str(db_file)

    db_manager = DatabaseManager(db_path=str(db_file))
    await db_manager.connect()

    yield db_manager

    await db_manager.close()
