# backend/app/services/report_card_actions.py
"""
全链路指挥中心 · 定时战报卡片交互动作处理引擎。
负责处理飞书战报卡片上的所有回传动作（Card Action Trigger）：
1. 分流调出子卡片（open_ab_card / open_mass_card / open_rejected_card）
2. 精投岗位批量/多选放行（approve_all_ab / approve_selected_ab）
3. 大厂海投批量/多选放行（approve_all_mass / approve_selected_mass）
4. 淘汰岗位误杀召回复活（recall_selected_rejected）
5. 确认淘汰（confirm_trash）
"""

import asyncio
import logging
import sqlite3
from typing import Any

from app.automation.db import mark_job_approved
from app.automation.scrape_runner import _get_raw_db_path
from app.core.feishu_messaging import send_feishu_card, send_feishu_message
from app.services import feishu_service
from app.services.pipeline_card_builders import (
    SUB_CARD_MAX,
    JobCardItem,
    build_action_result_card,
    build_sub_card_ab,
    build_sub_card_mass,
    build_sub_card_rejected,
    extract_job_record_id,
    get_base_url,
)

logger = logging.getLogger("report_card_actions")

# 战报卡片支持的全部 action 标识
REPORT_CARD_ACTIONS = {
    "open_ab_card", "open_mass_card", "open_rejected_card",
    "open_sub_card_ab", "open_sub_card_mass", "open_sub_card_rejected",
    "approve_all_ab", "approve_selected_ab", "approve_all_mass",
    "approve_selected_mass", "recall_selected_rejected",
    "confirm_recall", "confirm_trash",
}


def is_report_card_action(action: str) -> bool:
    """判定是否属于定时战报卡片的交互动作。"""
    return (action or "").strip() in REPORT_CARD_ACTIONS


def _get_semaphore() -> asyncio.Semaphore:
    """延迟获取当前事件循环的安全并发限流器（限制 3 并发，防 429）。"""
    return asyncio.Semaphore(3)


async def handle_report_card_action(
    chat_id: str,
    action_value: dict[str, Any],
    selected_options: list[str] | None = None,
) -> None:
    """
    战报卡片交互统一异步处理入口。
    """
    action = str((action_value or {}).get("action") or "").strip()
    logger.info(
        f"[战报卡片交互] 收到操作 | chat_id={chat_id} | action={action} "
        f"| value={action_value} | selected_options={selected_options}"
    )

    if not chat_id:
        logger.warning("[战报卡片交互] 缺少 chat_id，终止执行")
        return

    try:
        # 1. 调出分流子卡片（动态拉取真实数据）
        if action in (
            "open_ab_card", "open_mass_card", "open_rejected_card",
            "open_sub_card_ab", "open_sub_card_mass", "open_sub_card_rejected",
        ):
            raw_target_ids = (action_value or {}).get("record_ids")
            if isinstance(raw_target_ids, list):
                target_ids = [str(x).strip() for x in raw_target_ids if str(x).strip()]
            elif isinstance(raw_target_ids, str) and raw_target_ids.strip():
                target_ids = [raw_target_ids.strip()]
            elif raw_target_ids is None:
                target_ids = None
            else:
                target_ids = []

            raw_total = (action_value or {}).get("total")
            total_cnt = raw_total if (isinstance(raw_total, int) and not isinstance(raw_total, bool)) else (len(target_ids) if target_ids is not None else None)

            await _handle_open_sub_card(chat_id, action, target_ids=target_ids, total=total_cnt)
            return

        # 2. 精投岗位放行（一键全选 或 多选下拉）
        if action == "approve_all_ab":
            record_ids = list(action_value.get("record_ids") or [])
            await _batch_approve_jobs(chat_id, record_ids, job_type_label="精投岗位", is_all=True)
            return

        if action == "approve_selected_ab":
            record_ids = list(selected_options or [])
            if not record_ids:
                await send_feishu_message(chat_id, "⚠️ 未勾选任何精投岗位，请先在下拉列表中勾选。", "chat_id")
                return
            await _batch_approve_jobs(chat_id, record_ids, job_type_label="精投岗位", is_all=False)
            return

        # 3. 大厂海投放行（一键全选 或 多选下拉）
        if action == "approve_all_mass":
            record_ids = list(action_value.get("record_ids") or [])
            await _batch_approve_jobs(chat_id, record_ids, job_type_label="大厂海投岗位", is_all=True)
            return

        if action == "approve_selected_mass":
            record_ids = list(selected_options or [])
            if not record_ids:
                await send_feishu_message(chat_id, "⚠️ 未勾选任何大厂海投岗位，请先在下拉列表中勾选。", "chat_id")
                return
            await _batch_approve_jobs(chat_id, record_ids, job_type_label="大厂海投岗位", is_all=False)
            return

        # 4. 淘汰岗位误杀召回复活（表单多选勾选并点击确定提交）
        if action in ("recall_selected_rejected", "confirm_recall"):
            record_ids = list(selected_options or action_value.get("record_ids") or [])
            if not record_ids:
                await send_feishu_message(chat_id, "⚠️ 请先在上方下拉框中勾选要召回的岗位（支持多选，点击确定后转入 AI 初评）。", "chat_id")
                return
            await _batch_recall_rejected_jobs(chat_id, record_ids)
            return

        # 5. 确认淘汰归档
        if action == "confirm_trash":
            logger.info(f"[战报卡片交互] 确认淘汰归档 | chat_id={chat_id}")
            record_ids = list(action_value.get("record_ids") or [])
            if not record_ids:
                # 容错：若点击未绑定 record_ids 的旧卡片按钮，自动读取当前最新淘汰记录
                recent_rejs = await asyncio.to_thread(_fetch_real_jobs_for_sub_card, "rejected")
                record_ids = [j.job_id for j in recent_rejs]
            await _batch_reject_jobs(chat_id, record_ids)
            return

        logger.warning(f"[战报卡片交互] 未识别的战报动作: {action}")

    except Exception as e:
        logger.exception(f"[战报卡片交互] 处理异常: {e}")
        await send_feishu_message(chat_id, f"❌ 操作执行失败: {e}", "chat_id")


