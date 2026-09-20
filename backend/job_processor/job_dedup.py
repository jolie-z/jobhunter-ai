# -*- coding: utf-8 -*-
"""
疑似重复岗位检测（纯逻辑层，不碰飞书 / 不调 LLM，零 token）
==========================================================
背景：同一家公司常把同一个岗位换个名字（AI 全栈 / AI 应用 / AI 前端工程师）
在多平台重复发布，JD 只做小幅改写。现状的三要素精确去重（公司+岗位名+城市
逐字相等）拦不住这类改名重发，导致每条变体都走一遍 AI 初评甚至高分轨深度
评估，浪费大量 token。

本模块用纯本地文本相似度做判定：
  1. 公司名归一化（剥法律后缀、全半角、括号拆分）→ 同公司分组
  2. 组内两两比对：岗位名 difflib 相似度 + JD 字符 shingle 的 Jaccard 重合率
  3. 双阈值命中 → 判定「疑似重复」，交给编排层标记飞书、复用母本结论

阈值说明：宁可漏判（少省 token）不可误杀（把真岗位错标成重复），
所以每条规则都要求标题与 JD 双信号同时达标；模糊地带留给人工或后续校准。
"""

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

# ==========================================
# 阈值配置（校准脚本 scripts/dedup_calibration.py 可离线验证）
# 2026-08-29 用近 90 天真实数据校准过（城市归一化修复后）：
#   真重复 32 对：k5∈[0.61,1.00] / 包含率∈[0.78,1.00] / seq∈[0.90,1.00]
#   同公司真不同岗位：k5≤0.43 / 包含率≤0.64 / seq≤0.66 —— 间隔充裕
# ==========================================
JD_STRONG = 0.60        # JD 高度重合 + 标题沾边 → 重复
SEQ_STRONG = 0.85       # JD 序列相似度（对散落小改写比 shingle 稳）也可独立扛 JD 强命中
CONT_STRONG = 0.80      # JD 高度包含（专治「母本 JD 多几段」的非对称重发）+ 标题相近 → 重复
CONT_TITLE_FLOOR = 0.55
TITLE_STRONG = 0.72     # 标题高度相似 + JD 中度重合 → 重复
JD_MID = 0.45           # 标题强命中时要求的 JD 最低重合
SAME_TITLE_JD = 0.40    # 标题几乎逐字相同时的 JD 最低重合
TITLE_JD_FLOOR = 0.30   # JD 强命中时允许的标题最低相似（校准：优尼客 0.33 为真重复）
SEQ_PROBE_MIN = 0.30    # k5 落在此区间之下不算 seq（省时且无信号）
SHINGLE_K = 5           # JD 字符 shingle 长度（校准结论：k5 比 k3 区分度更好）
JD_MAX_CHARS = 4000     # 参与 shingle 的 JD 截断长度（超出部分视为改写重灾区，不比）

# 公司名里剥掉的法律/组织后缀（从长到短循环剥）
_COMPANY_SUFFIXES = [
    "股份有限公司", "有限责任公司", "有限公司", "股份公司", "集团公司",
    "分公司", "公司", "集团", "控股",
]
# 岗位名里的纯营销噪音词（剥掉后再比相似度）
_TITLE_NOISE = ["急聘", "急招", "热招", "直招", "最新", "高薪"]

_PAREN_RE = re.compile(r"[（(][^（）()]*[)）]")
_NONWORD_RE = re.compile(r"[^\w]+", re.UNICODE)


