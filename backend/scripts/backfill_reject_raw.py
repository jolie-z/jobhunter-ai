#!/usr/bin/env python
"""存量回填：飞书 E/F 初评淘汰岗 → raw_jobs 回写 REJECT_AI（2026-11-02 审计 P1-6）。

修复前 wave 链初评 F 只写飞书不回写 raw，存量淘汰岗的 raw 行仍是归档 guard
不认识的流转态（如实测 '已进行打分'），回收站「确认淘汰」必然 409。本脚本按
岗位链接字段中的网页 URL（extract_feishu_text 对 url 型字段提取 link，与运行时
wave_pipeline 同一提取函数）关联 raw_jobs 回填，幂等。

CR-R1-P4 修正：原版 _plain 对飞书 url 型字段（{link,text,type}）做 str() 序列化
导致 1900 条全部匹配失败；现统一复用 extract_feishu_text。apply 语义与运行时
服务（sync_eval_reject_to_raw）完全同源。

用法（backend 目录下）：
  .venv/bin/python scripts/backfill_reject_raw.py            # dry-run：只打印命中清单，不写库
  .venv/bin/python scripts/backfill_reject_raw.py --apply    # 实际回写（走服务函数，幂等）
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3  # noqa: E402
from urllib.parse import urlencode  # noqa: E402

from app.core.feishu_utils import POST_DELIVERY_FOLLOW_STATUSES, extract_feishu_text  # noqa: E402
from app.core.process_status import EVAL_REJECT_WRITABLE_STATUSES  # noqa: E402


def _feishu_headers() -> dict:
    from app.services.feishu_service import get_tenant_access_token
    return {"Authorization": f"Bearer {get_tenant_access_token()}", "Content-Type": "application/json"}


def fetch_eval_rejected_jobs() -> tuple[list[dict], bool]:
    """拉取飞书岗位表中 评级∈{E,F} 的记录（分页 500/页，复用待审批查询同款字段）。"""
    from app.core.config import settings
    app_token, table_id = settings.FEISHU_APP_TOKEN, settings.FEISHU_TABLE_ID_JOBS
    base_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
    out: list[dict] = []
    seen_record_ids: set[str] = set()
    page_token = ""
    pages = 0
    exhausted = True
    incomplete_reason = "page_cap"
    # _plain 提到循环外（CR-R2-P2）：仅展示用；链接字段一律走 extract_feishu_text 提取 link
    def _plain(v):
        if isinstance(v, list):
            return "".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in v)
        return str(v or "")

    for _ in range(500):
        pages += 1
        # 🌟 分页参数必须放 URL query（CR-R2-P1-A 实测：放 body 会被忽略，每页重复首页，
        # 95 条 E/F × 页数 = 虚假总数；query 传参后翻页零重复）；空 token 不携带参数
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        url = base_url + "?" + urlencode(params)
        req = urllib.request.Request(url, data=b"{}", headers=_feishu_headers(), method="POST")
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = json.loads(resp.read().decode())
        if raw.get("code") != 0:
            raise RuntimeError(f"飞书 API 错误 code={raw.get('code')}: {str(raw.get('msg') or raw.get('message'))[:120]}")
        data = raw.get("data") or {}
        items = data.get("items", [])
        page_ids = {i.get("record_id", "") for i in items}
        dup = seen_record_ids & page_ids
        if dup:
            raise RuntimeError(f"分页异常：第 {pages} 页与之前重复 {len(dup)} 条 record_id，page_token 失效，终止以免虚增")
        seen_record_ids |= page_ids
        for item in items:
            fields = item.get("fields", {})
            grade = extract_feishu_text(fields.get("综合评级 (A-F)", "")).strip().upper()
            if grade in ("E", "F"):
                follow = extract_feishu_text(fields.get("跟进状态", "")).strip()
                # 防御：已进入投递/面试后段的岗位不打淘汰标（评级为历史残留的场景）
                if follow in POST_DELIVERY_FOLLOW_STATUSES:
                    continue
                out.append({
                    "record_id": item.get("record_id", ""),
                    "company": _plain(fields.get("公司名称", "")),
                    "job_name": _plain(fields.get("岗位名称", "")),
                    "grade": grade,
                    "job_link": extract_feishu_text(fields.get("岗位链接", "")).strip(),
                })
        page_token = data.get("page_token", "")
        if not data.get("has_more"):
            exhausted = False
            break
        if not page_token:
            # has_more=True 却无 token：数据没拉全，保持 exhausted 以禁止 --apply
            incomplete_reason = "no_token"
            break
    if exhausted:
        reason_txt = "上游 has_more=True 但未返回 page_token" if incomplete_reason == "no_token" else "达 500 页上限"
        print(f"⚠️ 分页不完整（{reason_txt}，{pages} 页 / 唯一记录 {len(seen_record_ids)}），结果可能不完整")
    return out, exhausted


def run_backfill(jobs: list[dict], conn: sqlite3.Connection, apply_mode: bool,
                 service, quiet: bool = False) -> dict:
    """按行口径核验与回填主循环（CR-R3-P1）。

    - 核验：每个链接 COUNT 白名单内待回写行数，不以首行状态代表整组——同链接多行
      raw 中首行已淘汰、其余行仍待回写的历史场景（老清洗链路只标过其中一行）只有
      按行统计才能发现。
    - 回填：命中链接无条件调用服务（不受任何单行状态影响），按返回 rowcount 精确
      计数；同链接重复 record 由 seen_links 去重，行数不虚增（CR-R4-P2）。
    返回计数器 dict（单位：链接 / 行，分别可考）。
    """
    placeholders = ",".join("?" for _ in EVAL_REJECT_WRITABLE_STATUSES)
    stats = {"matched_links": 0, "writable_rows": 0, "written_rows": 0,
             "skipped_clean": 0, "skipped_missing": 0, "skipped_dup": 0}
    seen_links: set[str] = set()
    printed = 0
    for j in jobs:
        link = str(j.get("job_link") or "").strip()
        if not link:
            stats["skipped_missing"] += 1
            if not quiet:
                print(f"  ⏭️ 无链接，跳过: {j.get('company', '')} - {j.get('job_name', '')} ({j.get('record_id', '')})")
            continue
        if link in seen_links:
            stats["skipped_dup"] += 1
            continue
        seen_links.add(link)
        writable = conn.execute(
            f"SELECT COUNT(*) FROM raw_jobs WHERE job_link = ? AND process_status IN ({placeholders})",
            (link, *EVAL_REJECT_WRITABLE_STATUSES),
        ).fetchone()[0]
        if writable == 0:
            # 三种情况合一：无匹配行 / 已全部回写（ai清洗淘汰+存量回填标记）/ 白名单外
            # 非淘汰态（如已放弃、待投递）。需要细分时按 process_status GROUP BY 查询。
            stats["skipped_clean"] += 1
            continue
        stats["matched_links"] += 1
        stats["writable_rows"] += writable
        if not quiet:
            if printed < 30:
                print(f"  🎯 [{j.get('grade', '')}级] {j.get('company', '')} - {j.get('job_name', '')} | 待回写行数={writable}")
                printed += 1
            elif printed == 30:
                print("  …（其余命中省略，仅计数）")
                printed = 31
        if apply_mode:
            # 无条件调用服务（服务自带白名单守卫），按 rowcount 精确计数
            stats["written_rows"] += service(link, f"存量回填：初评{j.get('grade', '')}级淘汰")
    return stats


def main() -> None:
    apply_mode = "--apply" in sys.argv
    jobs, exhausted = fetch_eval_rejected_jobs()
    print(f"飞书 E/F 淘汰岗共 {len(jobs)} 条（唯一 record 计数）\n")

    import os
    from app.core.db_paths import job_hunter_db_path
    from app.automation.services.reject_sync_service import sync_eval_reject_to_raw

    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    conn = sqlite3.connect(job_hunter_db_path(os.path.join(PROJECT_ROOT, "data", "job_hunter.db")), timeout=30.0)
    # 分页不完整时禁止 --apply（CR-R3-P2）：不完整数据上批量写库风险不可控
    if apply_mode and exhausted:
        print("⛔ 分页未拉全（见上方警告），--apply 已中止；请提高分页上限后重试")
        conn.close()
        return

    stats = run_backfill(jobs, conn, apply_mode, sync_eval_reject_to_raw)
    conn.close()
    mode = "已回写" if apply_mode else "DRY-RUN（未写库，加 --apply 执行）"
    applied = stats["written_rows"] if apply_mode else 0
    print(f"\n命中链接 {stats['matched_links']}（待回写行 {stats['writable_rows']}）| 已清零链接 {stats['skipped_clean']} "
          f"| 同链接重复 record 跳过 {stats['skipped_dup']} | 无链接 {stats['skipped_missing']} | {mode} {applied} 行")
    if not apply_mode:
        print("（口径说明：命中=存在白名单内待回写行的唯一链接；行数=按行核验的真实待回写量；"
              "已清零=无匹配行 / 已全部回写 / 白名单外非淘汰态三种情况合计）")


if __name__ == "__main__":
    main()
