"""
全链路任务报告 — 每次链路结束时汇总本轮战果并发送到飞书接收群。

报告内容：
- 各平台抓取条数（含失效跳过的平台）
- 清洗结果（硬规则拦截 / AI 拦截 / 通过）
- 飞书推送条数
- 初评等级分布
- A/B 高价值岗位清单（挂起等待人工审批）
- 已自动投递清单 / 其余待审批清单 / 失败与提前终止清单

发送目标与日报一致：优先 job_goals 表的 feishu_receive_id（接收群），
降级 FEISHU_ALERT_RECEIVE_ID；oc_ 前缀按群聊 chat_id 发送。
"""
import logging
import sqlite3
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# 岗位最终去向
OUTCOME_DELIVERED = "delivered"     # 已自动投递
OUTCOME_WAITING = "waiting"         # 停在待审批断点
OUTCOME_FAILED = "failed"           # 评估/投递失败
OUTCOME_STOPPED = "stopped"         # 提前终止（如海投门槛）


def collect_cleaning_stats(raw_db_path: str, start_rowid: int) -> dict[str, int]:
    """统计本轮（rowid > start_rowid）清洗结果（以数据库白名单事实为单一事实源）。"""
    stats = {
        "total": 0,
        "hard_rejected": 0,
        "hard_passed": 0,
        "ai_rejected": 0,
        "ai_passed": 0,
        "pending_ai": 0,
        "passed": 0,
        "untracked": 0,
    }
    try:
        with sqlite3.connect(raw_db_path) as conn:
            rows = conn.execute(
                "SELECT process_status, COUNT(*) FROM raw_jobs WHERE rowid > ? GROUP BY process_status",
                (start_rowid,),
            ).fetchall()
        for status, n in rows:
            stats["total"] += n
            if status == "清洗淘汰":
                stats["hard_rejected"] += n
            elif status == "待AI初筛":
                stats["pending_ai"] += n
            elif status == "ai清洗淘汰":
                stats["ai_rejected"] += n
            elif status in ("待推送至飞书", "已推送飞书", "已同步"):
                stats["ai_passed"] += n
                stats["passed"] += n

        # 硬清洗通过必然流转至后续合法状态（白名单显式累加，绝不使用反向排除）
        stats["hard_passed"] = stats["ai_passed"] + stats["ai_rejected"] + stats["pending_ai"]

        # 状态机恒等式校验
        expected_total = stats["hard_rejected"] + stats["hard_passed"]
        if stats["total"] != expected_total:
            diff = stats["total"] - expected_total
            stats["untracked"] = diff
            logger.warning(
                f"[PipelineReport] 清洗状态机统计存在未纳管状态记录共 {diff} 条！"
                f"（total={stats['total']}, hard_rejected={stats['hard_rejected']}, hard_passed={stats['hard_passed']}）"
            )
    except Exception as e:
        logger.warning(f"[PipelineReport] 清洗统计失败: {e}")
        return {}
    return stats


def _fmt_job_line(idx: int, job: dict[str, Any], with_reason: bool = False) -> str:
    grade = job.get("grade") or "?"
    platform = job.get("platform") or "?"
    company = str(job.get("company_name") or "")[:20]
    name = str(job.get("job_name") or "")[:28]
    line = f"{idx}. [{platform}] {company} - {name} ({grade}级)"
    if with_reason and job.get("error"):
        line += f"：{str(job['error'])[:40]}"
    return line


