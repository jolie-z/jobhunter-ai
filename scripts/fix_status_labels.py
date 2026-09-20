#!/usr/bin/env python3
"""
门牌双轨数据校正
================
把低评级（C/D/F）却挂着「简历人工复核」的岗位批量校正为「海投人工复核」。

例外规则：带真实深度改写产物（AI改写JSON > 50 字）的岗位保持不动——
它们经过精投轨处理、有定制简历待复核，挂「简历人工复核」语义正确。

背景：2026-08-29 门牌双头事故——8月26日 门牌双轨化（204a409）之前，
所有审批断点统一写「简历人工复核」，导致 282 条低分岗门牌错挂。

用法:
  python scripts/fix_status_labels.py --dry-run    # 只出清单（默认）
  python scripts/fix_status_labels.py --execute    # 执行校正
"""
import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from dotenv import load_dotenv

load_dotenv(REPO / "backend" / ".env", override=False)

from app.core.config import settings  # noqa: E402
from app.core.feishu_client import feishu_client  # noqa: E402
from app.core.feishu_utils import extract_feishu_text as _txt  # noqa: E402
from app.services.feishu_service import update_feishu_record  # noqa: E402


async def main(dry: bool):
    records = await feishu_client.fetch_bitable_records(settings.FEISHU_TABLE_ID_JOBS)
    to_fix, keep = [], []
    for r in records:
        f = r.get("fields", {})
        grade = (_txt(f.get("综合评级 (A-F)", "")) or "").strip()
        st = (_txt(f.get("跟进状态", "")) or "").strip()
        if grade in ("C", "D", "F") and st == "简历人工复核":
            j = _txt(f.get("AI改写JSON", "")) if f.get("AI改写JSON") else ""
            row = (
                r["record_id"],
                grade,
                (_txt(f.get("招聘平台", "")) or "")[:6],
                (_txt(f.get("公司名称", "")) or "")[:12],
                (_txt(f.get("岗位名称", "")) or "")[:18],
                len(j),
            )
            (keep if len(j) > 50 else to_fix).append(row)

    print(f"待校正 {len(to_fix)} 条 → 海投人工复核 | 保留（有定制产物）{len(keep)} 条\n")
    for rid, g, p, c, t, _jl in to_fix:
        print(f"  {rid} | {g} | {p} | {c} | {t}")
    if keep:
        print("\n保留样本（前 5，全部保留）:")
        for rid, g, p, c, t, jl in keep[:5]:
            print(f"  {rid} | {g} | {p} | {c} | {t} | 改写{jl}字")

    if dry:
        print(f"\n(dry-run: 未执行任何写入，共将校正 {len(to_fix)} 条)")
        return

    ok = fail = 0
    for rid, *_ in to_fix:
        try:
            success = await asyncio.to_thread(
                update_feishu_record, rid, {"跟进状态": "海投人工复核"}
            )
            if success:
                ok += 1
            else:
                fail += 1
                print(f"  ❌ {rid}: 更新返回失败")
        except Exception as e:
            fail += 1
            print(f"  ❌ {rid}: {str(e)[:60]}")
    print(f"\n校正完成: 成功 {ok} / 失败 {fail}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="真正执行写入（默认 dry-run）")
    args = ap.parse_args()
    asyncio.run(main(dry=not args.execute))
