import os
import tempfile

os.environ.setdefault("SPENDLY_DB", tempfile.mkstemp(suffix=".db")[1])
os.environ.setdefault("SPENDLY_SECRET_KEY", "test-only-secret-key")

import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SPENDLY_DB", str(db_path))
    yield db_path


@pytest.fixture
def client(isolated_db):
    import app as app_module
    from database.db import init_db

    init_db()
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()