async def _handle_open_sub_card(
    chat_id: str,
    action: str,
    target_ids: list[str] | None = None,
    total: int | None = None,
) -> None:
    """根据动作动态拉取真实数据并调出对应的子卡片。"""
    card_map = {
        "open_ab_card": ("🌟 精投岗位清单", "ab", build_sub_card_ab),
        "open_sub_card_ab": ("🌟 精投岗位清单", "ab", build_sub_card_ab),
        "open_mass_card": ("🏢 海投复核清单", "mass", build_sub_card_mass),
        "open_sub_card_mass": ("🏢 海投复核清单", "mass", build_sub_card_mass),
        "open_rejected_card": ("🗑️ 淘汰清单", "rejected", build_sub_card_rejected),
        "open_sub_card_rejected": ("🗑️ 淘汰清单", "rejected", build_sub_card_rejected),
    }
    label, cat, builder = card_map.get(action, ("", "", None))
    if not builder:
        return

    # 动态从真实存储中拉取岗位数据（支持任务作用域隔离）
    real_jobs = await asyncio.to_thread(_fetch_real_jobs_for_sub_card, cat, target_ids=target_ids)
    total_str = f" / 总计 {total}" if total is not None else ""
    logger.info(f"[战报卡片交互] 调出子卡片: {label} (找到真实岗位 {len(real_jobs)} 条{total_str}) -> {chat_id}")
    card_content = builder(jobs=real_jobs, total=total)
    await send_feishu_card(receive_id=chat_id, card_content=card_content, receive_id_type="chat_id")


