"""SQLite 引擎与会话工厂（WAL + busy_timeout + foreign_keys 强制生效）。

数据库文件位于项目目录 data/automation.db。
"""
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import scoped_session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DB_DIR = PROJECT_ROOT / "data"
DB_PATH = DB_DIR / "automation.db"

BUSY_TIMEOUT_MS = 5000

def create_app_engine(db_path: Path | None = None) -> Engine:
    """创建 SQLite 引擎；每个新连接强制应用 PRAGMA（LDM 第 3 节）。"""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.as_posix()}")

    # 装饰器：在 engine 的 connect 事件上注册回调函数 _init_pragmas
    @event.listens_for(engine, "connect")
    # connect 事件触发时调用 _init_pragmas，确保每个新连接都应用 PRAGMA
    def _init_pragmas(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    return engine


# 全局默认引擎与会话工厂（工作线程/主线程各自取 Session，scoped_session 按线程隔离）
engine = create_app_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
DbSession = scoped_session(SessionLocal)
