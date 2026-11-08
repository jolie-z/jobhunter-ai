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


def _ensure_zhilian_path():
    zhilian_dir = str(BACKEND_DIR / "zhilian_scraper")
    if zhilian_dir not in sys.path:
        sys.path.insert(0, zhilian_dir)


def extract_job_url(feishu_fields: dict[str, Any]) -> str:
    """从飞书 fields 提取岗位链接（与 workflow.delivery_node 同逻辑）。"""
    link_obj = feishu_fields.get("岗位链接", {})
    if isinstance(link_obj, dict):
        return link_obj.get("link", "") or ""
    return str(link_obj or "")


def is_boss_platform(platform: str) -> bool:
    p = (platform or "").lower()
    return "boss" in p or "直聘" in (platform or "")


def is_zhilian_platform(platform: str) -> bool:
    p = (platform or "").lower()
    return "zhilian" in p or "智联" in (platform or "")


def check_boss_link_sync(job_url: str):
    """同步版预检（线程池里跑，避免阻塞事件循环）。返回 True/False/None。"""
    _ensure_boss_path()
    import boss_auto_delivery as boss
    return boss.check_job_link_alive(job_url)


def check_zhilian_link_sync(job_url: str):
    """智联同步版预检（2026-10-11 泰索斯事故扩展：评估前剔除智联死链，省评估/投递）。

    判定与投递引擎完全一致（zhilian_auto_delivery._detect_dead_job_page +
    主操作区按钮）：有按钮=活；失效 DOM 签名/失效文本=死；无按钮且无签名=无法判定。
    """
    if not (job_url or "").startswith("http"):
        # 非 http(s) 输入：跳转保护缺失会导致 sleep 后扫描浏览器残留页，判定不可信——直接无法判定
        return None
    _ensure_zhilian_path()
    import zhilian_auto_delivery as zhilian
    if job_url.startswith("http://"):
        job_url = "https://" + job_url[7:]
    try:
        page = zhilian._get_shared_browser()
    except Exception as e:
        logger.warning(f"[链接预检] 智联浏览器不可用（无法判定，保留岗位）: {e}")
        return None
    try:
        if not zhilian._is_logged_in(page):
            logger.warning("[链接预检] 智联登录态不可用，预检无法判定（保留岗位，不误杀）")
            return None
        if job_url.startswith("http"):
            page.get(job_url)
        import time as _time
        _time.sleep(3)
        dead_hint = zhilian._detect_dead_job_page(page)
        if dead_hint:
            logger.info(f"[链接预检] 智联死链确认（{dead_hint}）: {job_url}")
            return False
        try:
            if page.eles('css:.summary-planes__action button', timeout=2):
                return True
        except Exception:
            pass
        logger.warning("[链接预检] 智联页面无按钮且无失效签名（无法判定，保留岗位）")
        return None
    except Exception as exc:
        logger.warning(f"[链接预检] 智联预检异常（无法判定，保留岗位）: {str(exc)[:80]}")
        return None


async def precheck_boss_link(job_url: str):
    """异步入口：True=活链 / False=确定死链 / None=无法判定（保留岗位，不误杀）。

    外审 round2-P1 双重修正：
    1. 非阻塞预探（wait_timeout_s=0）：引擎在飞立即返回 None，绝不逐条干等 90s
       （批级预探只覆盖入口时刻，批中引擎占用的 TOCTOU 由本层 0 等待兜住，N×90s 从
       机制上不可能发生）；
    2. 无 wait_for 熔断（round2-P1-3）：aux 位持有到同步检测线程自然结束——线程
       残留窗口（DrissionPage page_load=30s 级）与 aux 释放完全同步，引擎闸门在
       线程结束前无法进入，导航共享标签页的窗口从机制上关闭。最坏延迟 ≈38s/条，
       由批级预探与逐条 0 等待保证不会叠加。
    """
    if not job_url:
        return False
    import hashlib

    from app.automation import platform_mutex
    owner = f"link_precheck:{hashlib.md5(job_url.encode()).hexdigest()[:12]}"
    # run_with_aux（round4-P1-1'' 终版）：aux 释放挂线程 done-callback——线程活着
    # aux 必在，引擎闸门在线程结束前无法进入；协程取消不放锁。R9 撞页窗三路径全关。
    return await platform_mutex.run_with_aux(check_boss_link_sync, "boss", owner, job_url,
                                             _wait_timeout_s=0)