# ==========================================
# 归一化
# ==========================================
def normalize_company(name: str) -> str:
    """公司名归一化：全半角统一 → 去括号段 → 去标点空白 → 循环剥法律后缀。

    「华为技术有限公司」「华为（北京）」→ 都归一到可比形态；
    城市前缀等残差靠 is_same_company 的包含匹配兜底。
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name)).strip().lower()
    s = _PAREN_RE.sub("", s)
    s = _NONWORD_RE.sub("", s)
    changed = True
    while changed and s:
        changed = False
        for suffix in _COMPANY_SUFFIXES:
            if s.endswith(suffix) and len(s) - len(suffix) >= 2:
                s = s[: -len(suffix)]
                changed = True
    return s


def normalize_title(title: str) -> str:
    """岗位名归一化：全半角统一 → 去括号段 → 去营销噪音词 → 去标点空白 → 小写。"""
    if not title:
        return ""
    s = unicodedata.normalize("NFKC", str(title)).strip().lower()
    s = _PAREN_RE.sub("", s)
    for noise in _TITLE_NOISE:
        s = s.replace(noise, "")
    s = _NONWORD_RE.sub("", s)
    return s


def normalize_city(city: str) -> str:
    """城市归一化：取分隔符前第一段（城市名）并剥「市/省」后缀。

    跨平台城市粒度不一（「广州·天河·员村」vs「广州」vs「广州市」），
    区县级差异不作为「不同城市」的证据；真实跨市岗位仍能被守卫拦住。
    """
    if not city:
        return ""
    s = unicodedata.normalize("NFKC", str(city)).strip()
    first = re.split(r"[·・\-—_/,,，\s]+", s)[0] or s
    if first.endswith("市") and len(first) > 2:
        first = first[:-1]
    if first.endswith("省") and len(first) > 2:
        first = first[:-1]
    return first


def is_same_company(a: str, b: str) -> bool:
    """同公司判定：归一化后相等，或一方包含另一方（短名 ≥4 字，兜城市前缀/后缀残差）。"""
    na, nb = normalize_company(a), normalize_company(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    return len(short) >= 4 and short in long_


# ==========================================
# 相似度
# ==========================================
def title_similarity(a: str, b: str) -> float:
    """岗位名相似度：归一化后 difflib 序列匹配。"""
    ta, tb = normalize_title(a), normalize_title(b)
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()


def _shingles(text: str, k: int = SHINGLE_K) -> set:
    t = re.sub(r"\s+", "", str(text or ""))[:JD_MAX_CHARS]
    if len(t) < k:
        return set()
    return {t[i: i + k] for i in range(len(t) - k + 1)}


def jd_metrics(a: str, b: str) -> Tuple[float, float]:
    """JD 正文指标一次算两个：(Jaccard 重合率, 包含率=交集/较小集)。

    Jaccard 对两边对称敏感；包含率专治「同一岗位、一份 JD 多几段」的非对称重发
    （多出的文本会稀释 Jaccard，但包含率仍然很高）。
    任一方 JD 过短（<50 字）视为无信号，返回 (0, 0)（宁可漏判不误杀）。
    """
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0, 0.0
    if len(re.sub(r"\s+", "", str(a or ""))) < 50 or len(re.sub(r"\s+", "", str(b or ""))) < 50:
        return 0.0, 0.0
    inter = len(sa & sb)
    if not inter:
        return 0.0, 0.0
    return inter / len(sa | sb), inter / min(len(sa), len(sb))


def jd_similarity(a: str, b: str) -> float:
    """JD 正文重合率（Jaccard）。校准脚本与外部沿用此口径。"""
    return jd_metrics(a, b)[0]


def _jd_seq_ratio(a: str, b: str) -> float:
    """JD 序列相似度（difflib ratio）：对散落式小改写比 shingle 更稳。

    真实数据校准：真重复 ≥0.90，同公司真不同岗位 ≤0.27。带 quick_ratio 剪枝省时。
    """
    ta = "".join(str(a or "").split())[:2000]
    tb = "".join(str(b or "").split())[:2000]
    if len(ta) < 50 or len(tb) < 50:
        return 0.0
    sm = SequenceMatcher(None, ta, tb, autojunk=True)
    if sm.real_quick_ratio() < SEQ_STRONG:
        return 0.0
    if sm.quick_ratio() < SEQ_STRONG:
        return 0.0
    return sm.ratio()


# ==========================================
# 配对判定
# ==========================================
@dataclass
class DupVerdict:
    is_duplicate: bool
    score: float            # 综合相似度（标题 45% + JD 55%），仅用于展示/排序
    title_sim: float
    jd_sim: float
    jd_seq: float = 0.0     # JD 序列相似度（仅在中度重合带才计算）
    reason: str = ""        # 命中规则的中文名，未命中为空
    borderline: bool = False  # 模糊地带（没到重复线但值得人工/校准留意）


def judge_pair(job_a: dict, job_b: dict) -> DupVerdict:
    """判定两个岗位是否疑似重复。字段兼容 company/company_name、job_title/job_name 两种键。"""
    co_a, co_b = _f(job_a, "company", "company_name"), _f(job_b, "company", "company_name")
    ti_a, ti_b = _f(job_a, "job_title", "job_name", "title"), _f(job_b, "job_title", "job_name", "title")
    jd_a, jd_b = _f(job_a, "jd_text", "jd"), _f(job_b, "jd_text", "jd")
    city_a, city_b = _f(job_a, "city"), _f(job_b, "city")

    t = title_similarity(ti_a, ti_b)
    j, c = jd_metrics(jd_a, jd_b)

    # 城市守卫：同岗位不同城市分部是真实的不同岗位（归一化后仍不同 → 不判重）
    na, nb = normalize_city(city_a), normalize_city(city_b)
    if na and nb and na != nb and "未知" not in na and "未知" not in nb:
        return DupVerdict(False, round(0.45 * t + 0.55 * j, 3), t, j, reason="城市不同")

    # 序列相似度只在 k5 中度重合带才算（强命中已够判，弱命中无信号，省时）
    seq = _jd_seq_ratio(jd_a, jd_b) if SEQ_PROBE_MIN <= j < JD_STRONG else 0.0
    jd_strong_hit = j >= JD_STRONG or seq >= SEQ_STRONG
    score = round(0.45 * t + 0.55 * j, 3)

    def verdict(dup: bool, rule: str, borderline: bool = False) -> DupVerdict:
        return DupVerdict(dup, score, t, j, jd_seq=seq, reason=rule, borderline=borderline)

    if jd_strong_hit and t >= TITLE_JD_FLOOR:
        detail = f"JD 重合({j:.0%})" + (f"/序列相似({seq:.0%})" if seq >= SEQ_STRONG else "")
        return verdict(True, f"{detail}且岗位名沾边")
    if t >= TITLE_STRONG and j >= JD_MID:
        return verdict(True, f"岗位名高度相似({t:.0%})且 JD 中度重合({j:.0%})")
    if t >= 0.92 and j >= SAME_TITLE_JD:
        return verdict(True, f"岗位名几乎相同({t:.0%})且 JD 重合({j:.0%})")
    if c >= CONT_STRONG and t >= CONT_TITLE_FLOOR:
        return verdict(True, f"JD 高度包含({c:.0%})且岗位名相近")

    # 模糊地带：没到重复线，但双信号都在爬坡，值得校准脚本留意
    borderline = (j >= 0.50 and t >= 0.30) or (t >= 0.60 and j >= 0.30)
    return verdict(False, "", borderline=borderline)


# ==========================================
# 历史岗位（SQLite raw_jobs，作为母本候选池）
# ==========================================
PARENT_USABLE_STATUSES = {
    # 母本必须已有真实 AI 结论，标记才有意义
    "已完成初步评估", "已完成深度评估", "简历人工复核", "海投人工复核",
    "待投递", "已投递",
}


def load_history_jobs(db_path: str, days: int = 90) -> List[dict]:
    """从 SQLite raw_jobs 拉历史岗位池（有飞书记录 ID 的），近 N 天，按抓取时间倒序。"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    sql = (
        "SELECT feishu_record_id, company_name, job_title, jd_text, platform, job_link, city, crawl_time "
        "FROM raw_jobs "
        "WHERE IFNULL(feishu_record_id, '') != '' AND IFNULL(company_name, '') != '' "
        "AND IFNULL(job_title, '') != ''"
    )
    rows: List[dict] = []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for r in conn.execute(sql):
            crawl = str(r["crawl_time"] or "")
            if days and crawl and crawl < cutoff:
                continue
            rows.append({
                "record_id": r["feishu_record_id"],
                "company": r["company_name"],
                "job_title": r["job_title"],
                "jd_text": r["jd_text"] or "",
                "platform": r["platform"] or "",
                "job_link": r["job_link"] or "",
                "city": r["city"] or "",
                "crawl_time": crawl,
            })
    rows.sort(key=lambda x: x["crawl_time"], reverse=True)
    return rows


