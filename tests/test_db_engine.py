"""数据库引擎 PRAGMA 初始化单测（T9.2）。"""
from pathlib import Path

import pytest

from app.db.engine import DB_PATH, create_app_engine


def _pragma_value(engine, name: str):
    with engine.connect() as conn:
        return conn.exec_driver_sql(f"PRAGMA {name}").scalar()


@pytest.mark.parametrize(
    ("pragma", "expected"),
    [
        ("journal_mode", "wal"),
        ("busy_timeout", 5000),
        ("foreign_keys", 1),
    ],
)
def test_pragmas_enforced_on_connect(tmp_path, pragma, expected):
    engine = create_app_engine(tmp_path / "test.db")
    try:
        assert _pragma_value(engine, pragma) == expected
    finally:
        engine.dispose()


def test_db_path_located_in_project_data_dir():
    assert DB_PATH.parent == Path(__file__).resolve().parent.parent / "data"
    assert DB_PATH.name == "automation.db"


def test_engine_creates_missing_parent_dir(tmp_path):
    engine = create_app_engine(tmp_path / "nested" / "test.db")
    try:
        assert (tmp_path / "nested").is_dir()
    finally:
        engine.dispose()
