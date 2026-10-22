import os
from contextlib import closing

_TEST_URL = os.environ.get("SPENDLY_TEST_DATABASE_URL", "")
os.environ["DATABASE_URL"] = _TEST_URL
os.environ.setdefault("SPENDLY_SECRET_KEY", "test-only-secret-key")

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

_MISSING_TEST_URL_MESSAGE = (
    "SPENDLY_TEST_DATABASE_URL must be set, "
    "e.g. SPENDLY_TEST_DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/spendly_test"
)
_WRONG_DBNAME_MESSAGE = (
    "SPENDLY_TEST_DATABASE_URL must point at a database named spendly_test; "
    "refusing to run"
)
_UNREACHABLE_MESSAGE = (
    "Cannot connect to the spendly_test database. Start the server with "
    "`docker start spendly-pg` and create the database once with "
    '`docker exec spendly-pg psql -U postgres -d postgres -c "CREATE DATABASE spendly_test"`'
)


def pytest_sessionstart(session):
    if not _TEST_URL:
        pytest.exit(_MISSING_TEST_URL_MESSAGE, returncode=1)

    try:
        dbname = conninfo_to_dict(_TEST_URL).get("dbname")
    except psycopg.ProgrammingError:
        dbname = None
    if dbname != "spendly_test":
        pytest.exit(_WRONG_DBNAME_MESSAGE, returncode=1)

    try:
        psycopg.connect(_TEST_URL, connect_timeout=5).close()
    except psycopg.OperationalError:
        pytest.exit(_UNREACHABLE_MESSAGE, returncode=1)


@pytest.fixture(autouse=True)
def isolated_db():
    from database import db

    with closing(db.get_db()) as conn:
        conn.execute("SET lock_timeout = '5s'")
        conn.execute("DROP TABLE IF EXISTS expenses, users CASCADE")
    yield


@pytest.fixture
def client(isolated_db):
    import app as app_module
    from database.db import init_db

    init_db()
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()
