#!/usr/bin/env python3
"""
积压岗位存活检测与飞书清理
==========================
对积压期已同步至飞书的岗位逐条做链接存活预检（与投递引擎同一判定标准）：
  - 死链（已下架）→ 从飞书多维表格删除该行；SQLite 行保留不删，仅标记「已确认淘汰」防止再同步
  - 活链（还在招聘）→ 保留，一切不动
  - 无法判定（超时/异常/风控）→ 不动，不误杀

用法:
  python scripts/check_stale_jobs_liveness.py --limit 5 --dry-run   # 试点（只看判定不删）
  python scripts/check_stale_jobs_liveness.py --limit 50            # 正式执行
  python scripts/check_stale_jobs_liveness.py --from 2026-08-08 --to 2026-08-11 --all
"""
import argparse
import asyncio
import json
import random
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

load_dotenv(BACKEND / ".env", override=False)

from app.core.config import settings  # noqa: E402

DB_PATH = BACKEND / "data" / "job_hunter.db"
MARK_STATUS = "已确认淘汰"
MARK_REASON = "链接存活预检判定已下架（2026-08-29 积压清理，SQLite 保留）"


def get_platform_browser(platform: str):
    """连接指定平台的常驻 Edge 浏览器（与各投递引擎同源：registry 端口 + 统一 Profile）"""
    from DrissionPage import ChromiumPage, ChromiumOptions
    from app.session.registry import get_profile_path, get_platform_port

    co = ChromiumOptions()
    co.set_address(f"127.0.0.1:{get_platform_port(platform)}")
    profile_dir = get_profile_path(platform)
    co.set_user_data_path(profile_dir)
    return ChromiumPage(addr_or_opts=co)


ZHILIAN_DEAD_KWS = ["职位已失效", "职位已下架", "已停止招聘", "该职位已关闭"]
LIEPIN_DEAD_KWS = ["职位已下线", "职位已失效", "已停止招聘", "该职位已关闭", "已下架"]


def check_zhilian_link(page, job_url: str):
    """智联存活判定：死链关键词 / 登录态 / 投递入口（与 zhilian_auto_delivery 同标准）。"""
    if job_url.startswith("http://"):
        job_url = "https://" + job_url[7:]
    tab = page.new_tab(job_url)
    time.sleep(4)
    try:
        if tab.ele("text:扫码登录", timeout=2) or tab.ele("text:手机号登录", timeout=2):
            return None, "未登录"
        if tab.ele("css:.registers-guide__button", timeout=1):
            return None, "登录态失效"
        for kw in ZHILIAN_DEAD_KWS:
            if tab.ele(f"text:{kw}", timeout=1):
                return False, f"页面提示：{kw}"
        for alive in ["立即投递", "申请职位", "去投递", "继续沟通"]:
            if tab.ele(f"text:{alive}", timeout=1):
                return True, f"发现入口：{alive}"
        return None, "无已知标志（保守不判）"
    finally:
        try:
            tab.close()
        except Exception:
            pass


def check_liepin_link(page, job_url: str):
    """猎聘存活判定：死链关键词 / 聊一聊入口（与 liepin_auto_delivery 同标准，保守不判优先）。"""
    tab = page.new_tab(job_url)
    time.sleep(4)
    try:
        if tab.ele("text:扫码登录", timeout=2):
            return None, "未登录"
        for kw in LIEPIN_DEAD_KWS:
            if tab.ele(f"text:{kw}", timeout=1):
                return False, f"页面提示：{kw}"
        for alive in ["聊一聊", "继续聊", "立即沟通", "申请职位"]:
            if tab.ele(f"text:{alive}", timeout=1):
                return True, f"发现入口：{alive}"
        return None, "无已知标志（保守不判）"
    finally:
        try:
            tab.close()
        except Exception:
            pass


