"""飞书 ChatOps 文字快捷审批（放行/拒绝）独立子模块。

从 agent_router 抽出（Q-M9-2 修复 + 500 行红线治理）。

扫描源修复（Q-M9-2）：待审批线程 = 内存 task_queues（job_ 前缀）∪ pending_delivery_pool
SQLite 停车场。旧实现只扫内存——后端重启后 task_queues 清空，graph_runner 在断点写入
停车场的线程永远扫不到，「放行」误报「没有待审批」漏审（checkpoint 断点其实还在，
保留 14 天、待审批岗另有 30 天宽限保护）。

线程号是两套 checkpoint 命名空间：内存流水线线程 task_id 带 job_ 前缀
（agent_router 扫描口径），停车场断点线程 thread_id=record_id（checkpoint_gc 保护
名单口径）——同一逻辑岗位正常只居其一，跨命名空间的同名后缀（job_recX vs recX）
是不同 checkpoint 线程、必须各自扫描，故合并仅做 exact-string 去重（防同号线程
意外双登记被重复 resume）。

恢复语义与重启前一致：对停在 manual_review_node 的断点 Command(resume=...)；
approve=True 继续改写→招呼→投递全链路，False 走拒绝分支。resume 成功后从停车场
移除该记录（与 remove_from_pending_pool 的「已放行走T3/已拒绝」语义对齐）。
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# 停车场读取窗口：与 checkpoint_gc 的待审批保护宽限（PENDING_GRACE_DAYS=30）对齐
_POOL_MAX_AGE_DAYS = 30


async def collect_pending_approval_threads() -> list[str]:
    """收集待审批线程：内存 task_queues ∪ 发射池停车场（去重保序，内存优先）。

    任何一路失败都不阻断另一路：停车场读取异常仅告警，回退为纯内存扫描（旧行为）。
    """
    from app.tasks.state import task_queues

    memory_ids = [k for k in task_queues.keys() if k.startswith("job_")]

    pool_ids: list[str] = []
    try:
        from app.automation.db import get_pending_pool

        def _read_pool():
            return [row["record_id"] for row in get_pending_pool(max_age_days=_POOL_MAX_AGE_DAYS)]

        pool_ids = await asyncio.to_thread(_read_pool)
    except Exception as e:
        logger.warning(f"[快捷审批] 发射池读取失败，回退纯内存扫描: {e}")

    return list(dict.fromkeys([*memory_ids, *pool_ids]))


async def handle_quick_approval(chat_id: str, action: str = "approve", send_message=None) -> None:
    """快捷审批：对所有停在 manual_review_node 的断点线程批量放行/拒绝。

    Args:
        chat_id: 回执目标会话。
        action: "approve"=放行 / "reject"=拒绝。
        send_message: 发消息协程（默认 feishu_service.send_feishu_message 的 to_thread 包装），
          便于测试注入；签名 (chat_id, text)。
    """
    async def _reply(text: str) -> None:
        if send_message is not None:
            await send_message(chat_id, text)
        else:
            from app.services.feishu_service import send_feishu_message

            await asyncio.to_thread(send_feishu_message, chat_id, text, "chat_id")

    try:
        # 导入置于 try 内：与旧 agent_router 实现同语义，导入期异常也有「审批操作异常」兜底回执
        from langgraph.types import Command

        from app.automation.scheduler import pipeline_app

        if not pipeline_app:
            await _reply("⚠️ Pipeline 尚未初始化，无法审批。")
            return

        action_value = True if action == "approve" else False
        action_label = "放行" if action_value else "拒绝"

        await _reply(f"⏳ 正在查找待审批岗位并批量{action_label}...")

        approved_count = 0
        rejected_count = 0
        error_count = 0
        resumed_threads: list[str] = []

        pipeline_threads = await collect_pending_approval_threads()
        logger.info(f"[快捷审批] 扫描待审批线程 {len(pipeline_threads)} 个（内存∪停车场）")

        for tid in pipeline_threads:
            config = {"configurable": {"thread_id": tid}}
            try:
                snapshot = await pipeline_app.aget_state(config)
                if snapshot and snapshot.next and "manual_review_node" in snapshot.next:
                    async for _event in pipeline_app.astream(Command(resume=action_value), config):
                        pass
                    if action_value:
                        approved_count += 1
                    else:
                        rejected_count += 1
                    resumed_threads.append(tid)
            except Exception as e:
                error_count += 1
                logger.warning(f"[快捷审批] 线程 {tid} 处理失败: {e}")

        if resumed_threads:
            try:
                from app.automation.db import remove_from_pending_pool

                await asyncio.to_thread(remove_from_pending_pool, resumed_threads)
            except Exception as e:
                logger.warning(f"[快捷审批] 停车场清理失败（不影响审批结果）: {e}")

        total = approved_count + rejected_count
        if total == 0 and error_count == 0:
            await _reply("📭 当前没有待审批的岗位。")
        else:
            msg = f"✅ 批量{action_label}完毕！\n"
            if approved_count:
                msg += f"  放行: {approved_count} 个\n"
            if rejected_count:
                msg += f"  拒绝: {rejected_count} 个\n"
            if error_count:
                msg += f"  失败: {error_count} 个\n"
            await _reply(msg)

    except Exception as e:
        logger.exception("[快捷审批] 审批操作异常")
        await _reply(f"❌ 审批操作异常: {str(e)}")
