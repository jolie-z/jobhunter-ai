"""7.4 双源对账脚本（质检计划 P1 项）：飞书「跟进状态」vs SQLite raw_jobs「process_status」。

只读工具：不对任何一端写入。输出四类矛盾/异常计数与明细（docs/qa/reconcile-report-<ts>.json）。

字段映射表（2026-09-19 经验普查锚定，1859 条飞书 / 3075 条 raw）：
  飞书跟进状态            SQLite process_status 合法域
  None/空(流程态不在飞书)  已同步 / 已进行打分 / 待推送至飞书 / 已存入数据 / 淘汰类 —— 均正常
  新线索                  已同步
  简历人工复核/海投人工复核/待投递/已投递/投递失败   已同步 或 已进行打分（不得为淘汰类/未同步类）
  已拒绝                  已同步 或 已进行打分（仅全部岗位列表归档）
  清洗淘汰/ai清洗淘汰      清洗淘汰 / ai清洗淘汰
矛盾判定：
  A orphan_link        raw 引用的 feishu_record_id 在飞书表不存在（死链）
  B rejected_but_flow  raw 已淘汰（清洗淘汰/ai清洗淘汰/已确认淘汰）但飞书门牌在流转态
  C never_synced_flow  raw 从未同步（已存入数据/待推送至飞书）但飞书门牌在流转态
  D feishu_unlinked    飞书记录未被任何 raw 行引用（信息项：极速录入/手工记录属正常来源）

用法：backend/ 下  python scripts/reconcile_feishu_sqlite.py [--report docs/qa/]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.core.feishu_client import feishu_client  # noqa: E402

FLOW_STATES = {"新线索", "简历人工复核", "海投人工复核", "待投递", "已投递", "投递失败", "已完成初步评估", "已深度初步评估"}
REJECTED_RAW = ("清洗淘汰", "ai清洗淘汰", "已确认淘汰")
UNSYNCED_RAW = ("已存入数据", "待推送至飞书")


def flat(v) -> str:
    """飞书字段值拉平为纯文本；None 显式映射为「（空）」避免 str(None) 污染词表。"""
    if v is None:
        return "（空）"
    if isinstance(v, list):
        return "".join(str(i.get("text", "")) if isinstance(i, dict) else str(i) for i in v)
    return str(v)


async def fetch_feishu_statuses() -> dict[str, str]:
    token = await feishu_client.get_tenant_access_token()
    base = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}"
        f"/tables/{settings.FEISHU_TABLE_ID_JOBS}/records/search?page_size=500"
    )
    out: dict[str, str] = {}
    url = base
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30) as c:
        while url:
            r = (await c.post(url, json={})).json()
            if r.get("code") != 0:
                raise RuntimeError(f"飞书 search 失败: {r.get('code')} {r.get('msg')}")
            for it in (r.get("data") or {}).get("items") or []:
                out[it["record_id"]] = flat(it.get("fields", {}).get("跟进状态"))
            pg = (r.get("data") or {}).get("page_token")
            url = base + f"&page_token={pg}" if pg else None
    return out


def load_raw_rows(db_path: str) -> list[tuple[str, str]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT feishu_record_id, process_status FROM raw_jobs WHERE feishu_record_id != ''"
        ).fetchall()
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(Path(__file__).resolve().parents[1] / "data" / "job_hunter.db"))
    ap.add_argument("--report-dir", default=str(Path(__file__).resolve().parents[2] / "docs" / "qa"))
    args = ap.parse_args()

    feishu = asyncio.run(fetch_feishu_statuses())
    raw_rows = load_raw_rows(args.db)

    raw_by_rid: dict[str, list[str]] = {}
    for rid, status in raw_rows:
        raw_by_rid.setdefault(rid, []).append(status)

    anomalies = {"A_orphan_link": [], "B_rejected_but_flow": [], "C_never_synced_flow": []}
    consistency: Counter = Counter()
    for rid, f_status in feishu.items():
        statuses = raw_by_rid.get(rid)
        if not statuses:
            consistency["D_feishu_unlinked"] += 1
            continue
        raw_status = statuses[0]
        key = (raw_status, f_status)
        if f_status in FLOW_STATES or f_status == "已拒绝":
            if raw_status in REJECTED_RAW:
                anomalies["B_rejected_but_flow"].append({"record_id": rid, "raw": raw_status, "feishu": f_status})
            elif raw_status in UNSYNCED_RAW:
                anomalies["C_never_synced_flow"].append({"record_id": rid, "raw": raw_status, "feishu": f_status})
            else:
                consistency[f"OK {raw_status} ↔ {f_status}"] += 1
        else:
            consistency[f"OK {raw_status} ↔ {f_status or '（空）'}"] += 1

    for rid, statuses in raw_by_rid.items():
        if rid not in feishu:
            anomalies["A_orphan_link"].append({"record_id": rid, "raw": statuses[0]})

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "feishu_total": len(feishu),
        "raw_total_with_link": len(raw_rows),
        "feishu_status_distribution": dict(Counter(feishu.values()).most_common()),
        "anomaly_counts": {k: len(v) for k, v in anomalies.items()},
        "anomaly_details": {k: v[:50] for k, v in anomalies.items() if v},
        "consistency_matrix_top": dict(consistency.most_common(15)),
        "mapping_table": {
            "None/空 ↔ 已同步/已进行打分/待推送/已存入/淘汰类": "正常（流程态主要存 SQLite+内存，设计形态）",
            "流转态门牌 ↔ 淘汰类 process_status": "矛盾（B）",
            "流转态门牌 ↔ 未同步类 process_status": "矛盾（C）",
            "raw 引用 id 不在飞书": "死链（A）",
        },
    }
    out_dir = Path(args.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"reconcile-report-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"飞书 {report['feishu_total']} 条 / raw 带链 {report['raw_total_with_link']} 条")
    print(f"矛盾计数: {report['anomaly_counts']}")
    print(f"一致性矩阵 TOP: {dict(consistency.most_common(8))}")
    print(f"报告: {out_file}")
    # 对账结论判据：A/B/C 三类矛盾均应为 0；D 为信息项（极速录入来源）
    bad = sum(len(v) for k, v in anomalies.items() if k != "D_feishu_unlinked")
    print("对账结论:", "PASS ✅ 无状态分裂" if bad == 0 else f"FAIL ❌ {bad} 条矛盾待查")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