def _fetch_real_jobs_for_sub_card(category: str, target_ids: list[str] | None = None) -> list[JobCardItem]:
    """从多维表格与本地 SQLite 动态拉取最新的真实岗位。

    支持任务作用域隔离：
    - target_ids is not None：严格按给定的当次任务岗位 ID 列表筛选。
      若为 []，表示当次任务此分流为 0 条，立即返回 [] 渲染空态卡片，绝不降级扫描历史库；
    - target_ids is None：旧版卡片无此字段，保留平滑降级兜底逻辑。
    """
    items: list[JobCardItem] = []
    base_url = get_base_url()

    # 🌟 关键防御：显式空列表代表当次任务为 0 条，坚决返回空列表渲染空态卡片，严禁扫历史库！
    if target_ids is not None and len(target_ids) == 0:
        logger.info(f"[战报卡片交互] category={category} 当次任务 ID 列表为空，直接返回 0 条空态")
        return []

    target_id_set = {str(t).strip() for t in target_ids if str(t).strip()} if target_ids is not None else None

    try:
        if category in ("ab", "mass"):
            # 精投 / 海投岗位：从多维表格拉取待人工复核的真实记录
            all_pending = feishu_service.get_pending_review_jobs_from_feishu() or []
            candidates: list[dict[str, Any]] = []

            for job in all_pending:
                status = str(job.get("follow_status") or "").strip()
                # 状态必须包含「复核」，且排除已终态或已处理状态
                is_pending_review = "复核" in status and not any(
                    ex in status for ex in ["已投递", "待投递", "沟通中", "已打招呼", "不合适", "已淘汰", "已归档", "已下架"]
                )
                if not is_pending_review:
                    continue

                rec_id = extract_job_record_id(job)
                # 任务隔离：若传入了当次任务 target_ids，只保留属于 target_ids 的记录
                if target_id_set is not None and rec_id not in target_id_set:
                    continue

                grade = str(job.get("grade") or "").strip().upper()
                is_custom = bool(job.get("is_custom"))

                if category == "ab":
                    # 精投岗位：评级为 A/B 级，或标记为定制岗位
                    if not (is_custom or any(g in grade for g in ("A", "B"))):
                        continue
                    candidates.append(job)
                elif category == "mass":
                    # 大厂海投岗位：状态包含海投复核，或非定制 A/B 岗
                    if "海投" in status or not (is_custom or any(g in grade for g in ("A", "B"))):
                        candidates.append(job)

            if target_id_set is not None:
                missing_cnt = len(target_id_set) - len(candidates)
                if not candidates:
                    logger.warning(f"[战报卡片交互] category={category} 指定了 {len(target_id_set)} 个目标岗位 ID，但在多维表格未匹配到任何待复核记录: {target_ids}")
                elif missing_cnt > 0:
                    logger.warning(f"[战报卡片交互] category={category} 指定了 {len(target_id_set)} 个目标岗位 ID，实际匹配 {len(candidates)} 条，部分未命中缺失 {missing_cnt} 条")

            # 筛选出符合条件的候选集后，最多展示 SUB_CARD_MAX 条
            for idx, job in enumerate(candidates[:SUB_CARD_MAX], 1):
                record_id = extract_job_record_id(job)
                platform = str(job.get("platform") or "渠道").upper()
                company = str(job.get("company_name") or "目标企业")
                job_title = str(job.get("job_name") or "待审岗位")
                grade = str(job.get("grade") or ("A" if category == "ab" else "C")).upper()
                clean_grade = "A" if "A" in grade else ("B" if "B" in grade else grade)
                scale = str(job.get("company_scale") or "").strip()

                if category == "ab":
                    items.append(JobCardItem(
                        job_id=record_id,
                        title=f"{idx}. [{platform}] {company} - {job_title}",
                        grade=f"{clean_grade}级",
                        short_name=f"{company[:8]} · {job_title[:8]}",
                        color="green" if clean_grade == "A" else "blue",
                        detail_url=f"{base_url}&record={record_id}" if base_url and record_id else "",
                    ))
                else:
                    items.append(JobCardItem(
                        job_id=record_id,
                        title=f"{idx}. [{platform}] {company} - {job_title}",
                        grade="海投",
                        short_name=f"{company[:8]} · {job_title[:8]}",
                        color="blue",
                        detail_url=f"{base_url}&record={record_id}" if base_url and record_id else "",
                        extra_info=f"公司规模: {scale}" if scale else "海投岗位",
                    ))

        elif category == "rejected":
            # 淘汰岗位：拉取本地 SQLite 记录
            db_path = _get_raw_db_path()
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cols_all = [c[1] for c in conn.execute("PRAGMA table_info(raw_jobs)").fetchall()]
                has_job_link = "job_link" in cols_all
                cols = "rowid, platform, job_title, company_name, reject_reason, feishu_record_id"
                if has_job_link:
                    cols += ", job_link"

                if target_ids is not None:
                    # 精准任务过滤：支持纯数字 SQLite rowid 或飞书 feishu_record_id
                    target_rowids = []
                    target_feishu_ids = []
                    for tid in target_ids:
                        s = str(tid).strip()
                        if s.isdigit():
                            target_rowids.append(int(s))
                        elif s:
                            target_feishu_ids.append(s)

                    if not target_rowids and not target_feishu_ids:
                        logger.warning(f"[战报卡片交互] category=rejected 目标 ID 列表中无法解析出有效 ID: {target_ids}")
                        return []

                    target_rowids = target_rowids[:SUB_CARD_MAX]
                    target_feishu_ids = target_feishu_ids[:SUB_CARD_MAX]

                    where_clauses = []
                    params: list[Any] = []
                    if target_rowids:
                        ph = ",".join("?" for _ in target_rowids)
                        where_clauses.append(f"rowid IN ({ph})")
                        params.extend(target_rowids)
                    if target_feishu_ids:
                        ph = ",".join("?" for _ in target_feishu_ids)
                        where_clauses.append(f"feishu_record_id IN ({ph})")
                        params.extend(target_feishu_ids)

                    where_sql = " OR ".join(where_clauses)
                    select_sql = (
                        f"SELECT {cols} FROM raw_jobs "
                        f"WHERE ({where_sql}) "
                        "  AND process_status NOT IN ('召回待初评', '召回待投递', '待投递', '已投递', '新线索') "
                        f"ORDER BY rowid DESC LIMIT {SUB_CARD_MAX}"
                    )
                    rows = conn.execute(select_sql, params).fetchall()
                    missing_cnt = (len(target_rowids) + len(target_feishu_ids)) - len(rows)
                    if not rows:
                        logger.warning(f"[战报卡片交互] category=rejected 指定了目标 ID，但在本地 SQLite 未找到记录: rowids={target_rowids}, feishu_ids={target_feishu_ids}")
                    elif missing_cnt > 0:
                        logger.warning(f"[战报卡片交互] category=rejected 目标共 {len(target_rowids) + len(target_feishu_ids)} 条，实际匹配 {len(rows)} 条，缺失 {missing_cnt} 条")
                else:
                    # 旧卡片兼容兜底：拉取最新淘汰记录
                    select_sql = (
                        f"SELECT {cols} FROM raw_jobs "
                        "WHERE (process_status LIKE '%淘汰%' OR (reject_reason IS NOT NULL AND reject_reason != '')) "
                        "  AND process_status NOT IN ('召回待初评', '召回待投递', '待投递', '已投递', '新线索') "
                        f"ORDER BY rowid DESC LIMIT {SUB_CARD_MAX}"
                    )
                    rows = conn.execute(select_sql).fetchall()

                for idx, r in enumerate(rows, 1):
                    platform = r["platform"] or "平台"
                    company = r["company_name"] or "目标企业"
                    job_title = r["job_title"] or "岗位"
                    reason = r["reject_reason"] or "规则清洗拦截"
                    jid = r["feishu_record_id"] if r["feishu_record_id"] else str(r["rowid"])
                    feishu_rec = str(r["feishu_record_id"] or "").strip()
                    job_link = str(r["job_link"] or "").strip() if has_job_link and "job_link" in r.keys() else ""

                    if base_url and feishu_rec.startswith("rec"):
                        det_url = f"{base_url}&record={feishu_rec}"
                    else:
                        det_url = job_link if job_link.startswith("http") else (base_url or "")

                    items.append(JobCardItem(
                        job_id=jid,
                        title=f"{idx}. [{platform}] {company} - {job_title}",
                        grade=reason[:12],
                        short_name=f"{company[:8]} ({reason[:6]})",
                        color="red",
                        detail_url=det_url,
                        extra_info=f"淘汰原因: {reason}",
                    ))

    except Exception as e:
        logger.warning(f"[战报卡片交互] 真实岗位数据拉取异常: {e}")

    return items


