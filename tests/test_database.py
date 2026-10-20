import os
from pathlib import Path


def test_database_isolation_env_var_set_and_real_db_untouched():
    assert "SPENDLY_DB" in os.environ

    real_db_path = Path(__file__).resolve().parent.parent / "spendly.db"
    assert os.environ["SPENDLY_DB"] != str(real_db_path)
    assert not real_db_path.exists()
