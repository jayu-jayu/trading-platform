"""
Shared pytest fixtures. Uses a temporary file-based SQLite database (not
Postgres) so this test suite runs anywhere with no external service
required — production still uses Postgres via DATABASE_URL, this is
purely for fast, portable testing.
"""
import os
import sys
import subprocess
import tempfile
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import every model module up front, exactly like app/main.py does — a
# model with a ForeignKey to another table (e.g. shadow_ledger -> signal_history)
# only resolves correctly once ALL model modules have been imported at least
# once, regardless of which one a given test actually uses.
from app.models import signal, portfolio, position, price_cache, backtest, shadow_ledger  # noqa: F401,E402


@pytest.fixture(scope="session", autouse=True)
def _test_database_url():
    """Points DATABASE_URL at a fresh temp SQLite file and runs every
    migration against it before any test executes."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)  # alembic/sqlalchemy create it fresh
    db_url = f"sqlite+aiosqlite:///{path}"
    os.environ["DATABASE_URL"] = db_url

    repo_root = os.path.join(os.path.dirname(__file__), "..")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=repo_root, env={**os.environ, "DATABASE_URL": db_url}, check=True,
    )

    yield db_url

    if os.path.exists(path):
        os.remove(path)


@pytest_asyncio.fixture
async def db_session():
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        yield session
