# -*- coding: utf-8 -*-
"""pytest 共享 fixture：QT offscreen 平台 + 临时种子库（T10.3 DB fixture）。

widget/主窗口测试注入 db_engine（tmp_path + init_db + 真实业务种子），
替代直接引用 demo_cases 内存数据；既有引擎类测试仍可自由选择数据源。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from app.db.engine import create_app_engine
from app.db.migration import init_db
from app.db.seed import seed_db


@pytest.fixture()
def db_engine(tmp_path):
    """临时种子库：建表 + 真实业务种子，测试结束销毁（不触碰生产 data/automation.db）。"""
    engine = create_app_engine(tmp_path / "test_tree.db")
    init_db(engine)
    seed_db(engine)
    yield engine
    engine.dispose()
