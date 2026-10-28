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
OUTCOME_READY_TO_DELIVER = "ready_to_deliver"  # 海投安检已过，停在待投递等发射波次
OUTCOME_ABORTED = "aborted"         # 手动终止（2026-10-24 工单：与「提前终止」语义区分）


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
        f"🕐 {started_at.strftime('%Y-%m-%d %H:%M:%S')}{duration}",
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
    aborted_jobs = [j for j in job_results if j.get("outcome") == OUTCOME_ABORTED]
    aborted_ungraded = [j for j in aborted_jobs if not (j.get("grade") or "").strip()]
    grade_dist: dict[str, int] = {}
    for j in job_results:
        # 手动终止且未完成初评的岗位单列，不折算成「评估失败」（2026-10-24 工单）
        if j.get("outcome") == OUTCOME_ABORTED and not (j.get("grade") or "").strip():
            continue
        # 空 grade = 评估失败（8维解析失败/LLM异常），不折算成任何评级
        g = (j.get("grade") or "评估失败").upper()
        grade_dist[g] = grade_dist.get(g, 0) + 1
    dist_txt = " · ".join(f"{g} {n}" for g, n in sorted(grade_dist.items()))
    lines.append(f"🧠 初评：共 {len(job_results) - len(aborted_ungraded)} 条 → {dist_txt}")
    if aborted_ungraded:
        lines.append(f"⛔ 另手动终止 {len(aborted_ungraded)} 条（未完成初评，未计入）")
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
            elif j.get("outcome") == OUTCOME_ABORTED:
                line += "｜手动终止"
            lines.append(line)
        lines.append("")

    # ── 已自动投递 ──
    delivered = [j for j in job_results if j.get("outcome") == OUTCOME_DELIVERED]
    if delivered:
        plat_dist: dict[str, int] = {}
        for j in delivered:
            p = str(j.get("platform") or "未知渠道")
            plat_dist[p] = plat_dist.get(p, 0) + 1
        plat_txt = " · ".join(f"{p} {n}" for p, n in plat_dist.items())
        lines.append(f"🚀 已自动投递（{len(delivered)} 条：{plat_txt}）：")
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

    # ── 待投递（海投安检已过，等发射波次）──
    ready = [j for j in job_results if j.get("outcome") == OUTCOME_READY_TO_DELIVER]
    if ready:
        lines.append(f"📬 待投递（{len(ready)} 条，已过安检，等发射波次自动投出）：")
        for i, j in enumerate(ready, 1):
            lines.append(_fmt_job_line(i, j))
        lines.append("")

    # ── 提前终止 ──
    stopped = [j for j in job_results if j.get("outcome") == OUTCOME_STOPPED]
    if stopped:
        lines.append(f"⚠️ 提前终止（{len(stopped)} 条，如海投门槛/数据不全）：")
        for i, j in enumerate(stopped, 1):
            lines.append(_fmt_job_line(i, j))
        lines.append("")

    # ── 手动终止（2026-10-24 工单）：终止前已完成的成果照常统计，未执行完的岗位单列 ──
    if aborted_jobs:
        lines.append(f"⛔ 手动终止（{len(aborted_jobs)} 条，后续节点未执行）：")
        for i, j in enumerate(aborted_jobs, 1):
            lines.append(_fmt_job_line(i, j, with_reason=True))
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
    trigger_source: str = "scheduled",
    aborted: bool = False,
) -> bool:
    """构建【全链路指挥中心 · 定时任务/手动即时任务】Card 2.0 主战报卡片并推送至飞书群。"""
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
        # 精确到秒（2026-10-10 用户需求 3.1）：肉眼可验证真实触发时刻——用户此前连续
        # 看到整点（真实整点触发）误以为显示被取整；秒级时间戳自证无舍入
        task_time_str = started_at.strftime("%Y-%m-%d %H:%M:%S")

        total_scraped = sum(scrape_counts.values()) if scrape_counts else cleaning.get("total", 0)
        hard_rejected = cleaning.get("hard_rejected", 0)
        hard_passed = cleaning.get("hard_passed", max(0, total_scraped - hard_rejected))
        ai_rejected = cleaning.get("ai_rejected", 0)
        ai_passed = cleaning.get("ai_passed", max(0, hard_passed - ai_rejected))

        # 统计评级与精投岗位
        # 分桶口径（2026-10-23 修复，pipeline_63487fa1 事故）：待审批桶以闸门挂起类型
        # （review_kind，graph_runner 审批断点写入）为事实源，与桌面待审批 tab（跟进状态
        # 含「复核」）同口径；旧版按评级 C/D/F 分桶——D 级大厂拦截岗（挂「海投人工复核」
        # 停审批断点）被误报进「其他情况已自动投递」，C 级已投递岗被虚报为待审批，
        # 「海投规则审批」计数恒等于 C 级岗位数、与文案语义脱节且放行卡为空。
        # 评级此后只用于「初评梯队」展示行，不再充当投递/待审批判据。
        grade_counts: dict[str, int] = {}
        precision_cnt = 0
        mass_review_cnt = 0
        ab_record_ids: list[str] = []
        mass_record_ids: list[str] = []

        eval_failed_cnt = 0
        for j in job_results:
            # 评估失败（8维解析失败/LLM异常）grade 为空串：绝不折算进 D/F 桶伪装成
            # 真实评级（2026-10-10），单列「评估失败」交由执行失败 tab 重试
            g = str(j.get("grade") or "").upper()
            rid = extract_job_record_id(j)
            if not rid:
                logger.warning(f"[PipelineReport] 岗位缺失有效 record_id: {j.get('job_name')}")
            if not g:
                # 手动终止且未完成初评的岗位单列，不计入「评估失败」（2026-10-24 工单）
                if j.get("outcome") == OUTCOME_ABORTED:
                    continue
                eval_failed_cnt += 1
                continue
            # 初评梯队展示行：纯评级分布，与投递/待审批去向解耦
            if g in ("A", "B"):
                precision_cnt += 1
                grade_counts[g] = grade_counts.get(g, 0) + 1
            elif g == "C":
                grade_counts["C"] = grade_counts.get("C", 0) + 1
            else:
                grade_counts["D/F"] = grade_counts.get("D/F", 0) + 1

            # 待审批分桶：review_kind 为事实源；缺失时兜底——A/B 视为精投审批，其余视为海投审批
            if j.get("outcome") == OUTCOME_WAITING:
                review_kind = str(j.get("review_kind") or "").strip()
                is_mass_review = review_kind == "mass_review" or (
                    not review_kind and g not in ("A", "B")
                )
                if is_mass_review:
                    mass_review_cnt += 1
                    if rid:
                        mass_record_ids.append(rid)
                elif rid:
                    ab_record_ids.append(rid)

        # 淘汰候选清单：仅收阶段 2 清洗/AI 排雷淘汰 ID（rowid），保序去重防截断窗口重复占位。
        # 初评 D/F 级不并入——流水线把 D/F 走海投轨正常流转（待投递/复核/已投递），
        # 并入会把活跃岗位误标成「淘汰:规则清洗拦截」，且召回已投递岗会污染状态。
        combined_rejected_ids = list(dict.fromkeys(rejected_ids or []))

        # 自动投递执行情况（2026-10-10 用户需求 3.2/3.4）：即时任务会真实发生投递动作，
        # 报告必须体现投了多少、成败多少、败因是什么——数据以运行时 job_results 为源
        delivered_jobs = [j for j in job_results if j.get("outcome") == OUTCOME_DELIVERED]
        delivery_failed_jobs = [j for j in job_results if j.get("outcome") == OUTCOME_FAILED]
        delivered_by_platform: dict[str, int] = {}
        delivered_record_ids: list[str] = []
        for j in delivered_jobs:
            platform = str(j.get("platform") or "未知渠道")
            delivered_by_platform[platform] = delivered_by_platform.get(platform, 0) + 1
            rid = extract_job_record_id(j)
            if rid:
                delivered_record_ids.append(rid)
        delivery_fail_reasons: dict[str, int] = {}
        for j in delivery_failed_jobs:
            reason = str(j.get("error") or "").strip()[:30] or "未知原因"
            delivery_fail_reasons[reason] = delivery_fail_reasons.get(reason, 0) + 1
            # 失败岗位同样进详情卡按钮值（R1 审查 P1：漏提会导致详情卡永远看不到失败明细，
            # 全败时更会误显「本轮无自动投递岗位」）
            rid = extract_job_record_id(j)
            if rid:
                delivered_record_ids.append(rid)

        # 「已执行自动投递」= 真实投递成功数（outcome==delivered），不再是 D/F 评级的代名词；
        # 已过安检停在「待投递」等发射波次的岗位单列（定时链路的正常终点）
        auto_delivered_cnt = len(delivered_jobs)
        ready_to_deliver_cnt = sum(1 for j in job_results if j.get("outcome") == OUTCOME_READY_TO_DELIVER)
        # 手动终止（2026-10-24 工单）：主战报卡片必须带终止横幅，且未完成初评的终止岗
        # 不能计入「评估异常中断」（否则终止会被误报成故障）。
        aborted_jobs = [j for j in job_results if j.get("outcome") == OUTCOME_ABORTED]
        aborted_ungraded_cnt = sum(1 for j in aborted_jobs if not (j.get("grade") or "").strip())

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
            auto_delivered_cnt=auto_delivered_cnt,
            ready_to_deliver_cnt=ready_to_deliver_cnt,
            dedup_count=dedup_count,
            ab_record_ids=ab_record_ids,
            mass_record_ids=mass_record_ids,
            rejected_record_ids=combined_rejected_ids,
            delivered_record_ids=delivered_record_ids,
            delivered_by_platform=delivered_by_platform,
            delivery_fail_reasons=delivery_fail_reasons,
            delivery_fail_cnt=len(delivery_failed_jobs),
            eval_failed_cnt=eval_failed_cnt,
            trigger_source=trigger_source,
            aborted=aborted,
            aborted_cnt=len(aborted_jobs),
            aborted_ungraded_cnt=aborted_ungraded_cnt,
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
