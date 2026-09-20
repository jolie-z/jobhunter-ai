"""全链路指挥中心质检 · 隔离环境哨兵脚本（S1/S2/S3）。

配套 docs/qa/command-center-qa-matrix.md 第 5 层硬性前置：
- S1 飞书隔离哨兵：经隔离实例注入测试岗 → 断言【测试表收到（阳性对照）+ 生产表零变化（阴性对照）】。
- S2 LLM 计数哨兵：读隔离实例 SQLite 的 token_log 行数，对照声明预算（0 stub / ≤N 真实）。
- S3 投递拦截哨兵：向测试表直造「待投递」哨兵岗 → 调隔离实例 /deliver_approved →
  断言【门牌未翻已投递 + 51job 配额文件零变更 + 无浏览器进程残留】，允许缺料/登录守卫任一层拦截。

用法（在 backend/ 下用生产 venv 运行，生产 .env 仅用于只读指纹）：
  python scripts/command_center_qa_sentry.py s1 --base-url http://127.0.0.1:8017 --qa-table <QA_TABLE_ID>
  python scripts/command_center_qa_sentry.py s2 --db /path/to/isolated/data/job_hunter.db --budget 30
  python scripts/command_center_qa_sentry.py s3 --base-url http://127.0.0.1:8017 --qa-table <QA_TABLE_ID> \
      --quota-file /path/to/isolated/data/51job_upload_quota.json
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.feishu_client import feishu_client  # noqa: E402

SENTINEL_MARKER = "QA哨兵公司"
DEFAULT_PROFILE_PATTERN = "qa_cc_isolated.*profiles|profiles.*qa_cc_isolated"


def _bitable_url(table_id: str, suffix: str) -> str:
    """Bitable records API URL 收敛：app 前缀样板一处定义，分页改写逻辑不受影响。"""
    return (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}"
        f"/tables/{table_id}{suffix}"
    )


# ---------------------------------------------------------------- 飞书只读指纹
async def _table_record_ids(table_id: str) -> set[str]:
    """拉取指定表的全部 record_id（只读，用于前后对比指纹）。"""
    ids: set[str] = set()
    token = await feishu_client.get_tenant_access_token()
    url = _bitable_url(table_id, "/records/search?page_size=500")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(headers=headers, timeout=30) as c:
        while url:
            r = (await c.post(url, json={})).json()
            if r.get("code") != 0:
                raise RuntimeError(f"飞书 search 失败: {r.get('code')} {r.get('msg')}")
            data = r.get("data") or {}
            ids |= {item["record_id"] for item in (data.get("items") or [])}
            page = data.get("page_token")
            url = url.split("&page_token=")[0] + f"&page_token={page}" if page else None
    return ids


async def _qa_table_find_marker(table_id: str, marker: str) -> list[str]:
    """在测试表里按公司名找哨兵记录（阳性对照）。"""
    token = await feishu_client.get_tenant_access_token()
    url = _bitable_url(table_id, "/records/search?page_size=50")
    body = {"filter": {"conjunction": "and", "conditions": [
        {"field_name": "公司名称", "operator": "is", "value": [marker]}
    ]}}
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30) as c:
        r = (await c.post(url, json=body)).json()
    if r.get("code") != 0:
        raise RuntimeError(f"QA 表 filter 失败: {r.get('code')} {r.get('msg')}")
    return [i["record_id"] for i in (r.get("data") or {}).get("items") or []]


# ---------------------------------------------------------------- S1
async def sentry_s1(base_url: str, qa_table: str) -> int:
    ts = datetime.now().strftime("%m%d%H%M%S")
    company = f"{SENTINEL_MARKER}{ts}"
    raw_text = (
        f"公司名称：{company}\n岗位名称：QA哨兵测试岗\n城市：广州\n薪资：20-30K\n"
        f"招聘平台：BOSS直聘\n岗位链接：https://www.zhipin.com/job_detail/qa{ts}.htm\n"
        "岗位详情：负责质检哨兵验证，全日制本科，3-5年经验，熟悉 Python 与自动化测试。"
    )
    print(f"[S1] ① 生产表指纹（前）…")
    prod_before = await _table_record_ids(settings.FEISHU_TABLE_ID_JOBS)
    print(f"[S1]    生产岗位表 record 数: {len(prod_before)}")

    print("[S1] ② 经隔离实例极速录入哨兵岗 …")
    async with httpx.AsyncClient(base_url=base_url, timeout=60) as c:
        r = await c.post("/api/jobs/import/parse", json={"raw_text": raw_text})
        r.raise_for_status()
        fields = r.json()["fields"]
        r2 = await c.post("/api/jobs/import/confirm", json={"fields": fields, "force_duplicate": False})
        if r2.status_code == 409:
            r2 = await c.post("/api/jobs/import/confirm", json={"fields": fields, "force_duplicate": True})
        r2.raise_for_status()
        record_id = r2.json()["data"].get("record_id")
        print(f"[S1]    隔离实例回执 record_id: {record_id}")

    print("[S1] ③ 阳性对照：测试表应收到哨兵记录 …")
    qa_hits = await _qa_table_find_marker(qa_table, company)
    ok_pos = bool(qa_hits)
    print(f"[S1]    测试表命中: {qa_hits or '无'} → {'✅' if ok_pos else '❌'}")

    print("[S1] ④ 阴性对照：生产表应零变化 …")
    prod_after = await _table_record_ids(settings.FEISHU_TABLE_ID_JOBS)
    added = prod_after - prod_before
    removed = prod_before - prod_after
    ok_neg = not added and not removed
    print(f"[S1]    生产表 record 数: {len(prod_after)}｜新增 {len(added)}｜删除 {len(removed)} → {'✅' if ok_neg else '❌'}")
    if added: print(f"[S1]    ⚠️ 新增明细: {sorted(added)[:10]}")
    if removed: print(f"[S1]    ⚠️ 删除明细: {sorted(removed)[:10]}")

    verdict = ok_pos and ok_neg
    print(f"[S1] 结论: {'PASS ✅' if verdict else 'FAIL ❌'}（哨兵公司: {company}）")
    return 0 if verdict else 1


# ---------------------------------------------------------------- S2
def sentry_s2(db_path: str, budget: int, before: int | None) -> int:
    import sqlite3
    p = Path(db_path)
    if not p.exists():
        print(f"[S2] ❌ 数据库不存在: {p}")
        return 1
    # 只读打开；路径含 ?/# 等 URI 特殊字符时需先编码（当前用法路径可控）
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "token_log" not in tables:
            print("[S2] ⚠️ token_log 表不存在（该库尚无 LLM 调用）→ 计数 0")
            count = 0
        else:
            count = conn.execute("SELECT COUNT(*) FROM token_log").fetchone()[0]
    finally:
        conn.close()
    delta = None if before is None else count - before
    print(f"[S2] token_log 总数: {count}｜相对基线增量: {delta if delta is not None else '未提供基线'}｜声明预算: {budget}")
    ok = count <= budget and (delta is None or delta <= budget)
    print(f"[S2] 结论: {'PASS ✅' if ok else 'FAIL ❌ 超出预算'}")
    return 0 if ok else 1


# ---------------------------------------------------------------- S3
async def sentry_s3(base_url: str, qa_table: str, quota_file: str | None, allow_no_quota: bool = False, profile_pattern: str = DEFAULT_PROFILE_PATTERN) -> int:
    # 配额断言 fail-closed：忘传 --quota-file 或路径拼错时绝不能静默空转成假 PASS
    quota_before = _quota_state(quota_file)
    if quota_before is None:
        if not allow_no_quota:
            print(f"[S3] ❌ 51job 配额文件不可读（未提供 / 不存在 / 内容非法 JSON 三者之一）: {quota_file}；如确认无此文件请显式传 --allow-no-quota")
            return 1
        print("[S3] ⚠️ 显式声明无配额文件（--allow-no-quota），跳过该项检查")
    ts = datetime.now().strftime("%m%d%H%M%S")
    company = f"{SENTINEL_MARKER}投递{ts}"
    print("[S3] ① 测试表直造「待投递」哨兵岗（BOSS，无物料）…")
    token = await feishu_client.get_tenant_access_token()
    create_url = _bitable_url(qa_table, "/records")
    fields = {
        "公司名称": company,
        "岗位名称": "QA投递哨兵岗",
        "城市": "广州",
        "招聘平台": "BOSS直聘",
        "跟进状态": "待投递",
        # URL 类型字段必须用 {link, text} 对象格式（与 import_service 写入口径一致）
        "岗位链接": {"link": f"https://www.zhipin.com/job_detail/qa{ts}.html", "text": "点击查看"},
        "岗位详情": "QA 投递拦截哨兵：验证隔离实例绝无真实投递副作用。",
    }
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30) as c:
        r = (await c.post(create_url, json={"fields": fields})).json()
        if r.get("code") != 0:
            print(f"[S3] ❌ 造岗失败: {r.get('code')} {r.get('msg')}")
            return 1
        record_id = r["data"]["record"]["record_id"]
        print(f"[S3]    哨兵岗 record_id: {record_id}")

    print("[S3] ② 调隔离实例 /deliver_approved（预期在某层 fail-closed 拦截）…")
    async with httpx.AsyncClient(base_url=base_url, timeout=180) as c:
        r = await c.post("/api/automation/deliver_approved", json={"thread_ids": [record_id]})
        print(f"[S3]    端点返回 HTTP {r.status_code}: {r.text[:200]}")
    # 等编排与引擎收尾：门牌应翻转/保持为「投递失败」（或停在待投递），绝不允许「已投递」。
    # 注意失败回写为异步 eventual-write，轮询最长 90s 等「投递失败」落牌。
    final_status = None
    initial_status = None
    poll_failures = 0
    for _ in range(45):
        await asyncio.sleep(2)
        rec_url = _bitable_url(qa_table, f"/records/{record_id}")
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30) as c:
            rec = (await c.get(rec_url)).json()
        # fail-closed：观测渠道本身失效（code!=0）绝不能当「空门牌」静默放行
        if rec.get("code") != 0:
            poll_failures += 1
            print(f"[S3] ⚠️ 门牌读取失败 ({poll_failures}/5): {rec.get('code')} {str(rec.get('msg'))[:60]}")
            if poll_failures >= 5:
                print("[S3] ❌ 飞书观测渠道连续失败，「未翻已投递」不变量无法证明 → FAIL")
                return 1
            continue
        poll_failures = 0
        raw_status = (((rec.get("data", {}) or {}).get("record", {}) or {}).get("fields") or {}).get("跟进状态")
        status_now = _flat_text(raw_status) or "（空）"
        if initial_status is None:
            initial_status = status_now  # 以首次成功观测为基准（首查失败 continue 不得占用初值位）
        if "已投递" in status_now and "失败" not in status_now:
            print(f"[S3] ❌ 门牌翻转为: {status_now} —— 出现真实投递副作用！")
            return 1
        # 只有观测到「失败」、或状态离开初始值（说明编排已产生真实状态转移）才提前收口；
        # 初始「待投递」原样持续不算落牌（编排收尾未完成，继续等满窗口）
        if "失败" in status_now or (status_now != initial_status):
            final_status = status_now
            break
        final_status = status_now
    is_fail_form = final_status is not None and "失败" in final_status
    # 门牌异常形态探测器：变（空）、或离开初始值却未落「失败」——提示异常改写，需人工复核
    abnormal_status_detected = (
        final_status is not None and not is_fail_form
        and ("（空）" in final_status or (initial_status == "待投递" and final_status != initial_status))
    )
    if is_fail_form:
        print(f"[S3]    最终门牌: {final_status}（拦截形态确认 ✅）")
    elif abnormal_status_detected:
        print(f"[S3]    最终门牌: {final_status}（初始 {initial_status}）→ ⚠️ 门牌异常形态（变空/非预期改写），退出码=2，务必人工复核！")
    else:
        print(f"[S3]    最终门牌: {final_status}（轮询窗内未观测到落牌 → WARN，按「未翻已投递」放行，建议人工复核 ⚠️）")

    quota_after = _quota_state(quota_file)
    if quota_before is None:
        quota_ok, quota_desc = True, "（显式跳过）"
    else:
        quota_ok = quota_after == quota_before
        quota_desc = "" if quota_ok else f"❌ 指纹变化: {quota_before} -> {quota_after}"
    print(f"[S3] ③ 51job 配额文件零变更: {'✅' if quota_ok else '❌'} {quota_desc}")
    if not quota_ok:
        return 1
    browsers = _count_browser_processes(profile_pattern)
    print(f"[S3] ④ 残留浏览器进程: {browsers} 个（登录检查用途允许，结束应归零）")
    ok = quota_ok and browsers == 0
    if abnormal_status_detected:
        print(f"[S3] 结论: WARN ⚠️（门牌异常改写，退出码=2）")
        return 2
    print(f"[S3] 结论: {'PASS ✅' if ok else 'FAIL ❌'}（门牌落牌: {'是' if is_fail_form else '否-WARN'}）")
    return 0 if ok else 1


def _flat_text(value) -> str:
    """飞书字段值可能是 str / [{text,type}] dict 混合体，拉平成纯文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(str(i.get("text", "")) if isinstance(i, dict) else str(i) for i in value)
    return str(value)


