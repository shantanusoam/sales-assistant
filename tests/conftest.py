import pytest


@pytest.fixture
def tmp_sqlite_url(tmp_path):
    return f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
