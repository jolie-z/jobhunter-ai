"""
疑似重复岗位关卡（所有评估路径共用的前置闸门）
================================================
自动全链路（full_auto）和手动批量评估（tasks/service，含 ChatOps/工作台/Copilot）
在评估前统一过这道关卡：同公司改名/跨平台重发的变体被标记「疑似重复」并从
评估批次剔除，母本结论抄送给副本，全部零 token。

设计约定（与 full_auto 原实现一致）：
- fail-open：关卡自身异常或单条标记失败，岗位照常进评估，绝不因去重误杀
- 人工放行白名单：用户把「疑似重复」改回其他状态即视为复核放行，之后
  任何关卡不再拦它（见 record_dedup_override）
- dry_run：只判定不写飞书（存量回填脚本用它先出清单）
"""

import asyncio
import inspect
import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from job_processor import job_dedup

logger = logging.getLogger(__name__)

RAW_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "job_hunter.db"
)

# 人工放行白名单（record_id 列表）。放在 data/ 下与其它运行时数据同目录。
_OVERRIDES_PATH = Path(RAW_DB_PATH).parent / "dedup_overrides.json"


def record_dedup_override(record_id: str) -> bool:
    """记录一次人工放行：该岗位此后不再被任何查重关卡拦截。"""
    if not record_id:
        return False
    try:
        overrides = _load_overrides()
        if record_id in overrides:
            return True
        overrides.add(record_id)
        _OVERRIDES_PATH.write_text(
            json.dumps(sorted(overrides), ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"🙋 [去重关卡] 人工复核放行，已加入白名单: {record_id}")
        return True
    except Exception as e:
        logger.warning(f"[去重关卡] 白名单写入失败（不影响主流程）: {e}")
        return False


def load_overrides() -> set:
    return _load_overrides()


def _load_overrides() -> set:
    try:
        return set(json.loads(_OVERRIDES_PATH.read_text(encoding="utf-8")))
    except Exception:
        return set()


async def _notify(log: Callable | None, msg: str) -> None:
    """日志回调统一出口：支持同步/异步 callable，异常吞掉不影响关卡。"""
    if log is None:
        return
    try:
        res = log(msg)
        if inspect.isawaitable(res):
            await res
    except Exception:
        pass


def _parent_status_usable(parent_record: dict[str, Any] | None) -> bool:
    """母本可用 = 飞书上已有真实 AI 结论的状态（新线索/淘汰/已下架/已拒绝都不算）。"""
    from app.core.feishu_utils import extract_feishu_text
    status = extract_feishu_text((parent_record or {}).get("fields", {}).get("跟进状态", ""))
    return status in job_dedup.PARENT_USABLE_STATUSES


async def _mark_duplicate(
    record: dict[str, Any],
    parent_title: str,
    parent_platform: str,
    parent_link: str,
    verdict,
    log: Callable | None = None,
    dry_run: bool = False,
    parent_grade: str = "",
    parent_rationales: str = "",
) -> bool:
    """把重复岗位标记为「疑似重复」并写明母本信息；已有结论的母本顺带抄送其初评结论。"""
    from app.services.feishu_service import update_feishu_record

    rid = record.get("record_id", "")
    if not rid:
        return False
    if dry_run:
        await _notify(log, f"[dry-run] 将标记疑似重复: {job_dedup._f(record, 'company', 'company_name')} "
                           f"{job_dedup._f(record, 'job_title', 'job_name')[:24]} ≈《{parent_title}》")
        return True
    note = job_dedup.build_dup_note(
        parent_title=parent_title,
        parent_platform=parent_platform,
        parent_link=parent_link,
        verdict=verdict,
        parent_grade=parent_grade,
        parent_rationales=parent_rationales,
    )
    ok = await asyncio.to_thread(
        update_feishu_record, rid, {"跟进状态": "疑似重复", "AI评估详情": note})
    if ok:
        await _notify(
            log,
            f"🧬 疑似重复: {job_dedup._f(record, 'company', 'company_name')} "
            f"{job_dedup._f(record, 'job_title', 'job_name')[:24]} "
            f"≈《{parent_title}》(相似度 {verdict.score:.0%})，跳过评估留给人工")
    else:
        logger.warning(f"[去重关卡] 疑似重复标记失败，岗位照常评估: {rid}")
    return ok


def _extract_text(field_val: Any) -> str:
    """飞书字段值 → 纯文本（兼容富文本结构 / 纯字符串）。"""
    from app.core.feishu_utils import extract_feishu_text
    try:
        return extract_feishu_text(field_val) or ""
    except Exception:
        return str(field_val or "")


async def run_dedup_gate(
    records: list[dict[str, Any]],
    *,
    log: Callable | None = None,
    dry_run: bool = False,
    history_days: int = 90,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """评估前查重关卡：批次内聚类 + 对历史池查重（均纯本地相似度，零 token）。

    - 命中「历史母本」（此前已评估过）：标记并把母本初评结论抄过去
    - 命中「本批母本」（同批变体只评 JD 最全的一条代表）：标记并登记待回填
    - 人工放行白名单里的岗位直接通过
    返回 (放行进评估的岗位, 被标记的重复岗位, 待回填的批次内母子对)。
    """
    from app.automation.db import get_autopilot_config
    from app.services.feishu_service import TABLE_ID, get_job_record_from_feishu

    if not records or not get_autopilot_config().get("enable_job_dedup", True):
        return records, [], []

    try:
        overrides = _load_overrides()
    except Exception:
        overrides = set()

    history = await asyncio.to_thread(job_dedup.load_history_jobs, RAW_DB_PATH, history_days)
    if not history:
        return records, [], []
    index = job_dedup.index_history_by_company(history)
    batch_rids = {r.get("record_id") for r in records if r.get("record_id")}

    parent_record_cache: dict[str, dict[str, Any] | None] = {}

    async def _fetch_parent_record(rid: str):
        if rid not in parent_record_cache:
            try:
                parent_record_cache[rid] = await asyncio.to_thread(
                    get_job_record_from_feishu, rid, TABLE_ID)
            except Exception as e:
                logger.warning(f"[去重关卡] 拉取母本记录失败 {rid}: {e}")
                parent_record_cache[rid] = None
        return parent_record_cache[rid]

    kept: list[dict[str, Any]] = []
    kept_keys: list[str] = []
    marked: list[dict[str, Any]] = []
    pending_pairs: list[dict[str, Any]] = []
    n_hist = n_batch = n_override = 0
    for record in records:
        rid = record.get("record_id", "")
        # 人工已复核放行的岗位不再拦
        if rid and rid in overrides:
            n_override += 1
            kept.append(record)
            kept_keys.append(job_dedup.normalize_company(job_dedup._f(record, "company", "company_name")))
            continue
        marked_now = False
        # 1) 历史池查重（排除本批自己的行——它们还不是可用母本，只会白耗核对次数）。
        #    候选按相似度降序逐个核实状态：最高分的那条可能还没评过（新线索），别卡在它身上。
        hist_group = [
            h for h in job_dedup.find_company_group(index, job_dedup._f(record, "company", "company_name"))
            if h.get("record_id") not in batch_rids
        ]
        status_checks = 0
        for parent, verdict in job_dedup.find_history_parents(record, hist_group):
            prec = await _fetch_parent_record(parent.get("record_id", ""))
            status_checks += 1
            if _parent_status_usable(prec):
                pf = prec.get("fields", {})
                ok = await _mark_duplicate(
                    record,
                    parent_title=_extract_text(pf.get("岗位名称")) or job_dedup._f(parent, "job_title"),
                    parent_platform=_extract_text(pf.get("招聘平台")) or parent.get("platform", ""),
                    parent_link=_extract_text(pf.get("岗位链接")) or parent.get("job_link", ""),
                    verdict=verdict,
                    log=log,
                    dry_run=dry_run,
                    parent_grade=_extract_text(pf.get("综合评级 (A-F)")),
                    parent_rationales=_extract_text(pf.get("AI评估详情")),
                )
                if ok:
                    n_hist += 1
                    marked_now = True
                    marked.append({"job": record, "parent": parent, "verdict": verdict, "kind": "history"})
                    break
            if status_checks >= 3:  # 每岗位最多核实 3 条母本的飞书状态，控制 API 消耗
                break
        # 2) 批次内变体：与本批已放行的同公司代表比，命中则标记并登记待回填
        if not marked_now:
            my_key = job_dedup.normalize_company(job_dedup._f(record, "company", "company_name"))
            for rep, rep_key in zip(kept, kept_keys, strict=False):
                if rep_key != my_key:
                    continue
                v = job_dedup.judge_pair(record, rep)
                if not v.is_duplicate:
                    continue
                ok = await _mark_duplicate(
                    record,
                    parent_title=job_dedup._f(rep, "job_title", "job_name"),
                    parent_platform=job_dedup._f(rep, "platform"),
                    parent_link=job_dedup._f(rep, "job_url", "job_link"),
                    verdict=v,
                    log=log,
                    dry_run=dry_run,
                )
                if ok:
                    n_batch += 1
                    marked_now = True
                    marked.append({"job": record, "parent": rep, "verdict": v, "kind": "batch"})
                    pending_pairs.append({"duplicate": record, "parent": rep, "verdict": v})
                    break
        if marked_now:
            continue
        kept.append(record)
        kept_keys.append(my_key)

    if n_hist or n_batch or n_override:
        await _notify(
            log,
            f"🔁 疑似重复拦截: {n_hist + n_batch} 条不进评估"
            f"（历史母本 {n_hist} / 本批母本 {n_batch}）"
            + (f"，人工放行 {n_override} 条" if n_override else "")
            + f"，{len(kept)} 条照常评估"
            + (f"，预计节省 {n_hist + n_batch} 次 AI 初评" if not dry_run else "（dry-run 未写飞书）"))
    return kept, marked, pending_pairs


async def backfill_batch_dup_conclusions(
    pending_pairs: list[dict[str, Any]],
    *,
    log: Callable | None = None,
) -> int:
    """批次内母本跑完评估后，把其初评结论抄送给对应「疑似重复」副本（省人工一次跳转）。"""
    from app.services.feishu_service import (
        TABLE_ID,
        get_job_record_from_feishu,
        update_feishu_record,
    )

    backfilled = 0
    for pair in pending_pairs:
        try:
            dup, parent, verdict = pair["duplicate"], pair["parent"], pair["verdict"]
            if not dup.get("record_id"):
                continue
            prec = await asyncio.to_thread(get_job_record_from_feishu, parent.get("record_id", ""), TABLE_ID)
            if not prec or not _parent_status_usable(prec):
                continue
            pf = prec.get("fields", {})
            note = job_dedup.build_dup_note(
                parent_title=_extract_text(pf.get("岗位名称")) or job_dedup._f(parent, "job_title", "job_name"),
                parent_platform=_extract_text(pf.get("招聘平台")) or job_dedup._f(parent, "platform"),
                parent_link=_extract_text(pf.get("岗位链接")) or job_dedup._f(parent, "job_url", "job_link"),
                verdict=verdict,
                parent_grade=_extract_text(pf.get("综合评级 (A-F)")),
                parent_rationales=_extract_text(pf.get("AI评估详情")),
            )
            if await asyncio.to_thread(update_feishu_record, dup["record_id"], {"AI评估详情": note}):
                backfilled += 1
                await _notify(
                    log,
                    f"🧬 已回填母本结论: {job_dedup._f(dup, 'company', 'company_name')} "
                    f"{job_dedup._f(dup, 'job_title', 'job_name')[:24]}")
        except Exception as e:
            logger.warning(f"[去重关卡] 母本结论回填单条失败（继续）: {e}")
    if backfilled:
        await _notify(log, f"🧬 批次内母本结论回填完成: {backfilled}/{len(pending_pairs)} 条")
    return backfilled