def _quota_state(path: str | None):
    """配额文件指纹。路径缺失/文件不存在/内容非法一律返回 None（由调用方决定 fail-closed）。"""
    import json as _json
    if not path or not Path(path).exists():
        return None
    try:
        return _json.dumps(_json.loads(Path(path).read_text()), sort_keys=True)
    except Exception:
        return None


def _count_browser_processes(pattern: str = DEFAULT_PROFILE_PATTERN) -> int:
    import os as _os
    import subprocess
    try:
        out = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True, text=True, timeout=10)
        me = _os.getpid()
        # pgrep -f 会匹配到携带 pattern 字面值的哨兵进程自身 argv，必须排除
        return len([l for l in out.stdout.splitlines() if l.strip() and int(l.strip()) != me])
    except Exception:
        return -1


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description="指挥中心质检隔离哨兵")
    ap.add_argument("mode", choices=["s1", "s2", "s3"])
    ap.add_argument("--base-url", default="http://127.0.0.1:8017")
    ap.add_argument("--qa-table", default="")
    ap.add_argument("--db", default="")
    ap.add_argument("--budget", type=int, default=30)
    ap.add_argument("--before", type=int, default=None)
    ap.add_argument("--quota-file", default=None)
    ap.add_argument("--allow-no-quota", action="store_true")
    ap.add_argument("--profile-pattern", default=DEFAULT_PROFILE_PATTERN)
    args = ap.parse_args()
    if args.mode == "s2":
        if not args.db:
            sys.exit("s2 模式必须提供 --db（隔离实例的 job_hunter.db 路径）")
        sys.exit(sentry_s2(args.db, args.budget, args.before))
    if not args.qa_table:
        sys.exit("必须提供 --qa-table（QA 测试岗位表 id）")
    # fail-closed：绝不允许把生产表当 QA 表（S3 会向该表写哨兵岗并触发投递编排）
    if args.qa_table in (settings.FEISHU_TABLE_ID_JOBS, settings.FEISHU_TABLE_ID_RESUMES):
        sys.exit(f"❌ --qa-table 不能是生产表（jobs={settings.FEISHU_TABLE_ID_JOBS}, resumes={settings.FEISHU_TABLE_ID_RESUMES}）")
    if args.mode == "s1":
        sys.exit(asyncio.run(sentry_s1(args.base_url, args.qa_table)))
    sys.exit(asyncio.run(sentry_s3(args.base_url, args.qa_table, args.quota_file, args.allow_no_quota, args.profile_pattern)))


if __name__ == "__main__":
    main()
