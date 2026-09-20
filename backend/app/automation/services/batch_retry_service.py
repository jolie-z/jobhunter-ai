"""批量重试与批量放弃执行失败岗位的服务层实现。

核心职责：
1. 接入现有的标准批量投递编排器 (_deliver_approved_worker)，严格遵守 BOSS->智联->猎聘->51job 平台排序与防风控休眠；
2. 共用 _deliver_worker_lock 互斥锁，rec_ 与 raw_ 串行执行，杜绝并发启动多浏览器；
3. 强引用持有后台任务，批次级 try...finally 确保在途标记 (retrying) 必然释放；
4. 批量放弃严格执行「持久化先行」原则，防止状态机脏读。
"""

import asyncio
import logging
import sqlite3
from typing import Any

from fastapi import HTTPException, status

from app.automation import run_snapshot as _rs
from app.automation.full_auto import RAW_DB_PATH
from app.automation.routes.delivery_router import (
    _deliver_approved_worker,
    _deliver_worker_lock,
)
from app.services import feishu_service

logger = logging.getLogger(__name__)

# 强引用持有后台任务，防止被 CPython GC 提前回收
_BATCH_BG_TASKS: set[asyncio.Task] = set()


def is_batch_busy() -> bool:
    """检查当前是否有投递任务或批量重试正在运行。"""
    return _deliver_worker_lock.locked() or bool(_BATCH_BG_TASKS)