def index_history_by_company(history: List[dict]) -> Dict[str, List[dict]]:
    """历史岗位按归一化公司名建索引。"""
    idx: Dict[str, List[dict]] = {}
    for h in history:
        idx.setdefault(normalize_company(h.get("company", "")), []).append(h)
    return idx


def find_company_group(index: Dict[str, List[dict]], company: str) -> List[dict]:
    """取某公司的历史候选：精确归一化命中 + 包含式命中（兜「华为」vs「华为技术」）。"""
    key = normalize_company(company)
    if not key:
        return []
    hits = list(index.get(key, []))
    if len(key) >= 4:
        seen = {id(h) for h in hits}
        for k, group in index.items():
            if k and k != key and len(k) >= 4 and (key in k or k in key):
                for h in group:
                    if id(h) not in seen:
                        seen.add(id(h))
                        hits.append(h)
    return hits


def find_history_parents(
    job: dict,
    history: List[dict],
    max_candidates: int = 6,
) -> List[Tuple[dict, DupVerdict]]:
    """在历史候选里找与 job 疑似重复的母本，按综合相似度从高到低返回（本地层面，不查飞书状态）。

    排除 job 自己（同 record_id / 同链接的行）。调用方按序向飞书核实状态，
    取第一个可用的当母本——最高分的可能还是「新线索」没评过，别卡在它身上。
    """
    self_rid = _f(job, "record_id", "job_id")
    self_link = _f(job, "job_link", "job_url")
    hits: List[Tuple[dict, DupVerdict]] = []
    checked = 0
    for cand in history:
        if checked >= max_candidates:
            break
        if self_rid and cand.get("record_id") == self_rid:
            continue
        if self_link and cand.get("job_link") and cand["job_link"] == self_link:
            continue
        checked += 1
        v = judge_pair(job, cand)
        if v.is_duplicate:
            hits.append((cand, v))
    hits.sort(key=lambda x: x[1].score, reverse=True)
    return hits