def check_51job_link(ctx, job_url: str, job_title: str):
    """51job 存活判定（Playwright CDP 复用 9227 登录态）：
    活链 = 投递入口按钮或岗位标题在 DOM；死链 = 显式失效关键词；其余保守不判。"""
    pg = ctx.new_page()
    try:
        pg.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        pg.wait_for_timeout(4000)
        body = pg.content()
        # 死链标志（含用户实测确认的「当前职位审核中或已下线」空态页，2026-08-30 标定）
        for kw in ["职位不存在", "已失效", "已下架", "已停止招聘", "该职位已关闭", "审核中或已下线", "当前职位审核中"]:
            if kw in body:
                return False, f"页面提示：{kw}"
        if "重新搜索" in body and "立即投递" not in body and "投递简历" not in body:
            return False, "空态页（重新搜索）"
        for alive in ["立即投递", "投递简历", "申请职位"]:
            if alive in body:
                return True, f"发现入口：{alive}"
        if (job_title or "")[:8] and job_title[:8] in body:
            return True, "标题在DOM"
        return None, "无已知标志（保守不判）"
    finally:
        try:
            pg.close()
        except Exception:
            pass


PLATFORM_CHECKS = {"boss", "zhilian", "liepin", "51job"}  # 51job 走 Playwright CDP(9227) 页面标志检测
PLATFORM_DB_PATTERNS = {  # raw_jobs.platform 存的是中文平台名
    "boss": "%BOSS%",
    "zhilian": "%智联%",
    "liepin": "%猎聘%",
    "51job": "%51job%",
}


def fetch_candidates(date_from: str, date_to: str, limit: int, platform: str = "boss", recheck_pending: bool = False):
    """积压期已进飞书（有 record_id）的指定平台岗位，按入库先后取；跳过本轮之前已检过的行。
    recheck_pending=True 时忽略断点记录，重检所有未淘汰行（用于补跑被中断批次的删除缺口）。"""
    checked_file = Path(__file__).parent / ".liveness_checked_rowids.txt"
    checked = set()
    if checked_file.exists() and not recheck_pending:
        checked = {int(x) for x in checked_file.read_text().split() if x.strip().isdigit()}
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        f"""
        SELECT rowid, job_link, feishu_record_id, job_title, company_name, platform, process_status
        FROM raw_jobs
        WHERE date(crawl_time) BETWEEN ? AND ?
          AND process_status IN ('已同步', '待推送至飞书')
          AND feishu_record_id IS NOT NULL AND feishu_record_id != ''
          AND platform LIKE ?
        ORDER BY rowid
        """,
        (date_from, date_to, PLATFORM_DB_PATTERNS.get(platform, f"%{platform}%")),
    ).fetchall()
    conn.close()
    rows = [r for r in rows if r[0] not in checked][:limit]
    return rows, checked_file


def mark_dead_in_sqlite(rowids: list):
    conn = sqlite3.connect(DB_PATH)
    conn.executemany(
        "UPDATE raw_jobs SET process_status = ?, reject_reason = ? WHERE rowid = ?",
        [(MARK_STATUS, MARK_REASON, r) for r in rowids],
    )
    conn.commit()
    conn.close()