async def batch_retry_failed_jobs_service(job_ids: list[str]) -> dict[str, Any]:
    """批量重试选中的执行失败岗位。

    - 400: job_ids 为空或经在途过滤后无有效项
    - 409: 当前已有投递任务正在执行
    - 200: 成功启动后台批量重试协程
    """
    if not job_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="job_ids 列表不能为空",
        )

    # 409 锁冲突前置拦截
    if is_batch_busy():
        logger.warning("⛔ [batch_retry] 触发 409：当前已有投递或重试任务正在运行中")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前已有投递任务正在执行中，请等待上一批次完成",
        )

    # 过滤空串、同次请求重复项与已经在途重试中的岗位（防重）
    seen_ids: set[str] = set()
    valid_ids: list[str] = []
    ignored_count = 0
    for jid in job_ids:
        cleaned = str(jid or "").strip()
        if not cleaned or not _is_valid_job_id(cleaned):
            ignored_count += 1
            continue
        if cleaned in seen_ids or _rs.is_job_retrying(cleaned):
            ignored_count += 1
            continue
        seen_ids.add(cleaned)
        valid_ids.append(cleaned)

    if not valid_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="所选岗位均已在重试中或无效，无需重复触发",
        )

    feishu_ids = [jid for jid in valid_ids if not jid.startswith("raw_")]
    raw_ids = [jid for jid in valid_ids if jid.startswith("raw_")]

    # 标记在途重试态（带回滚保护）
    marked_ids: list[str] = []
    try:
        for jid in valid_ids:
            _rs.undismiss_job(jid)
            _rs.mark_job_retrying(jid)
            marked_ids.append(jid)
    except Exception as mark_err:
        for mid in marked_ids:
            _rs.unmark_job_retrying(mid)
        logger.error(f"❌ [batch_retry] 标记岗位重试状态异常: {mark_err}")
        raise HTTPException(status_code=500, detail="标记岗位状态异常")

    logger.info(
        f"⚡ [batch_retry] 接收到批量重试请求: 总计={len(valid_ids)}, "
        f"飞书岗={len(feishu_ids)}, raw岗={len(raw_ids)}, 忽略在途/重复={ignored_count}"
    )

    async def _batch_retry_worker(feishu_list: list[str], raw_list: list[str], all_ids: list[str]):
        try:
            async with _deliver_worker_lock:
                # 1. 飞书岗位：统一送入成熟的批量投递编排引擎 (BOSS->智联->猎聘->51job)
                if feishu_list:
                    try:
                        logger.info(f"🚀 [batch_retry_worker] 开始执行 {len(feishu_list)} 个飞书岗位的标准批量编排...")
                        for fid in feishu_list:
                            _rs.remove_delivery_failure(fid)
                            # 🌟 状态补偿平账：确保飞书跟进状态同步为「待投递」，消除放弃与重试并发可能导致的账目不一致
                            try:
                                sync_ok = await asyncio.to_thread(feishu_service.update_feishu_record, fid, {"跟进状态": "待投递"})
                                if not sync_ok:
                                    logger.warning(f"⚠️ [batch_retry_worker] 飞书平账更新返回 False ({fid})")
                            except Exception as sync_e:
                                logger.warning(f"⚠️ [batch_retry_worker] 状态平账写入异常 ({fid}): {sync_e}")
                        await _deliver_approved_worker(feishu_list)
                    except Exception as feishu_ex:
                        logger.error(f"❌ [batch_retry_worker] 飞书段批量投递编排发生异常（隔离不影响 raw 段）: {feishu_ex}", exc_info=True)

                # 2. 本地 raw_ 岗位：在同一互斥锁内依次串行推进流水线
                if raw_list:
                    from app.automation.full_auto import run_single_job_pipeline_async
                    logger.info(f"🚀 [batch_retry_worker] 开始串行执行 {len(raw_list)} 个本地 raw 岗位流水线...")
                    for idx, rid in enumerate(raw_list):
                        try:
                            raw_rowid = str(int(rid.replace("raw_", "")))
                            _rs.remove_delivery_failure(rid)
                            task_id = f"batch_retry_{rid}_{int(asyncio.get_running_loop().time())}_{idx}"
                            await run_single_job_pipeline_async(
                                record_id="",
                                raw_rowid=raw_rowid,
                                pipeline_task_id=task_id,
                            )
                        except Exception as raw_e:
                            logger.warning(f"❌ [batch_retry_worker] raw 岗位 {rid} 执行异常: {raw_e}")
        except Exception as ex:
            logger.error(f"❌ [batch_retry_worker] 批量重试批次发生未捕获异常: {ex}", exc_info=True)
        finally:
            # 提升到锁外层兜底：无论排队拿锁被取消还是执行中中途异常，必然全量释放
            for jid in all_ids:
                try:
                    _rs.unmark_job_retrying(jid)
                except Exception as unmark_e:
                    logger.warning(f"解除岗位重试状态异常 ({jid}): {unmark_e}")
            logger.info("🏁 [batch_retry_worker] 批量重试协程结束，已全量释放 retrying 标记")

    task = asyncio.create_task(_batch_retry_worker(feishu_ids, raw_ids, valid_ids))
    _BATCH_BG_TASKS.add(task)
    task.add_done_callback(_BATCH_BG_TASKS.discard)

    return {
        "status": "success",
        "retried_count": len(feishu_ids),
        "raw_count": len(raw_ids),
        "ignored_count": ignored_count,
        "message": f"已成功启动批量重试：{len(feishu_ids)} 个岗位送入标准编排队列，{len(raw_ids)} 个本地岗位串行重试",
    }


def _is_valid_job_id(jid: str) -> bool:
    """校验岗位 ID 格式合法性（raw 必须带有有效正整数 rowid）。"""
    if not jid:
        return False
    if jid.startswith("raw_"):
        suffix = jid[4:]
        return suffix.isdigit() and int(suffix) > 0
    return True


def _sync_sqlite_dismiss(raw_id_str: str) -> bool:
    """在线程池中执行 SQLite 放弃状态更新，避免阻塞异步事件循环。"""
    try:
        rowid = int(raw_id_str.replace("raw_", ""))
        conn = sqlite3.connect(RAW_DB_PATH)
        try:
            cur = conn.execute("UPDATE raw_jobs SET process_status = '已放弃' WHERE rowid = ?", (rowid,))
            conn.commit()
            return bool(cur.rowcount > 0)
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"⚠️ [batch_dismiss] SQLite 放弃更新异常 ({raw_id_str}): {e}")
        return False


