#!/usr/bin/env python3
"""
疑似重复岗位检测 · 离线校准脚本（只读，不碰飞书、不调 LLM）
==========================================================
用 SQLite raw_jobs 里的真实历史岗位，把「同公司岗位对」的多种相似度指标
全部算出来落盘 CSV，并按当前 job_dedup 阈值给出判定分布，供人工抽查与调阈值：

  python scripts/dedup_calibration.py                  # 近 90 天，默认输出
  python scripts/dedup_calibration.py --days 30 --limit 50

输出：
  1) stdout：分组统计 + 判定为「疑似重复」的组摘要 + 模糊地带对
  2) scripts/dedup_calibration_pairs.csv：全部同公司岗位对的明细指标
"""
import argparse
import csv
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

from job_processor import job_dedup
from job_processor.job_dedup import (
    DupVerdict,
    group_batch_by_company,
    is_same_company,
    jd_similarity,
    judge_pair,
    load_history_jobs,
    title_similarity,
)

RAW_DB = BACKEND / "data" / "job_hunter.db"
CSV_OUT = REPO / "scripts" / "dedup_calibration_pairs.csv"


def seq_ratio_jd(a: str, b: str) -> float:
    """difflib 序列相似度（对散落小改写比 shingle 更稳），只在 shingle 有苗头时才算（省时）。"""
    from difflib import SequenceMatcher
    ta = "".join(str(a or "").split())[:2000]
    tb = "".join(str(b or "").split())[:2000]
    if len(ta) < 50 or len(tb) < 50:
        return 0.0
    sm = SequenceMatcher(None, ta, tb, autojunk=True)
    if sm.real_quick_ratio() < 0.3:
        return 0.0
    if sm.quick_ratio() < 0.3:
        return 0.0
    return sm.ratio()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90, help="历史岗位回看天数")
    ap.add_argument("--max-pairs", type=int, default=20000, help="最多计算的岗位对数（防跑飞）")
    ap.add_argument("--limit", type=int, default=25, help="stdout 摘要里最多打印的重复组数")
    args = ap.parse_args()

    t0 = time.time()
    jobs = load_history_jobs(str(RAW_DB), days=args.days)
    print(f"📦 历史岗位池: {len(jobs)} 条（近 {args.days} 天，含飞书记录 ID）")

    groups = group_batch_by_company(jobs)
    multi = [(k, m) for k, m in groups if len(m) >= 2]
    print(f"🏢 归一化公司组: {len(groups)} 组，其中 ≥2 岗位的 {len(multi)} 组")

    rows = []
    dup_pairs = []
    borderline_pairs = []
    pair_budget = args.max_pairs
    for key, members in multi:
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                if pair_budget <= 0:
                    break
                pair_budget -= 1
                a, b = members[i], members[j]
                t = title_similarity(
                    job_dedup._f(a, "job_title", "job_name"), job_dedup._f(b, "job_title", "job_name"))
                j5 = jd_similarity(a.get("jd_text", ""), b.get("jd_text", ""))
                j3 = job_dedup._shingles(a.get("jd_text", ""), 3)
                j3b = job_dedup._shingles(b.get("jd_text", ""), 3)
                inter = len(j3 & j3b)
                j3s = round(inter / len(j3 | j3b), 3) if inter and len(j3) and len(j3b) else 0.0
                # 包含率：交集/较小集 —— 捕捉「同一岗位、一份 JD 多几段」的非对称重发
                k5a = job_dedup._shingles(a.get("jd_text", ""), 5)
                k5b = job_dedup._shingles(b.get("jd_text", ""), 5)
                inter5 = len(k5a & k5b)
                cont5 = round(inter5 / max(1, min(len(k5a), len(k5b))), 3) if inter5 else 0.0
                sr = seq_ratio_jd(a.get("jd_text", ""), b.get("jd_text", ""))
                v = judge_pair(a, b)
                row = {
                    "company": a.get("company", ""),
                    "title_a": a.get("job_title", "") or a.get("job_name", ""),
                    "title_b": b.get("job_title", "") or b.get("job_name", ""),
                    "platform_a": a.get("platform", ""),
                    "platform_b": b.get("platform", ""),
                    "city_a": a.get("city", ""),
                    "city_b": b.get("city", ""),
                    "time_a": a.get("crawl_time", ""),
                    "time_b": b.get("crawl_time", ""),
                    "title_sim": round(t, 3),
                    "jd_jaccard_k5": round(j5, 3),
                    "jd_containment_k5": cont5,
                    "jd_jaccard_k3": j3s,
                    "jd_seqratio": round(sr, 3),
                    "is_dup": v.is_duplicate,
                    "borderline": v.borderline,
                    "reason": v.reason,
                    "link_a": a.get("job_link", ""),
                    "link_b": b.get("job_link", ""),
                }
                rows.append(row)
                if v.is_duplicate:
                    dup_pairs.append(row)
                elif v.borderline:
                    borderline_pairs.append(row)

    with open(CSV_OUT, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["company"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n🧮 同公司岗位对共 {len(rows)} 对（耗时 {time.time()-t0:.1f}s），明细已写入: {CSV_OUT}")

    # ── 按当前阈值的判定分布 ──
    dup_groups: dict = {}
    for r in dup_pairs:
        dup_groups.setdefault(r["company"], []).append(r)
    print(f"\n✅ 判定【疑似重复】{len(dup_pairs)} 对，涉及 {len(dup_groups)} 家公司")

    for co, pairs in list(dup_groups.items())[: args.limit]:
        print(f"\n—— {co} ——")
        seen = set()
        for r in pairs:
            key = (r["title_a"], r["title_b"], r["platform_a"], r["platform_b"])
            if key in seen:
                continue
            seen.add(key)
            print(f"   [{r['platform_a']}|{r['platform_b']}] {r['title_a']}  ⟷  {r['title_b']}"
                  f"   标题{r['title_sim']:.2f} k5={r['jd_jaccard_k5']:.2f} k3={r['jd_jaccard_k3']:.2f} seq={r['jd_seqratio']:.2f}"
                  f"  {r['reason']}")
    if len(dup_groups) > args.limit:
        print(f"   ……其余 {len(dup_groups) - args.limit} 家公司见 CSV（is_dup=1）")

    # ── 模糊地带：阈值调参最该看的地方 ──
    borderline_pairs.sort(key=lambda r: max(r["jd_jaccard_k5"], r["jd_jaccard_k3"], r["jd_seqratio"]), reverse=True)
    print(f"\n🟡 模糊地带（未判重但双信号爬坡）{len(borderline_pairs)} 对，按最高 JD 指标排序（前 20）:")
    for r in borderline_pairs[:20]:
        print(f"   {r['company']} | [{r['platform_a']}|{r['platform_b']}] {r['title_a']} ⟷ {r['title_b']}"
              f"   标题{r['title_sim']:.2f} k5={r['jd_jaccard_k5']:.2f} k3={r['jd_jaccard_k3']:.2f} seq={r['jd_seqratio']:.2f}")


if __name__ == "__main__":
    main()