async def precheck_zhilian_link(job_url: str):
    """智联异步入口：契约同 precheck_boss_link（非阻塞预探 + aux 持有到线程结束）。"""
    if not job_url:
        return False
    import hashlib

    from app.automation import platform_mutex
    owner = f"link_precheck:{hashlib.md5(job_url.encode()).hexdigest()[:12]}"
    return await platform_mutex.run_with_aux(check_zhilian_link_sync, "zhilian", owner, job_url,
                                             _wait_timeout_s=0)


async def build_checked_batch(new_jobs: list[dict[str, Any]], batch_limit: int, pipeline_task_id: str) -> list[dict[str, Any]]:
    """构建本轮评估批次：按新鲜度排序 + BOSS/智联链接预检（2026-10-11 扩展智联）。

    - 死链（确定无沟通入口）：剔除，并把飞书记录标记为「已下架」
    - 无法判定（浏览器异常等）：保留岗位，不误杀
    - 预检有预算上限（2×batch_limit），超预算后不再预检直接递补，避免链路长时间挂起
    - 引擎在飞批级预探（外审 round1-P1 修正）：预检逐条经 auxiliary_gate 与引擎互斥，
      投递在飞时逐条各等 90s 会把评估批次拖长 N×90s——故批首先探测一次，引擎忙则
      整批跳过预检（全部按无法判定保留，与逐条拒绝同语义），不逐条干等。
    """
    from app.automation import pipeline_broadcast as pb
    from app.automation import platform_mutex
    from app.services.feishu_service import update_feishu_record

    new_jobs.sort(key=lambda j: j.get("_created_time", 0), reverse=True)
    if batch_limit <= 0:
        return new_jobs

    # 批级预探（round2-P2 按平台分别判定）：boss/zhilian 各自独立——boss 的存活检测
    # 在飞只跳过 boss 预检，zhilian 岗位照常预检，不扩大未预检范围
    involved_platforms = {j.get("platform", "") for j in new_jobs[: max(batch_limit * 2, 10)]}
    skip_platforms = set()
    for plat in involved_platforms:
        key = "boss" if is_boss_platform(plat) else ("zhilian" if is_zhilian_platform(plat) else None)
        if key and (platform_mutex.is_scrape_busy(key) or platform_mutex.is_delivery_busy(key)
                    or platform_mutex.is_aux_busy(key)):
            skip_platforms.add(key)
    if skip_platforms:
        names = "、".join("BOSS直聘" if p == "boss" else "智联招聘" for p in sorted(skip_platforms))
        await pb.emit_log(
            pipeline_task_id,
            f"⏭️ {names} 抓取/投递/存活检测进行中，本轮跳过其链接预检（岗位全部保留，引擎空闲后自动补检）")

    max_checks = max(batch_limit * 2, 10)
    selected: list[dict[str, Any]] = []
    checked, dead = 0, 0
    for job in new_jobs:
        if len(selected) >= batch_limit:
            break
        platform_name = job.get("platform", "")
        if (is_boss_platform(platform_name) or is_zhilian_platform(platform_name)) and checked < max_checks:
            checked += 1
            url = extract_job_url(job.get("feishu_fields", {}))
            skip_key = "boss" if is_boss_platform(platform_name) else (
                "zhilian" if is_zhilian_platform(platform_name) else None)
            if skip_key in skip_platforms:
                alive = None  # 批级预探判定该平台引擎在飞：直接保留，不进闸门
            elif is_boss_platform(platform_name):
                alive = await precheck_boss_link(url)
            else:
                alive = await precheck_zhilian_link(url)
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
            f"🔍 链接预检完成: 检查 {checked} 条链接（BOSS/智联），剔除死链 {dead} 条，{len(selected)} 条进入评估")
    return selected


_build_checked_batch = build_checked_batch
