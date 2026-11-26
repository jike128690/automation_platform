# -*- coding: utf-8 -*-
"""历史数据管理服务单测（T13.1 媒体过期清理 / T13.2 批次删除）。

验收标准（《数据库开发.md》WBS / LDM 确认项 4）：
- T13.1：过期文件被删、库记录保留、is_media_cleaned 置 1；
- T13.2：删除批次后结果/日志级联消失；磁盘文件同步清理。
"""
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.engine import create_app_engine
from app.db.migration import init_db
from app.db.repositories.case_repo import load_tree
from app.db.seed import seed_db
from app.db.services.batch_recorder import BatchRecorder
from app.db.services.history_service import cleanup_expired_media, delete_batches


@pytest.fixture()
def db(tmp_path):
    engine = create_app_engine(tmp_path / "history_svc.db")
    init_db(engine)
    seed_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def media_dir(tmp_path):
    path = tmp_path / "media"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture()
def tree(db):
    return load_tree(db)


def _checked_pairs(tree):
    return [(m, c) for m in tree for c in m.cases if c.default_checked]


def _run_batch(db, tree):
    pairs = _checked_pairs(tree)
    recorder = BatchRecorder(
        db,
        ",".join(dict.fromkeys(m.module_name for m, _ in pairs)),
        queue=pairs,
    )
    for module, case in pairs:
        recorder.on_case_status(case.case_id, "running")
        recorder.on_case_status(case.case_id, "passed")
    recorder.on_batch_finished(False)
    return recorder


def _attach_media(db, recorder, code, media_dir: Path, age_days: int):
    """给指定用例结果挂截图/录像文件并回填过期时间。"""
    screenshot = media_dir / f"{code}.png"
    video = media_dir / f"{code}.webm"
    screenshot.write_bytes(b"fake-png")
    video.write_bytes(b"fake-video")

    recorder.update_case_media(code, screenshot_path=str(screenshot), video_path=str(video))

    old_time = (datetime.now() - timedelta(days=age_days)).strftime("%Y-%m-%d %H:%M:%S.%f")
    with Session(db) as s:
        s.execute(
            text("UPDATE tb_batch_case_result SET end_time = :t "
                 "WHERE batch_id = :bid AND queue_order = 1"),
            {"t": old_time, "bid": recorder.batch_id},
        )
        s.commit()


# ---------------------------------------------------------------- T13.1 媒体清理

def test_expired_media_files_deleted_records_kept(db, tree, media_dir):
    """验收：过期文件被删、库记录保留、状态位置 1（确认项 4）。"""
    recorder = _run_batch(db, tree)
    code = _checked_pairs(tree)[0][1].case_id
    _attach_media(db, recorder, code, media_dir, age_days=10)  # 超过保留期 5 天

    result = cleanup_expired_media(db, media_retention_days=5)

    assert result["files_deleted"] == 2           # 截图 + 录像均被物理删除
    assert not (media_dir / f"{code}.png").exists()
    assert not (media_dir / f"{code}.webm").exists()

    with Session(db) as s:
        row = s.execute(
            text("SELECT is_media_cleaned, screenshot_path, video_path, exec_status "
                 "FROM tb_batch_case_result WHERE batch_id = :bid AND queue_order = 1"),
            {"bid": recorder.batch_id},
        ).one()
        assert row[0] == 1                        # 状态位置 1（确认项 4）
        assert row[1] is None and row[2] is None  # 路径清空（防重复扫描）
        assert row[3] == "PASSED"                 # 执行记录保留

    # 批次与日志记录保留（确认项 4：仅清理硬盘文件）
    with Session(db) as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM tb_execution_batch"
        )).scalar_one() == 1
        assert s.execute(text(
            "SELECT COUNT(*) FROM tb_batch_case_result"
        )).scalar_one() == 6


def test_fresh_media_not_cleaned(db, tree, media_dir):
    """未过保留期的文件不动，is_media_cleaned 保持 0。"""
    recorder = _run_batch(db, tree)
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]
    code = pairs[0][1].case_id
    _attach_media(db, recorder, code, media_dir, age_days=1)  # 1 天前 < 保留期 5 天

    result = cleanup_expired_media(db, media_retention_days=5)
    assert result["files_deleted"] == 0
    assert result["rows_flagged"] == 0
    assert (media_dir / f"{code}.png").exists()

    with Session(db) as s:
        flagged = s.execute(text(
            "SELECT COUNT(*) FROM tb_batch_case_result WHERE is_media_cleaned = 1"
        )).scalar_one()
    assert flagged == 0


def test_retention_forever_skips_cleanup(db, tree, media_dir):
    """media_retention_days = -1（永久保留）：跳过清理。"""
    recorder = _run_batch(db, tree)
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]
    code = pairs[0][1].case_id
    _attach_media(db, recorder, code, media_dir, age_days=100)

    result = cleanup_expired_media(db, media_retention_days=-1)
    assert result == {"checked": 0, "files_deleted": 0, "rows_flagged": 0}
    assert (media_dir / f"{code}.png").exists()


def test_cleanup_idempotent_second_run_noop(db, tree, media_dir):
    recorder = _run_batch(db, tree)
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]
    code = pairs[0][1].case_id
    _attach_media(db, recorder, code, media_dir, age_days=10)

    cleanup_expired_media(db, media_retention_days=5)
    second = cleanup_expired_media(db, media_retention_days=5)
    assert second["files_deleted"] == 0   # 已置位行不再触发


# ---------------------------------------------------------------- T13.2 批次删除

def test_delete_batch_cascades_and_removes_media(db, tree, media_dir):
    """验收：删除批次后结果/日志级联消失；磁盘文件同步清理。"""
    recorder = _run_batch(db, tree)
    pairs = [(m, c) for m in tree for c in m.cases if c.default_checked]
    code = pairs[0][1].case_id
    _attach_media(db, recorder, code, media_dir, age_days=0)

    # 删除前：结果 6 条、日志若干
    with Session(db) as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM tb_batch_case_result"
        )).scalar_one() == 6
        log_count = s.execute(text(
            "SELECT COUNT(*) FROM tb_execution_log"
        )).scalar_one()

    result = delete_batches(db, [recorder.batch_id])
    assert result["batches_deleted"] == 1
    assert result["media_deleted"] == 2
    assert not (media_dir / f"{code}.png").exists()
    assert not (media_dir / f"{code}.webm").exists()

    with Session(db) as s:
        assert s.execute(text(
            "SELECT COUNT(*) FROM tb_execution_batch"
        )).scalar_one() == 0
        assert s.execute(text(
            "SELECT COUNT(*) FROM tb_batch_case_result"
        )).scalar_one() == 0
        assert s.execute(text(
            "SELECT COUNT(*) FROM tb_execution_log"
        )).scalar_one() == 0


def test_delete_batch_only_removes_target(db, tree):
    """多批次场景：仅删除指定批次，其余批次及数据保留。"""
    recorder1 = _run_batch(db, tree)
    recorder2 = _run_batch(db, tree)

    result = delete_batches(db, [recorder1.batch_id])
    assert result["batches_deleted"] == 1

    with Session(db) as s:
        remaining = s.execute(text(
            "SELECT batch_id FROM tb_execution_batch"
        )).scalars().all()
    assert remaining == [recorder2.batch_id]


def test_delete_nonexistent_batch_noop(db):
    assert delete_batches(db, ["no-such-uuid"]) == {
        "batches_deleted": 0, "media_deleted": 0,
    }