async def delete_from_feishu(record_ids: list):
    from app.core.feishu_client import feishu_client

    deleted, failed = 0, []
    # 飞书 batch_delete 单次上限 500，这里量级小，直接整批
    try:
        res = await feishu_client.batch_delete_records(settings.FEISHU_TABLE_ID_JOBS, record_ids)
        deleted = len(record_ids)
    except Exception as e:
        print(f"  ❌ 批量删除失败，降级为逐条删除: {str(e)[:80]}")
        for rid in record_ids:
            try:
                await feishu_client.delete_record(settings.FEISHU_TABLE_ID_JOBS, rid)
                deleted += 1
            except Exception as e2:
                failed.append((rid, str(e2)[:60]))
    return deleted, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", default="2026-08-08")
    ap.add_argument("--to", dest="date_to", default="2026-08-11")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--platform", default="boss", help="boss（现仅支持）/ 51job / zhilian / liepin")
    ap.add_argument("--recheck-pending", action="store_true", help="忽略断点记录，重检所有未淘汰行（补中断缺口）")
    ap.add_argument("--dry-run", action="store_true", help="只做存活判定与汇报，不删飞书、不改库")
    args = ap.parse_args()

    if args.platform not in PLATFORM_CHECKS:
        print(f"⚠️ 平台 {args.platform} 的存活检测器尚未接入（51job 为 API 截获型架构，需单独校准）。")
        sys.exit(2)

    rows, checked_file = fetch_candidates(args.date_from, args.date_to, args.limit, args.platform, args.recheck_pending)
    if not rows:
        print("该范围内没有待检的已同步岗位（或已全部检过），结束。")
        return
    print(f"共取到 {len(rows)} 条待检 {args.platform} 岗位（{args.date_from} ~ {args.date_to}），预检中…\n")

    browser = None
    pw51 = None
    if args.platform in ("zhilian", "liepin"):
        print(f"🔌 连接 {args.platform} 常驻浏览器…")
        browser = get_platform_browser(args.platform)
    elif args.platform == "51job":
        from playwright.sync_api import sync_playwright
        print("🔌 连接 51job Edge 浏览器 (CDP 9227)…")
        pw51 = sync_playwright().start()
        b51 = pw51.chromium.connect_over_cdp("http://127.0.0.1:9227", timeout=15000)
        browser = b51.contexts[0] if b51.contexts else b51.new_context()
    else:
        from app.automation.link_precheck import check_boss_link_sync

    alive, dead, unknown = [], [], []
    for i, (rowid, link, rid, title, company, platform, status) in enumerate(rows, 1):
        verdict, reason = None, ""
        try:
            if args.platform == "boss":
                verdict = check_boss_link_sync(link)
            elif args.platform == "zhilian":
                verdict, reason = check_zhilian_link(browser, link)
            elif args.platform == "liepin":
                verdict, reason = check_liepin_link(browser, link)
            elif args.platform == "51job":
                verdict, reason = check_51job_link(browser, link, title)
        except Exception as e:
            print(f"  [{i}/{len(rows)}] ⚠️ 预检异常（按无法判定处理）: {str(e)[:60]}")
        tag = {True: "🟢 在招", False: "💀 已下架", None: "🟡 无法判定"}[verdict]
        print(f"  [{i}/{len(rows)}] {tag}{('（' + reason + '）') if reason else ''} | {company[:10]} | {title[:18]} | {status}")
        (alive if verdict is True else dead if verdict is False else unknown).append(
            (rowid, link, rid, title, company)
        )
        with checked_file.open("a") as f:
            f.write(f"{rowid}\n")
        # 逐行判定日志（JSONL 追加）：防止管道截断丢失明细，便于事后导出无法判定清单
        with Path(__file__).parent.joinpath(".liveness_verdicts.jsonl").open("a") as f:
            f.write(json.dumps({
                "platform": args.platform, "rowid": rowid, "link": link,
                "title": title, "company": company, "status": status,
                "verdict": {True: "alive", False: "dead", None: "unknown"}[verdict],
                "reason": reason,
            }, ensure_ascii=False) + "\n")
        time.sleep(random.uniform(1.5, 3.0))

    print(f"\n===== 判定汇总：🟢 在招 {len(alive)} | 💀 已下架 {len(dead)} | 🟡 无法判定 {len(unknown)} =====")

    if args.dry_run:
        print("（dry-run 模式：不删除飞书行、不更新 SQLite）")
        for rowid, link, rid, title, company in dead:
            print(f"  将删除: record_id={rid} | {company[:10]} | {title[:18]}")
        return

    if dead:
        record_ids = [d[2] for d in dead]
        print(f"\n开始清理飞书 {len(record_ids)} 行…")
        deleted, failed = asyncio.run(delete_from_feishu(record_ids))
        print(f"  飞书删除完成: 成功 {deleted}, 失败 {len(failed)}")
        for rid, err in failed:
            print(f"    ❌ {rid}: {err}")
        ok_rowids = [d[0] for d in dead]
        mark_dead_in_sqlite(ok_rowids)
        print(f"  SQLite 已标记 {len(ok_rowids)} 条为「{MARK_STATUS}」（数据行保留）")
    else:
        print("没有死链需要清理。")


if __name__ == "__main__":
    main()