async def _batch_approve_jobs(chat_id: str, record_ids: list[str], job_type_label: str = "精投岗位", is_all: bool = False) -> None:
    """
    批量将岗位状态放行至「待投递」队列，带并发限流、失败收集与防假成功闭环。
    以高质感交互卡片形式推送回执，并在标题中写出具体放行数量 n。
    """
    valid_ids = [r for r in (record_ids or []) if r and str(r).strip()]
    if not valid_ids:
        await send_feishu_message(chat_id, f"⚠️ 缺少要放行的{job_type_label}有效标识 (Record ID 为空)。", "chat_id")
        return

    logger.info(f"[战报放行] 开始批量放行 {len(valid_ids)} 个{job_type_label} (is_all={is_all}) | IDs={valid_ids}")

    sem = _get_semaphore()
    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []

    async def _update_single(rid: str):
        async with sem:
            try:
                # 严格锚定现有飞书多维表格「跟进状态」字段为「待投递」
                ok = await asyncio.to_thread(feishu_service.update_feishu_record, rid, {"跟进状态": "待投递"})
                if not ok:
                    failed.append((rid, "飞书多维表格更新接口返回 False"))
                    return

                # 标记 SQLite 放行状态与内存防抖
                await asyncio.to_thread(mark_job_approved, rid)
                succeeded.append(rid)
            except Exception as ex:
                failed.append((rid, str(ex)))

    await asyncio.gather(*[_update_single(r) for r in valid_ids], return_exceptions=False)

    total = len(valid_ids)
    succ_cnt = len(succeeded)
    fail_cnt = len(failed)

    logger.info(f"[战报放行] 批量放行完成 | 总计={total} | 成功={succ_cnt} | 失败={fail_cnt}")

    flow_desc = "已成功推入电脑端 **「待投递」Tab**，将在设定的投递时间由自动投递波次发射！"

    # 严格遵循防假成功：只有当成功数 > 0 且失败为 0 时才判定全胜
    if succ_cnt > 0 and fail_cnt == 0:
        title = f"🎉 本轮 {succ_cnt} 个{job_type_label}已全部放行！" if is_all else f"🎉 选中的 {succ_cnt} 个{job_type_label}放行成功！"
        card = build_action_result_card(
            title=title,
            succ_cnt=succ_cnt,
            target_queue="待投递",
            target_status="待投递",
            flow_desc=flow_desc,
            theme="turquoise",
        )
    elif succ_cnt > 0 and fail_cnt > 0:
        fail_details = "\n".join([f"  - `{rid}`: {err}" for rid, err in failed[:5]])
        card = build_action_result_card(
            title=f"⚠️ {job_type_label}部分放行完成 (成功 {succ_cnt} / 失败 {fail_cnt})",
            succ_cnt=succ_cnt,
            target_queue="待投递",
            target_status="待投递",
            flow_desc="部分岗位已推入待投递队列，失败条目请在电脑端或多维表格核对。",
            fail_cnt=fail_cnt,
            fail_details=fail_details,
            theme="orange",
        )
    else:
        fail_details = "\n".join([f"  - `{rid}`: {err}" for rid, err in failed[:5]]) if failed else "无有效可更新项目"
        card = build_action_result_card(
            title=f"❌ {job_type_label}放行未成功",
            succ_cnt=0,
            target_queue="待投递",
            target_status="失败",
            flow_desc="放行操作未成功，请检查网络连接或飞书多维表格访问权限后重试。",
            fail_cnt=fail_cnt,
            fail_details=fail_details,
            theme="carmine",
        )

    await send_feishu_card(chat_id, card, "chat_id")


