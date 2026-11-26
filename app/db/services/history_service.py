# -*- coding: utf-8 -*-
"""历史数据管理服务（T13.1 媒体过期清理 / T13.2 历史批次删除）。

设计依据（《数据库开发.md》4.4 / LDM 确认项 2/4 / 第 5 节策略 2）：
- 确认项 4："保留近 N 天"仅清理硬盘上的截图与录像文件，数据库中的
  批次、结果及日志记录长期保留；清理后将 is_media_cleaned 置 1；
- media_retention_days = -1 表示永久保留（跳过清理）；
- 确认项 2/软删除：媒体清理不触碰 tb_test_case（用例行永久保留）；
- T13.2：报告页删除历史批次 → 物理删除批次行（结果/日志由外键
  ON DELETE CASCADE 级联清理，engine 层 foreign_keys=ON 已保证），
  并同步删除本地截图/录像文件，释放磁盘空间。

文件时效判定（确认项 4 原文按记录 created_at 判定）：
- 结果行无 created_at，取 end_time，缺省回退 start_time（LDM 2.8）；
- 两者皆空（从未执行的 WAITING 行）视为"新建"不清理。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.db.models import BatchCaseResult, ExecutionBatch

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- T13.1 媒体清理

def cleanup_expired_media(engine, media_retention_days: int,
                          now: datetime | None = None) -> dict[str, int]:
    """按保留天数清理过期截图/录像文件（记录保留，状态位置 1）。

    Args:
        engine: SQLAlchemy 引擎。
        media_retention_days: 配置表 media_retention_days；-1 表示永久保留。
        now: 当前时间（测试注入用；缺省取本地当前时间）。

    Returns:
        {"checked": 检查行数, "files_deleted": 删除文件数,
         "rows_flagged": 置位行数}。
    """
    if media_retention_days == -1:
        return {"checked": 0, "files_deleted": 0, "rows_flagged": 0}

    now = now or datetime.now()
    cutoff = now - timedelta(days=media_retention_days)
    files_deleted = rows_flagged = 0

    with Session(engine) as s:
        results = s.scalars(
            select(BatchCaseResult).where(BatchCaseResult.is_media_cleaned == 0)
        ).all()

        for result in results:
            reference = _reference_time(result)
            if reference is None or reference >= cutoff:
                continue  # 未到期或缺时间基准：跳过（确认项 4 仅删过期）

            for path in (result.screenshot_path, result.video_path):
                if not path:
                    continue
                try:
                    file = Path(path)
                    if file.is_file():
                        file.unlink()
                        files_deleted += 1
                except OSError as exc:
                    _logger.warning("媒体文件删除失败（保留记录）: %s (%s)", path, exc)

            # 文件删没删得掉都置位：置位表示"清理任务已处理过该行"，
            # 避免不可删除文件反复触发扫描（记录与统计长期保留不受影响）
            result.screenshot_path = None
            result.video_path = None
            result.is_media_cleaned = 1
            rows_flagged += 1

        s.commit()

    return {
        "checked": len(results),
        "files_deleted": files_deleted,
        "rows_flagged": rows_flagged,
    }


def _reference_time(result: BatchCaseResult) -> datetime | None:
    """记录时效基准：end_time 优先，回退 start_time；均空返回 None。"""
    raw = result.end_time or result.start_time
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:23], "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None


# ---------------------------------------------------------------- T13.2 批次删除

def delete_batches(engine, batch_ids: list[str]) -> dict[str, int]:
    """物理删除历史批次：DB 级联清结果/日志 + 磁盘媒体文件同步删除。

    Returns:
        {"batches_deleted": 批次行数, "media_deleted": 删除媒体文件数}。
    """
    if not batch_ids:
        return {"batches_deleted": 0, "media_deleted": 0}

    media_deleted = 0
    with Session(engine) as s:
        # 先收集待删批次的媒体路径（删行后无法回查）
        paths: list[str] = []
        for result in s.scalars(
            select(BatchCaseResult).where(BatchCaseResult.batch_id.in_(batch_ids))
        ):
            paths.extend(p for p in (result.screenshot_path, result.video_path) if p)

        # 物理删除批次行（results/logs 由 ON DELETE CASCADE 级联清理）
        deleted = s.execute(
            delete(ExecutionBatch).where(ExecutionBatch.batch_id.in_(batch_ids))
        ).rowcount
        s.commit()

    for path in paths:
        try:
            file = Path(path)
            if file.is_file():
                file.unlink()
                media_deleted += 1
        except OSError as exc:
            _logger.warning("批次媒体文件删除失败: %s (%s)", path, exc)

    return {"batches_deleted": deleted, "media_deleted": media_deleted}
