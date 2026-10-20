import os
from pathlib import Path

from database import db


def test_database_isolation_env_var_set_and_real_db_untouched():
    assert "SPENDLY_DB" in os.environ

    real_db_path = Path(__file__).resolve().parent.parent / "spendly.db"
    assert os.environ["SPENDLY_DB"] != str(real_db_path)
    assert not real_db_path.exists()


def test_get_db_returns_row_with_foreign_keys_on():
    conn = db.get_db()
    try:
        fk_status = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk_status == 1

        conn.execute("CREATE TABLE t (col TEXT)")
        conn.execute("INSERT INTO t (col) VALUES (?)", ("value",))
        row = conn.execute("SELECT col FROM t").fetchone()
        assert row["col"] == "value"
    finally:
        conn.close()
