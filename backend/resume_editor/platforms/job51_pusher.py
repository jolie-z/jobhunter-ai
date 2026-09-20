"""
前程无忧(51job) - 简历数据推送脚本
统一转发至 job51_write_back.py 真实 API 回写引擎
"""

import sys
import os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
from job51_write_back import run_write_back, main

if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    as_json = "--json" in sys.argv
    paths = None
    for i, a in enumerate(sys.argv):
        if (a in ("--paths", "--modules")) and i + 1 < len(sys.argv):
            paths = [p.strip() for p in sys.argv[i + 1].split(",") if p.strip()]
    result = run_write_back(dry_run=dry, selected_paths=paths)
    if as_json:
        import json
        print("RESULT_JSON:" + json.dumps(result, ensure_ascii=False))
    if dry:
        sys.exit(0)
    ok_all = all(r.get("ok") for r in result.get("results", []))
    verify_bad = [v for v in result.get("verify", []) if not v.get("match")]
    sys.exit(0 if ok_all and not verify_bad else 2)