def build_pipeline_report(
    started_at: datetime,
    scrape_counts: dict[str, int],
    disabled_platforms: list[str],
    platform_cn: dict[str, str],
    cleaning: dict[str, int],
    synced_count: int,
    job_results: list[dict[str, Any]],
    aborted: bool = False,
    dedup_count: int = 0,
) -> str:
    """拼装任务报告文本。job_results 为空时表示本轮无进入评估的岗位。"""
    duration = ""
    try:
        mins = max(0, int((datetime.now() - started_at).total_seconds() // 60))
        duration = f" · 用时约 {mins} 分钟"
    except Exception:
        pass

    lines = [
        "📊 全链路任务报告",
        f"🕐 {started_at.strftime('%Y-%m-%d %H:%M')}{duration}",
    ]
    if aborted:
        lines.append("⛔ 本次任务被手动终止，以下为终止前已完成部分")
    lines.append("")

    # ── 抓取 ──
    total_new = sum(scrape_counts.values())
    lines.append(f"🕷️ 抓取：本轮新增 {total_new} 条")
    if scrape_counts:
        detail = " · ".join(
            f"{platform_cn.get(k, k)} {v}" for k, v in scrape_counts.items()
        )
        lines.append(f"· {detail}")
    if disabled_platforms:
        lines.append("· 跳过失效平台: " + "、".join(platform_cn.get(p, p) for p in disabled_platforms))
    lines.append("")

    # ── 清洗 ──
    lines.append(
        f"🧹 清洗：处理 {cleaning.get('total', 0)} 条 → 通过 {cleaning.get('ai_passed', cleaning.get('passed', 0))} 条"
    )
    lines.append(
        f"· 硬规则拦截 {cleaning.get('hard_rejected', 0)} · AI拦截 {cleaning.get('ai_rejected', 0)}"
    )
    lines.append("")

    # ── 飞书推送 ──
    lines.append(f"📤 飞书推送：新增 {synced_count} 条「新线索」")
    if dedup_count > 0:
        lines.append(f"🧬 疑似重复：拦截 {dedup_count} 条（已自动抄送母本结论并跳过评估）")
    lines.append("")

    if not job_results:
        lines.append("🧠 初评：本轮无岗位进入评估")
        return "\n".join(lines)

    # ── 初评分布 ──
    grade_dist: dict[str, int] = {}
    for j in job_results:
        g = (j.get("grade") or "?").upper()
        grade_dist[g] = grade_dist.get(g, 0) + 1
    dist_txt = " · ".join(f"{g} {n}" for g, n in sorted(grade_dist.items()))
    lines.append(f"🧠 初评：共 {len(job_results)} 条 → {dist_txt}")
    lines.append("")

    # ── A/B 高价值岗位 ──
    ab_jobs = [j for j in job_results if (j.get("grade") or "").upper() in ("A", "B")]
    if ab_jobs:
        lines.append(f"🌟 A/B 高价值岗位（{len(ab_jobs)} 条）：")
        for i, j in enumerate(ab_jobs, 1):
            line = _fmt_job_line(i, j)
            if j.get("outcome") == OUTCOME_WAITING:
                line += "｜已改写，挂起等待人工审批，放行后自动投递"
            elif j.get("outcome") == OUTCOME_DELIVERED:
                line += "｜已自动投递"
            elif j.get("outcome") == OUTCOME_FAILED:
                line += "｜失败"
            lines.append(line)
        lines.append("")

    # ── 已自动投递 ──
    delivered = [j for j in job_results if j.get("outcome") == OUTCOME_DELIVERED]
    if delivered:
        lines.append(f"🚀 已自动投递（{len(delivered)} 条）：")
        for i, j in enumerate(delivered, 1):
            lines.append(_fmt_job_line(i, j))
        lines.append("")

    # ── 其余待审批 ──
    waiting_rest = [
        j for j in job_results
        if j.get("outcome") == OUTCOME_WAITING and (j.get("grade") or "").upper() not in ("A", "B")
    ]
    if waiting_rest:
        lines.append(f"⏸️ 其他待审批（{len(waiting_rest)} 条）：")
        for i, j in enumerate(waiting_rest, 1):
            lines.append(_fmt_job_line(i, j))
        lines.append("")

    # ── 失败 ──
    failed = [j for j in job_results if j.get("outcome") == OUTCOME_FAILED]
    if failed:
        lines.append(f"❌ 失败（{len(failed)} 条）：")
        for i, j in enumerate(failed, 1):
            lines.append(_fmt_job_line(i, j, with_reason=True))
        lines.append("")

    # ── 提前终止 ──
    stopped = [j for j in job_results if j.get("outcome") == OUTCOME_STOPPED]
    if stopped:
        lines.append(f"⚠️ 提前终止（{len(stopped)} 条，如海投门槛/数据不全）：")
        for i, j in enumerate(stopped, 1):
            lines.append(_fmt_job_line(i, j))
        lines.append("")

    return "\n".join(lines).rstrip()


async def send_pipeline_report(text: str) -> bool:
    """把报告/通知发到飞书接收群（与日报同一接收目标）。

    失败只告警不抛出，返回是否真实送达：
    - 接收ID未配置/格式错误（应为 oc_/ou_ 开头）→ 告警 + 控制台降级
    - 飞书接口返回非0 → 告警 + 控制台降级
    """
    try:
        from app.core.feishu_messaging import is_valid_receive_id, send_feishu_message
        from app.services.report_feishu import _get_receive_id
        receive_id = _get_receive_id()
        if not is_valid_receive_id(receive_id):
            logger.warning(
                f"[PipelineReport] 飞书接收ID未配置或格式错误（当前值: {receive_id!r}，"
                f"应为 oc_/ou_ 开头），报告降级打印到控制台。请到配置大盘修正飞书接收群ID。"
            )
            print(f"\n{'=' * 50}\n{text}\n{'=' * 50}\n", flush=True)
            return False
        ok = await send_feishu_message(
            receive_id=receive_id,
            text=text,
            receive_id_type="chat_id" if receive_id.startswith("oc_") else "open_id",
        )
        if ok:
            logger.info("[PipelineReport] 报告已真实送达飞书")
        else:
            logger.warning("[PipelineReport] 飞书接口返回失败，报告降级打印到控制台")
            print(f"\n{'=' * 50}\n{text}\n{'=' * 50}\n", flush=True)
        return ok
    except Exception as e:
        logger.warning(f"[PipelineReport] 报告发送异常: {e}")
        print(f"\n{'=' * 50}\n{text}\n{'=' * 50}\n", flush=True)
        return False


async def send_pipeline_master_card(
    started_at: datetime,
    scrape_counts: dict[str, int],
    cleaning: dict[str, int],
    job_results: list[dict[str, Any]],
    dedup_count: int = 0,
    rejected_ids: list[str] | None = None,
) -> bool:
    """构建【全链路指挥中心 · 定时任务】Card 2.0 主战报卡片并推送至飞书群。"""
    try:
        from app.core.feishu_messaging import is_valid_receive_id, send_feishu_card
        from app.services.pipeline_card_builders import (
            build_master_pipeline_card,
            extract_job_record_id,
        )
        from app.services.report_feishu import _get_receive_id

        receive_id = _get_receive_id()
        if not is_valid_receive_id(receive_id):
            logger.warning(f"[PipelineReport] 飞书接收 ID 未配置或格式无效 ({receive_id!r})，跳过主战报卡片发送")
            return False

        duration_mins = max(1, int((datetime.now() - started_at).total_seconds() // 60))
        task_time_str = started_at.strftime("%Y-%m-%d %H:%M")

        total_scraped = sum(scrape_counts.values()) if scrape_counts else cleaning.get("total", 0)
        hard_rejected = cleaning.get("hard_rejected", 0)
        hard_passed = cleaning.get("hard_passed", max(0, total_scraped - hard_rejected))
        ai_rejected = cleaning.get("ai_rejected", 0)
        ai_passed = cleaning.get("ai_passed", max(0, hard_passed - ai_rejected))

        # 统计评级与精投岗位
        grade_counts: dict[str, int] = {}
        precision_cnt = 0
        mass_review_cnt = 0
        other_cnt = 0
        ab_record_ids: list[str] = []
        mass_record_ids: list[str] = []
        df_record_ids: list[str] = []

        for j in job_results:
            g = str(j.get("grade") or "D").upper()
            rid = extract_job_record_id(j)
            if not rid:
                logger.warning(f"[PipelineReport] 岗位缺失有效 record_id: {j.get('job_name')}")
            if g in ("A", "B"):
                precision_cnt += 1
                grade_counts[g] = grade_counts.get(g, 0) + 1
                if rid:
                    ab_record_ids.append(rid)
            elif g == "C":
                grade_counts["C"] = grade_counts.get("C", 0) + 1
                mass_review_cnt += 1
                if rid:
                    mass_record_ids.append(rid)
            else:
                grade_counts["D/F"] = grade_counts.get("D/F", 0) + 1
                other_cnt += 1
                if rid:
                    df_record_ids.append(rid)

        # 淘汰岗位：优先保留阶段 4 初评 AI 淘汰 ID (feishu record_id)，再追加阶段 2 清洗淘汰 ID (rowid)
        # 确保高价值误杀候选不被大量硬清洗淘汰挤出前 20 截断窗口
        combined_rejected_ids = list(dict.fromkeys(df_record_ids + (rejected_ids or [])))

        card = build_master_pipeline_card(
            task_time=task_time_str,
            duration_mins=duration_mins,
            total_scraped=total_scraped,
            hard_passed=hard_passed,
            hard_rejected=hard_rejected,
            ai_passed=ai_passed,
            ai_rejected=ai_rejected,
            precision_cnt=precision_cnt,
            channel_counts=scrape_counts,
            grade_counts=grade_counts,
            mass_review_cnt=mass_review_cnt,
            other_review_cnt=other_cnt,
            dedup_count=dedup_count,
            ab_record_ids=ab_record_ids,
            mass_record_ids=mass_record_ids,
            rejected_record_ids=combined_rejected_ids,
        )

        ok = await send_feishu_card(
            receive_id=receive_id,
            card_content=card,
            receive_id_type="chat_id" if receive_id.startswith("oc_") else "open_id",
        )
        if ok:
            logger.info(f"📮 [PipelineReport] 主战报卡片已成功推送至飞书群: {receive_id}")
        return ok
    except Exception as e:
        logger.warning(f"[PipelineReport] 主战报卡片发送失败: {e}")
        return False
