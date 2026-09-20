"""
岗位链接预检
==================
在评估/投递前检查岗位链接是否仍然有效，剔除死链，避免浪费 LLM 评估与投递尝试。

目前只覆盖 BOSS（存量链接失效率高）；判定标准与投递引擎完全一致
（boss_auto_delivery.check_job_link_alive：页面有「立即沟通/继续沟通」才算活）。
"""
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def _ensure_boss_path():
    boss_dir = str(BACKEND_DIR / "boss_scraper")
    if boss_dir not in sys.path:
        sys.path.insert(0, boss_dir)


def extract_job_url(feishu_fields: dict[str, Any]) -> str:
    """从飞书 fields 提取岗位链接（与 workflow.delivery_node 同逻辑）。"""
    link_obj = feishu_fields.get("岗位链接", {})
    if isinstance(link_obj, dict):
        return link_obj.get("link", "") or ""
    return str(link_obj or "")


def is_boss_platform(platform: str) -> bool:
    p = (platform or "").lower()
    return "boss" in p or "直聘" in (platform or "")


def check_boss_link_sync(job_url: str):
    """同步版预检（线程池里跑，避免阻塞事件循环）。返回 True/False/None。"""
    _ensure_boss_path()
    import boss_auto_delivery as boss
    return boss.check_job_link_alive(job_url)


async def precheck_boss_link(job_url: str):
    """异步入口：True=活链 / False=确定死链 / None=无法判定（保留岗位，不误杀）。设置 6s 熔断保护。"""
    if not job_url:
        return False
    try:
        return await asyncio.wait_for(asyncio.to_thread(check_boss_link_sync, job_url), timeout=6.0)
    except asyncio.TimeoutError:
        logger.warning(f"[链接预检] 超时熔断（6s未响应，无法判定，保留岗位）: {job_url}")
        return None
    except Exception as e:
        logger.warning(f"[链接预检] 异常（无法判定，保留岗位）: {e}")
        return None


async def build_checked_batch(new_jobs: list[dict[str, Any]], batch_limit: int, pipeline_task_id: str) -> list[dict[str, Any]]:
    """构建本轮评估批次：按新鲜度排序 + BOSS 链接预检。

    - 死链（确定无沟通入口）：剔除，并把飞书记录标记为「已下架」
    - 无法判定（浏览器异常等）：保留岗位，不误杀
    - 预检有预算上限（2×batch_limit），超预算后不再预检直接递补，避免链路长时间挂起
    """
    from app.automation import pipeline_broadcast as pb
    from app.services.feishu_service import update_feishu_record

    new_jobs.sort(key=lambda j: j.get("_created_time", 0), reverse=True)
    if batch_limit <= 0:
        return new_jobs

    max_checks = max(batch_limit * 2, 10)
    selected: list[dict[str, Any]] = []
    checked, dead = 0, 0
    for job in new_jobs:
        if len(selected) >= batch_limit:
            break
        if is_boss_platform(job.get("platform", "")) and checked < max_checks:
            checked += 1
            url = extract_job_url(job.get("feishu_fields", {}))
            alive = await precheck_boss_link(url)
            if alive is False:
                dead += 1
                rid = job.get("record_id", "")
                if rid:
                    try:
                        await asyncio.to_thread(update_feishu_record, rid, {"跟进状态": "已下架"})
                    except Exception as e:
                        logger.warning(f"[FullAuto] 死链标记失败 {rid}: {e}")
                await pb.emit_log(
                    pipeline_task_id,
                    f"💀 链接已失效，剔除: {job.get('company_name', '')} {str(job.get('job_name', ''))[:24]}")
                continue
        selected.append(job)

    if checked:
        await pb.emit_log(
            pipeline_task_id,
            f"🔍 链接预检完成: 检查 {checked} 条 BOSS 链接，剔除死链 {dead} 条，{len(selected)} 条进入评估")
    return selected


_build_checked_batch = build_checked_batch