def _sync_sqlite_rollback_dismiss(raw_id_str: str) -> bool:
    """在线程池中执行 SQLite 放弃状态回滚，消除并发重试与放弃打架导致的持久层状态分裂。"""
    try:
        rowid = int(raw_id_str.replace("raw_", ""))
        conn = sqlite3.connect(RAW_DB_PATH)
        try:
            cur = conn.execute("UPDATE raw_jobs SET process_status = '待投递' WHERE rowid = ?", (rowid,))
            conn.commit()
            return bool(cur.rowcount > 0)
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"⚠️ [batch_dismiss] SQLite 放弃状态回滚异常 ({raw_id_str}): {e}")
        return False


async def batch_dismiss_failed_jobs_service(job_ids: list[str]) -> dict[str, Any]:
    """批量放弃执行失败的岗位。

    严格遵循「在途互斥校验」与「持久化先行」原则：
    1. 在途重试中的岗位不可放弃，计入 busy_count；
    2. 飞书/SQLite 持久化成功后二次检查在途状态，才调用 _rs.dismiss_job 剔除内存看板台账；
    3. 持久化失败计入 failed_count，不污染快照。
    """
    if not job_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="job_ids 列表不能为空",
        )

    dismissed_count = 0
    failed_count = 0
    busy_count = 0
    seen_dismiss_ids: set[str] = set()

    for jid in job_ids:
        jid_str = str(jid or "").strip()
        if not jid_str or jid_str in seen_dismiss_ids:
            continue
        seen_dismiss_ids.add(jid_str)

        if not _is_valid_job_id(jid_str):
            logger.warning(f"⚠️ [batch_dismiss] 岗位 ID 格式非法，跳过放弃: {jid_str}")
            failed_count += 1
            continue

        # 首次在途互斥检查
        if _rs.is_job_retrying(jid_str):
            logger.warning(f"⚠️ [batch_dismiss] 岗位 {jid_str} 正在投递/重试中，拦截放弃")
            busy_count += 1
            continue

        is_raw = jid_str.startswith("raw_")
        persisted_ok = False

        try:
            if is_raw:
                persisted_ok = await asyncio.to_thread(_sync_sqlite_dismiss, jid_str)
            else:
                feishu_ok = await asyncio.to_thread(
                    feishu_service.update_feishu_record, jid_str, {"跟进状态": "已放弃投递"}
                )
                persisted_ok = bool(feishu_ok)
        except Exception as persist_err:
            logger.warning(f"⚠️ [batch_dismiss] 持久化放弃状态异常 ({jid_str}): {persist_err}")
            persisted_ok = False

        if persisted_ok:
            # 🌟 二次在途检查（防并发竞态）：防止在异步持久化 await 期间岗位被并发拉起重试
            if _rs.is_job_retrying(jid_str):
                logger.warning(f"⚠️ [batch_dismiss] 岗位 {jid_str} 在持久化期间被拉起重试，放弃中止，补偿回滚持久层状态")
                try:
                    if not is_raw:
                        await asyncio.to_thread(feishu_service.update_feishu_record, jid_str, {"跟进状态": "待投递"})
                    else:
                        await asyncio.to_thread(_sync_sqlite_rollback_dismiss, jid_str)
                except Exception as rb_err:
                    logger.warning(f"⚠️ [batch_dismiss] 放弃中止补偿回滚异常 ({jid_str}): {rb_err}")
                busy_count += 1
                continue

            # 持久化成功且未在途，操作内存台账
            try:
                _rs.dismiss_job(jid_str)
                _rs.remove_delivery_failure(jid_str)
                dismissed_count += 1
            except Exception as mem_err:
                logger.error(f"❌ [batch_dismiss] 更新内存台账异常 ({jid_str}): {mem_err}")
                failed_count += 1
        else:
            failed_count += 1

    return {
        "status": "success",
        "dismissed_count": dismissed_count,
        "failed_count": failed_count,
        "busy_count": busy_count,
        "message": f"批量放弃完成：已成功放弃 {dismissed_count} 个岗位"
        + (f"，{busy_count} 个岗位正在投递中已跳过" if busy_count > 0 else "")
        + (f"，{failed_count} 个岗位持久化失败" if failed_count > 0 else ""),
    }
