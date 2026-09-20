#!/usr/bin/env python3
"""
存量「新线索」疑似重复回填脚本
==============================
把现存积压的新线索岗位过一遍查重关卡，把疑似重复的标记为「疑似重复」并写判断书
（与自动链路同一套判定与标记格式）。默认 dry-run 只出清单不写飞书：

  python scripts/backfill_mark_duplicates.py             # dry-run：只看清单
  python scripts/backfill_mark_duplicates.py --apply     # 实际标记飞书
"""
import argparse
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

load_dotenv(BACKEND / ".env", override=False)


async def main(apply: bool):
    from job_processor import job_dedup
    from app.services.feishu_service import get_new_leads_from_feishu
    from app.services.job_dedup_gate import run_dedup_gate

    leads = await asyncio.to_thread(get_new_leads_from_feishu)
    print(f"📥 现存「新线索」岗位: {len(leads)} 条\n")
    if not leads:
        return

    # 新线索记录已经是关卡需要的全部字段（company/job_title/jd_text/city/platform/job_url/record_id）
    def log(msg):
        print(msg)

    kept, marked, pairs = await run_dedup_gate(leads, log=log, dry_run=not apply)

    print(f"\n{'✅ 已标记' if apply else '🔍 dry-run（未写飞书，加 --apply 实际标记）'}: "
          f"疑似重复 {len(marked)} 条（其中批次内变体 {len(pairs)} 条待母本评估后回填结论），"
          f"独立岗位 {len(kept)} 条")
    for m in marked:
        j, p = m["job"], m["parent"]
        print(f"   [{m['kind']}] {j.get('company', '')[:18]} 《{j.get('job_title', '')[:24]}》"
              f" ≈ 《{(p.get('job_title') or p.get('job_name') or '')[:24]}》 相似度 {m['verdict'].score:.0%}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际写飞书（默认 dry-run 只出清单）")
    args = ap.parse_args()
    asyncio.run(main(args.apply))
