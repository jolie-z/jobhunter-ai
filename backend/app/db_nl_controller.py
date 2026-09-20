#!/usr/bin/env python3
"""
🤖 数据库自然语言查询 Agent（Text-to-SQL + Markdown 表格可视化）
"""

import asyncio
import io
import os
import sqlite3
import sys
import time

import pandas as pd
from openai import OpenAI

# 🌟 修复为基于新架构的引入
from app.core.config import settings
from app.core.llm_tracker import make_tracked_client
from app.services.feishu_service import (
    send_feishu_card,
    send_feishu_file,
    send_feishu_message,
    upload_file_to_feishu,
)

# ---------- 路径与 sys.path 兜底 ----------
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "data", "job_hunter.db")

_client = None
_client_sig = None


def get_client():
    """惰性构建并缓存 OpenAI 客户端；Key/URL 变更时自动重建（配置页保存即生效）。"""
    global _client, _client_sig
    sig = (settings.OPENAI_API_KEY, settings.OPENAI_BASE_URL)
    if _client is None or _client_sig != sig:
        _client = make_tracked_client(OpenAI(api_key=sig[0], base_url=sig[1]), caller="db_nl_controller")
        _client_sig = sig
    return _client

# 🌟 本地 SQLite 全量多表结构上下文
DB_SCHEMA = """
============================================================
【表 1】招聘平台原始岗位表 (中文业务名: 岗位招聘表 / 招聘数据表 / 岗位表)
英文表名: raw_jobs
核心字段及业务含义:
- job_link (TEXT, 主键URL, 岗位的唯一链接)
- job_title (TEXT, 岗位名称)
- company_name (TEXT, 公司名称)
- city (TEXT, 城市)
- jd_text (TEXT, 职位描述)
- salary (TEXT, 薪资区间)
- publish_date (TEXT, 发布日期)
- platform (TEXT, 招聘平台)
- crawl_time (DATETIME, 抓取入库时间)
- is_synced (INTEGER, 飞书同步状态)

【表 2】飞书同步岗位全流程汇总表 (中文业务名: 飞书岗位数据汇总表 / 飞书表 / feishu_jobs)
英文表名: feishu_jobs
说明：该表字段名全部为【纯中文】。
- 综合评级 (A-F) (TEXT)
- 跟进状态 (TEXT)
- 投递日期 (TEXT)

【表 3】面经库核心数据表 (中文业务名: 面经数据表 / 个人面经表)
英文表名: interview_experiences
- question (TEXT, 面试问题)
- golden_answer (TEXT, 黄金参考答案)
============================================================
"""

_DANGEROUS_KEYWORDS = ("DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "REPLACE", "ATTACH", "DETACH")

def _is_dangerous_sql(sql: str) -> bool:
    upper = sql.upper()
    return any(kw in upper for kw in _DANGEROUS_KEYWORDS)

async def process_db_query(chat_id: str, user_query: str):
    print(f"\n{'=' * 50}\n🕵️ [DEBUG] 飞书请求已进入数据库查询 Agent！问题: {user_query}")

    await asyncio.to_thread(send_feishu_message, chat_id, "🔍 正在为您检索本地数据库并整理报表，请稍候...", "chat_id")

    sql_prompt = f"""你是一个严谨、高情商且极具业务洞察力的 AI 数据分析师。
你的任务是将用户的自然语言查询转化为 SQLite 的 SELECT 语句。
【数据库 Schema 参考】\n{DB_SCHEMA}\n
⚠️ 铁律：
1. 遇到需要查询中文日期，必须用 DATE(crawl_time) = 'YYYY-MM-DD'。
2. 绝对只返回单条 SQL，或者 [CLARIFY] 反问句。
用户查询指令: {user_query}"""

    try:
        res1 = await asyncio.to_thread(
            get_client().chat.completions.create,
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": sql_prompt}],
            temperature=0
        )
        raw_output = res1.choices[0].message.content.strip()

        if raw_output.startswith("[CLARIFY]"):
            clarify_msg = raw_output.replace("[CLARIFY]", "").strip()
            await asyncio.to_thread(send_feishu_message, chat_id, f"🤔 {clarify_msg}", "chat_id")
            return

        sql_query = raw_output.replace("```sql", "").replace("```", "").strip()
        print(f"🕵️ [DEBUG] 生成的 SQL: {sql_query}")

        if _is_dangerous_sql(sql_query):
            await asyncio.to_thread(send_feishu_message, chat_id, "❌ 安全警报：检测到非法的修改数据库指令！", "chat_id")
            return

        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            cursor.execute(sql_query)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            results = cursor.fetchall()
        finally:
            conn.close()

        if not results:
            await asyncio.to_thread(send_feishu_message, chat_id, "📬 报告老板，根据您的条件，数据库中没有查到数据。", "chat_id")
            return

        df = pd.DataFrame(results, columns=columns)
        excel_buffer = io.BytesIO()
        await asyncio.to_thread(df.to_excel, excel_buffer, index=False, engine="openpyxl")
        excel_buffer.seek(0)
        excel_bytes = excel_buffer.read()

        answer_prompt = f"""请结合以下信息，向老板汇报：
问题: {user_query}\n执行SQL: {sql_query}\n结果(前30行): {results[:30]}
要求：
1. 必须使用 Markdown 表格展示数据。
2. 寒暄要高情商，结尾不要提附件。"""

        res2 = await asyncio.to_thread(
            get_client().chat.completions.create,
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": answer_prompt}],
            temperature=0.4,
        )
        llm_reply = res2.choices[0].message.content.strip()

        feishu_card = {
            "config": {"wide_screen_mode": True},
            "header": {"template": "blue", "title": {"content": "📊 智能数据分析简报", "tag": "plain_text"}},
            "elements": [
                {"tag": "markdown", "content": llm_reply},
                {"tag": "hr"},
                {"tag": "markdown", "content": "📎 *完整明细已打包为 Excel 附件。*"},
                {"tag": "markdown", "content": f"**🔧 执行溯源:**\n```sql\n{sql_query}\n```"}
            ]
        }

        await asyncio.to_thread(send_feishu_card, chat_id, feishu_card, "chat_id")

        file_name = f"JobHunter_Data_{int(time.time())}.xlsx"
        file_key = await asyncio.to_thread(upload_file_to_feishu, excel_bytes, file_name)
        if file_key:
            await asyncio.to_thread(send_feishu_file, chat_id, file_key, "chat_id")

    except Exception as e:
        print(f"❌ 数据库查询 Agent 异常: {e}")
        try:
            await asyncio.to_thread(send_feishu_message, chat_id, f"❌ 智能报表生成失败: {e}", "chat_id")
        except Exception:
            pass
