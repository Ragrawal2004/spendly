import os
import tempfile

os.environ.setdefault("SPENDLY_DB", tempfile.mkstemp(suffix=".db")[1])

import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SPENDLY_DB", str(db_path))
    yield db_path