async def _batch_recall_rejected_jobs(chat_id: str, job_ids: list[str]) -> None:
    """
    误杀召回批量放行（支持飞书 rec... 与本地 SQLite 纯数字 ID 智能分流，重新转入「AI 初评」队列）。
    """
    valid_ids = [j for j in (job_ids or []) if j and str(j).strip()]
    if not valid_ids:
        await send_feishu_message(chat_id, "⚠️ 未勾选任何需要召回的岗位。", "chat_id")
        return

    logger.info(f"[战报召回] 开始批量召回放行 {len(valid_ids)} 个岗位进入 AI 初评 | IDs={valid_ids}")

    sem = _get_semaphore()
    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []

    db_path = _get_raw_db_path()

    async def _recall_single(jid: str):
        async with sem:
            try:
                if str(jid).startswith("rec"):
                    # 1. 飞书多维表格记录：更新跟进状态为「新线索」（重新触发 AI 初评）
                    ok = await asyncio.to_thread(feishu_service.update_feishu_record, jid, {"跟进状态": "新线索"})
                    if not ok:
                        failed.append((jid, "多维表格更新返回 False"))
                        return
                    # 同步更新本地 SQLite 状态为已召回待初评
                    def _sync_sqlite():
                        with sqlite3.connect(db_path) as conn:
                            conn.execute(
                                "UPDATE raw_jobs SET process_status = '召回待初评' "
                                "WHERE feishu_record_id = ?", (jid,)
                            )
                    await asyncio.to_thread(_sync_sqlite)
                    succeeded.append(jid)
                else:
                    # 2. 本地 SQLite 纯数字 rowid 记录：更新为「召回待初评」
                    rowid = int(jid)
                    def _update_sqlite():
                        with sqlite3.connect(db_path) as conn:
                            conn.execute(
                                "UPDATE raw_jobs SET process_status = '召回待初评' "
                                "WHERE rowid = ?", (rowid,)
                            )
                    await asyncio.to_thread(_update_sqlite)
                    succeeded.append(jid)
            except Exception as ex:
                failed.append((jid, str(ex)))

    await asyncio.gather(*[_recall_single(j) for j in valid_ids], return_exceptions=False)

    succ_cnt, fail_cnt = len(succeeded), len(failed)
    flow_desc = "已成功解除淘汰锁定并重新转入 **「AI 初评」** 队列（多维表格跟进状态已重置为「新线索」），系统将自动重新评估。"

    if succ_cnt > 0 and fail_cnt == 0:
        card = build_action_result_card(
            title=f"♻️ 选中的 {succ_cnt} 个误杀岗位召回成功！",
            succ_cnt=succ_cnt, target_queue="AI 初评", target_status="新线索",
            flow_desc=flow_desc, theme="turquoise",
        )
    elif succ_cnt > 0 and fail_cnt > 0:
        fail_details = "\n".join([f"  - `{jid}`: {err}" for jid, err in failed[:5]])
        card = build_action_result_card(
            title=f"⚠️ 误杀召回部分完成 (成功 {succ_cnt} / 失败 {fail_cnt})",
            succ_cnt=succ_cnt, target_queue="AI 初评", target_status="新线索",
            flow_desc="成功召回岗位已转入「AI 初评」队列，失败条目请核验权限后重试。",
            fail_cnt=fail_cnt, fail_details=fail_details, theme="orange",
        )
    else:
        fail_details = "\n".join([f"  - `{jid}`: {err}" for jid, err in failed[:5]]) if failed else "无有效待召回项目"
        card = build_action_result_card(
            title="❌ 岗位误杀召回未成功", succ_cnt=0, target_queue="AI 初评",
            target_status="失败", flow_desc="未能成功召回任何岗位，请检查网络或系统日志后重试。",
            fail_cnt=fail_cnt, fail_details=fail_details, theme="carmine",
        )

    await send_feishu_card(chat_id, card, "chat_id")