# ==========================================
# 批次内聚类（同一批新岗位里互为变体的，只评一条代表）
# ==========================================
def group_batch_by_company(jobs: List[dict]) -> List[Tuple[str, List[dict]]]:
    """批次岗位按归一化公司名分组。组内代表排最前：JD 最全优先，其次最新。"""
    groups: Dict[str, List[dict]] = {}
    order: List[str] = []
    for job in jobs:
        key = normalize_company(_f(job, "company", "company_name"))
        if not key:
            key = f"__unknown__{len(order)}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(job)
    out = []
    for key in order:
        members = groups[key]
        members.sort(
            key=lambda j: (
                -len(re.sub(r"\s+", "", str(_f(j, "jd_text", "jd") or ""))),
                -float(_f(j, "_created_time", "created_time") or 0),
            )
        )
        out.append((key, members))
    return out


# ==========================================
# 小工具
# ==========================================
def _f(job: dict, *keys: str) -> str:
    """多键名取值（兼容批次 dict / 历史行 / 飞书 lead 的字段名差异）。"""
    for k in keys:
        v = job.get(k)
        if v:
            return v
    return ""


def build_dup_note(
    parent_title: str,
    parent_platform: str,
    parent_link: str,
    verdict: DupVerdict,
    parent_grade: str = "",
    parent_rationales: str = "",
) -> str:
    """组装写入重复岗位「AI评估详情」的说明文本（母本信息 + 相似度 + 可选母本结论）。"""
    lines = [
        f"⚠️ 疑似重复岗位（综合相似度 {verdict.score:.0%}，{verdict.reason}）",
        f"母本岗位：{parent_title or '（未知）'}" + (f"（{parent_platform}）" if parent_platform else ""),
        f"母本链接：{parent_link or '（未记录）'}",
    ]
    if parent_grade:
        lines.append(f"母本 AI 初评结论（综合评级 {parent_grade}）：")
        if parent_rationales:
            lines.append(parent_rationales)
    else:
        lines.append("母本结论待回填：母本若在本轮完成评估，此处会自动补上其初评结论。")
    return "\n".join(lines)
