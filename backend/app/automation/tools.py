import asyncio
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

import common.config as _ccfg
from app.services.feishu_service import update_feishu_record

BASE_DIR = Path(__file__).resolve().parent.parent.parent

@tool
async def update_feishu_status(record_id: str, updates: dict[str, Any]) -> str:
    """
    更新飞书多维表格中指定岗位的字段状态。

    Args:
        record_id: 飞书的记录 ID
        updates: 需要更新的字段字典，例如 {"跟进状态": "已投递", "AI改写JSON": "..."}

    Returns:
        str: 更新结果的文本描述
    """
    print(f"☁️ 正在将结果回写到飞书，更新字段: {list(updates.keys())}")

    # 因为 LangGraph 内部是跑在 asyncio 下的，所以我们也是用 to_thread 跑这个阻塞调用
    update_success = await asyncio.to_thread(
        update_feishu_record,
        record_id,
        updates,
        _ccfg.FEISHU_TABLE_ID_JOBS
    )

    if update_success:
        return f"✅ 飞书更新成功，记录ID: {record_id}"
    else:
        return f"❌ 飞书更新失败，记录ID: {record_id}"

def _format_delivery_error(platform_name: str, job_data: dict[str, Any] | None) -> str:
    detail = str((job_data or {}).get("delivery_error") or "").strip()
    if detail:
        # 避免拼接“引擎执行失败”前缀以防误触 failure_triage 的 PERSISTENT_PATTERNS 死锁
        return f"❌ {platform_name}投递受阻：{detail}"
    return f"❌ {platform_name}投递受阻，请检查相关日志"

@tool
async def deliver_boss_job(job_data: dict[str, Any]) -> str:
    """
    触发 BOSS 直聘自动化投递脚本。

    Args:
        job_data: 包含投递所需信息的字典，必须包含:
            - record_id: 飞书记录 ID
            - job_url: BOSS 直聘岗位链接
            - file_token: PDF 简历的文件 token
            - pdf_name: 简历文件名
            - greeting: 打招呼语
            - image_items: 图片简历项列表 (可选)

    Returns:
        str: 投递结果的文本描述
    """
    print("🚀 正在调用 BOSS 直聘自动化投递引擎...")

    boss_dir = str(BASE_DIR / "boss_scraper")
    if boss_dir not in sys.path:
        sys.path.insert(0, boss_dir)

    try:
        import boss_auto_delivery
        success = await asyncio.to_thread(boss_auto_delivery.deliver_job, job_data)
        if success:
            return "✅ BOSS 投递引擎执行成功"
        else:
            return _format_delivery_error("BOSS直聘", job_data)
    except Exception as e:
        return f"❌ BOSS 投递引擎执行异常: {str(e)}"

@tool
async def deliver_liepin_job(job_data: dict[str, Any]) -> str:
    """
    触发猎聘自动化投递脚本。

    Args:
        job_data: 包含投递所需信息的字典，必须包含:
            - record_id: 飞书记录 ID
            - job_url: 猎聘岗位链接
            - file_token: PDF 简历的文件 token
            - pdf_name: 简历文件名
            - greeting: 打招呼语
            - image_items: 图片简历项列表 (可选)

    Returns:
        str: 投递结果的文本描述
    """
    print("🚀 正在调用猎聘全自动投递引擎...")

    liepin_dir = str(BASE_DIR / "liepin_scraper")
    if liepin_dir not in sys.path:
        sys.path.insert(0, liepin_dir)

    try:
        import liepin_auto_delivery
        success = await asyncio.to_thread(liepin_auto_delivery.deliver_job, job_data)
        if success:
            return "✅ 猎聘投递引擎执行成功"
        else:
            return _format_delivery_error("猎聘", job_data)
    except Exception as e:
        return f"❌ 猎聘投递引擎执行异常: {str(e)}"

@tool
async def deliver_51job_job(job_data: dict[str, Any]) -> str:
    """
    触发51job(前程无忧)自动化投递脚本。
    51job 不支持打招呼语，直接点击申请职位。

    Args:
        job_data: 包含投递所需信息的字典，必须包含:
            - record_id: 飞书记录 ID
            - job_url: 51job 岗位链接

    Returns:
        str: 投递结果的文本描述
    """
    print("🚀 正在调用 [51job] 全自动投递引擎...")

    job51_dir = str(BASE_DIR / "51job_scraper")
    if job51_dir not in sys.path:
        sys.path.insert(0, job51_dir)

    try:
        import importlib
        mod = importlib.import_module("51job_auto_delivery")
        success = await asyncio.to_thread(mod.deliver_job, job_data)
        if success:
            return "✅ 51job 投递引擎执行成功"
        else:
            return _format_delivery_error("51job", job_data)
    except Exception as e:
        return f"❌ 51job 投递引擎执行异常: {str(e)}"

@tool
async def deliver_zhilian_job(job_data: dict[str, Any]) -> str:
    """
    触发智联招聘自动化投递脚本。
    智联通过上传简历附件后申请职位，并随微聊发送打招呼语（必填，缺失时引擎直接失败）。

    Args:
        job_data: 包含投递所需信息的字典，必须包含:
            - record_id: 飞书记录 ID
            - job_url: 智联招聘岗位链接
            - file_token: PDF 简历的文件 token
            - pdf_name: 简历文件名
            - greeting: 打招呼语（必填）
            - job_title: 岗位名称 (可选)
            - company: 公司名称 (可选)

    Returns:
        str: 投递结果的文本描述
    """
    print("🚀 正在调用 [智联招聘] 全自动投递引擎...")

    zhilian_dir = str(BASE_DIR / "zhilian_scraper")
    if zhilian_dir not in sys.path:
        sys.path.insert(0, zhilian_dir)

    try:
        import zhilian_auto_delivery
        success = await asyncio.to_thread(zhilian_auto_delivery.deliver_job, job_data)
        if success:
            return "✅ 智联投递引擎执行成功"
        else:
            return _format_delivery_error("智联招聘", job_data)
    except Exception as e:
        return f"❌ 智联投递引擎执行异常: {str(e)}"