async def _batch_reject_jobs(chat_id: str, record_ids: list[str]) -> None:
    """确认淘汰处理（实现飞书多维表格与本地 SQLite 双端一致性，带真实失败告警与防假成功）。"""
    valid_ids = [r for r in (record_ids or []) if r and str(r).strip()]
    sem = _get_semaphore()
    db_path = _get_raw_db_path()

    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []

    if valid_ids:
        async def _reject_single(rid: str):
            async with sem:
                try:
                    if str(rid).startswith("rec"):
                        ok = await asyncio.to_thread(feishu_service.update_feishu_record, rid, {"跟进状态": "不合适"})
                        if not ok:
                            failed.append((rid, "多维表格更新返回 False"))
                            return
                        def _sync_db():
                            with sqlite3.connect(db_path) as conn:
                                conn.execute("UPDATE raw_jobs SET process_status = '已淘汰' WHERE feishu_record_id = ?", (rid,))
                        await asyncio.to_thread(_sync_db)
                    else:
                        def _sync_db_row():
                            with sqlite3.connect(db_path) as conn:
                                conn.execute("UPDATE raw_jobs SET process_status = '已淘汰' WHERE rowid = ?", (int(rid),))
                        await asyncio.to_thread(_sync_db_row)
                    succeeded.append(rid)
                except Exception as ex:
                    logger.warning(f"[战报淘汰] 记录 {rid} 归档更新异常: {ex}")
                    failed.append((rid, str(ex)))

        await asyncio.gather(*[_reject_single(r) for r in valid_ids], return_exceptions=False)

    succ_cnt = len(succeeded)
    fail_cnt = len(failed)

    if fail_cnt == 0:
        card = build_action_result_card(
            title=f"🗑️ {succ_cnt} 个淘汰岗位已确认归档" if succ_cnt > 0 else "🗑️ 淘汰确认归档已锁定",
            succ_cnt=succ_cnt,
            target_queue="已淘汰",
            target_status="不合适",
            flow_desc="本轮清洗排雷岗位已完成归档锁定，未触发召回，数据已双端一致落盘锁定。" if succ_cnt > 0 else "本轮无待归档记录，系统已完成状态锁定。",
            theme="wathet",
        )
    else:
        fail_details = "\n".join([f"  - `{rid}`: {err}" for rid, err in failed[:5]])
        card = build_action_result_card(
            title=f"⚠️ 淘汰归档部分异常 (成功 {succ_cnt} / 失败 {fail_cnt})",
            succ_cnt=succ_cnt,
            target_queue="已淘汰",
            target_status="不合适",
            flow_desc="部分岗位在多维表格同步归档状态时遇到异常，请在飞书多维表格中核对。",
            fail_cnt=fail_cnt,
            fail_details=fail_details,
            theme="orange",
        )

    await send_feishu_card(chat_id, card, "chat_id")
