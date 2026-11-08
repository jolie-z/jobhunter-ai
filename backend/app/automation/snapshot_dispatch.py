"""jobs_snapshot 第 4 段分诊与失败卡构造（2026-11-02 拆分子任务）。

从 snapshot_service.py（原 1044 行，超仓库 <500 行门禁）抽离：
- classify_feishu_followup：跟进状态→看板分区映射纯函数（生产/测试共用）
- build_failure_job / build_failure_suggestion / _triage_classify：失败台账卡组装
- _mass_review_reason：海投岗停留人工复核的真实原因复算

依赖方向：本模块只依赖 app/core 词表与 workflow（延迟导入），snapshot_service
反向 import 本模块——保持"读快照"主文件聚焦聚合流程。
"""
import logging
from typing import Any

from app.core import process_status
from app.core.feishu_utils import POST_DELIVERY_FOLLOW_STATUSES
from app.core.process_status import APPROVAL_FOLLOW_STATUSES

logger = logging.getLogger(__name__)


def _mass_review_reason(grade: Any, platform: Any, feishu_fields: dict, config: dict) -> str:
    """复算海投岗停留「人工复核」的真实原因，替换旧硬编码「命中大厂规则，待人工过目」。

    2026-10-07 Windows 真机实证：待审批岗绝大多数是「评级 B 未在自动投递白名单」而非
    大厂规模拦截，旧文案让用户误以为 5000 阈值失效。这里与 workflow.evaluate_delivery_gate
    用同一判定口径复算（config 注入避免逐条读库）；安检全过却停在复核 = 物料挂载未完成
    （\\tmp 路径 bug 期间的遗留形态），文案如实区分。
    """
    try:
        from app.automation.workflow import evaluate_delivery_gate

        state = {"grade": grade, "platform": platform or "", "feishu_fields": feishu_fields or {}}
        gate_ok, reason = evaluate_delivery_gate(state, config=config)
        if gate_ok:
            return "安检已过，物料未就绪/流程中断，待人工处理"
        return f"{reason}，待人工过目"
    except Exception as e:
        logger.warning(f"复算海投拦截原因失败，回退通用文案: {e}")
        return "命中大厂规则，待人工过目"




def _triage_classify(error: str) -> str:
    """快照展示用：复用 L1 分诊对错误文本的分类结果。"""
    try:
        from app.automation.failure_triage import classify_delivery_failure
        return classify_delivery_failure(error)
    except Exception:
        return "unknown"




def build_failure_suggestion(err_msg: str) -> str:
    """按失败文本生成执行失败卡片的推进建议。

    结构化标签（引擎明确断言的事实）必须先于自由关键词匹配：
    「[物料] 打招呼语为非法内容」含"打招呼"却是物料问题，先匹配自由关键词会误导向补发打招呼。
    "附件已送达"只在引擎带 [微聊受阻] 标签时才成立，自由文本命中不做该断言。
    """
    text = str(err_msg or "")
    lower = text.lower()
    if "附件未送达" in text:
        return "打招呼语已成功送达！简历附件选择受阻，可点击右下角【重试】单独补发附件简历。"
    if "微聊受阻" in text:
        return "附件简历已成功送达！可点击右下角【重试】单独补发专属打招呼语。"
    if any(k in text for k in ("[下架]", "已下线", "已下架", "已关闭")):
        return "岗位已在对应平台下架或关闭，建议点击【放弃】移除。"
    if any(k in text for k in ("[物料]", "缺少", "简历下载失败")):
        return "物料缺失或异常，请在飞书检查简历附件与字段后重试。"
    if any(k in text for k in ("[登录]", "登录态", "未登录")):
        return "检测到平台会话失效，请前往对应浏览器重新扫码登录后点击【重试】。"
    if "超时" in text or "timeout" in lower:
        return "投递过程等待超时，多为页面加载或网络波动，可稍后点击【重试】。"
    if "tab" in lower:
        return "已修复微聊标签页捕获逻辑，可点击重试重新发射。"
    if any(k in text for k in ("微聊", "打招呼")):
        return "打招呼环节受阻，可点击右下角【重试】重新发起沟通。"
    return "建议检查投递日志或平台页面状态后点击重试。"




def classify_feishu_followup(f_status: str, grade: str, is_custom_job: bool = False,
                             pipeline_stopped: bool = False, crawl_recent: bool = False) -> dict:
    """第 4 段「跟进状态→看板分区」映射的纯函数（2026-11-02 审计 CR-B2-R1-P4）。

    生产第 4 段分支与测试共用同一实现，杜绝测试文件重抄一份逻辑、生产改错测试
    照样全过的验证盲区。入参=第 4 段分支的真实输入，出参 dict(status/node/sub_status/
    last_action_desc[/failure_reason])。分支序与生产一致：显式状态表 → 终态/失败 →
    评级 → 停机/运行。「已拒绝」亦收敛于此（CR-B2-R2-P2）。
    """
    norm = str(grade or "").strip().upper()
    has_rating = norm in ("A", "B", "C", "D")
    is_waiting = f_status in APPROVAL_FOLLOW_STATUSES

    if f_status == "已拒绝":
        return {"status": "rejected_manual", "node": "manual_rejected", "sub_status": "rejected_manual",
                "last_action_desc": "老板已拒绝"}
    if is_waiting:
        if f_status == "疑似重复":
            return {"status": "waiting", "node": "manual_review_node", "sub_status": "waiting",
                    "last_action_desc": "疑似重复岗位，待人工裁决"}
        # 显式状态表形态的海投文案：原第 4 段 is_waiting 分支即 _mass_review_reason
        # 复算（依赖 grade/platform/fields/config），由调用方在 status==waiting 且
        # f_status∈APPROVAL_FOLLOW_STATUSES 时回填，此处海投给占位文案
        return {"status": "waiting", "node": "manual_review_node", "sub_status": "waiting",
                "last_action_desc": "已生成定制简历，待细审放行" if is_custom_job else "待审批"}
    if f_status == "待投递":
        return {"status": "ready_to_deliver", "node": "ready_to_deliver", "sub_status": "ready_to_deliver",
                "last_action_desc": "已加入待投递队列"}
    if f_status == "已投递":
        return {"status": "delivered", "node": "delivery_node", "sub_status": "ai_eval",
                "last_action_desc": "已成功投递"}
    if f_status in ("已完成初步评估", "已深度初步评估", "已完成深度评估"):
        return {"status": "done", "node": "evaluate_node", "sub_status": "eval_done",
                "last_action_desc": "已完成初步评估"}
    if f_status in POST_DELIVERY_FOLLOW_STATUSES or f_status in ("已下架",):
        # 已下架不在 POST_DELIVERY 词表（它是"死链"而非"投递后段"），单独列出
        return {"status": "done", "node": "post_delivery", "sub_status": f_status,
                "last_action_desc": f"岗位已{f_status}" if f_status == "已下架" else f"招聘流程推进中（{f_status}）"}
    if f_status in ("AI评估失败", "投递失败"):
        # node 按失败阶段区分（CR-B2-R1-P2）：AI评估失败归评估节点、投递失败归投递节点；
        # failure_info 由调用方补充（第4段卡带 f_status 作为 reason，不再回退万能文案）
        is_eval_fail = f_status == "AI评估失败"
        return {"status": "failed",
                "node": "evaluate_node" if is_eval_fail else "delivery_node",
                "sub_status": "eval_failed" if is_eval_fail else "delivery_failed",
                "last_action_desc": f"{f_status}，可重试",
                "failure_reason": f_status}
    if f_status == "不合适":
        return {"status": "rejected_manual", "node": "manual_rejected", "sub_status": "rejected_manual",
                "last_action_desc": "飞书侧标记不合适"}
    if norm in ("E", "F"):
        return {"status": "rejected_auto", "node": "clean_rule_rejected", "sub_status": "rejected_auto",
                "last_action_desc": "初评未达门槛，已自动淘汰"}
    if f_status in ("清洗淘汰", "ai清洗淘汰", "ai 清洗淘汰") and not has_rating:
        return {"status": "rejected_auto", "node": "clean_rule_rejected", "sub_status": "rejected_auto",
                "last_action_desc": "触发AI排雷规则淘汰" if f_status.startswith("ai") else "触发规则清洗淘汰"}
    if has_rating:
        return {"status": "waiting", "node": "manual_review_node", "sub_status": "waiting",
                "last_action_desc": "已生成定制简历，待细审放行" if is_custom_job else "评估完成，海投物料装配中，过安检后自动进待投递"}
    if pipeline_stopped:
        return {"status": "waiting", "node": "evaluate_node",
                "sub_status": "eval_pending" if crawl_recent else "eval_incomplete",
                "last_action_desc": "已入库，评估排队中" if crawl_recent else "本轮评估未完成，建议在详情页重新评估"}
    return {"status": "running", "node": "evaluate_node", "sub_status": "ai_eval", "last_action_desc": "流水线处理中"}




def build_failure_job(fid: str, fval: dict, *, is_current_run: bool, crawl_time: str) -> dict:
    """把失败台账条目组装成执行失败 Tab 的卡片数据。

    reason 必须原样透传台账里的引擎真实报错：前端 failed-job-card 在该字段缺失时
    会回退成固定文案「流水线节点处理超时或网络连接异常」，等于把真实原因再次抹平。
    """
    err_msg = str(fval.get("error") or "投递异常")
    failed_at = str(fval.get("failed_at") or "")
    triage_kind = _triage_classify(err_msg)
    return {
        "job_id": fid,
        "job_name": fval.get("job_name") or "投递受阻岗位",
        "company_name": fval.get("company_name") or "",
        "platform": fval.get("platform") or "zhilian",
        # 失败台账没记录评级时不要伪造 D：假评级会让「已评估」分子虚高，
        # 也会让失败卡看起来像完成过初评。失败卡自身对空评级有降级渲染。
        "grade": fval.get("grade") or "",
        "status": "error",
        "node": "error",
        "failure_info": {
            "stage": "delivery",
            "step": fval.get("step") or "自动投递阶段",
            "reason": err_msg,
            "suggestion": build_failure_suggestion(err_msg),
            "can_retry": True,
            "failure_count": int(fval.get("failure_count") or 1),
            "triage": triage_kind,
            "triage_note": ("持久性故障：自动重试无法自愈，已停止波次自动发射" if triage_kind == "persistent"
                            else ("暂时性故障：保留自动重试，连续失败达上限后停止" if triage_kind == "transient" else "")),
            "heal_log": fval.get("heal_log") or [],
            "diagnosis": fval.get("diagnosis") or None,
        },
        "is_current_run": is_current_run,
        "crawl_time": crawl_time,
        "last_action_time": failed_at or crawl_time,
        "last_action_desc": "尝试自动投递受阻",
    }


_SQLITE_REJECTED_STATUSES = process_status.REJECTED_STATUSES


_RUNNING_CLEAN_STATES = (process_status.CLEANING, process_status.PENDING_AI, process_status.PENDING_AI_LEGACY)


def _map_sqlite_process_status(p_status: str) -> dict[str, str | None]:
    """把 raw_jobs.process_status 映射为快照卡片的 {status, sub_status, last_action_desc}。

    取值一律来自 app/core/process_status 词表(含旧变体归一),不再内联硬编码字符串。
    """
    p_status = process_status.normalize_legacy((p_status or "").strip())
    if not p_status:
        # NULL/空串真实可达（import_service 自建表无默认值）——按建表默认「已存入数据」语义呈现
        return {"status": "scraped", "sub_status": None, "last_action_desc": "入库待清洗"}
    if p_status == process_status.REJECT_AI:
        return {"status": "rejected", "sub_status": None, "last_action_desc": "触发AI排雷规则淘汰"}
    if p_status == process_status.REJECT_RULE:
        return {"status": "rejected", "sub_status": None, "last_action_desc": "触发规则清洗淘汰"}
    if p_status == process_status.REJECT_CONFIRMED:
        return {"status": "rejected", "sub_status": None, "last_action_desc": "已确认淘汰"}
    if p_status == process_status.REJECT_ARCHIVED_LEGACY:
        # [存量兼容] 2026-10-09 前飞书卡片归档旧词（现行归档统一写「已确认淘汰」）
        return {"status": "rejected", "sub_status": None, "last_action_desc": "已确认淘汰（历史归档）"}
    if p_status == process_status.ABANDONED:
        return {"status": "rejected", "sub_status": None, "last_action_desc": "已放弃"}
    if p_status == process_status.STORED:
        return {"status": "scraped", "sub_status": None, "last_action_desc": "入库待清洗"}
    if p_status == process_status.RECALL_PENDING_EVAL:
        return {"status": "running", "sub_status": "ai_eval_queued", "last_action_desc": "♻️ 已召回，等待AI重新初评"}
    if p_status == process_status.PUSH_PENDING:
        return {"status": "running", "sub_status": "ai_eval_queued", "last_action_desc": "已入库，待推送至飞书"}
    if p_status == process_status.SCORED:
        return {"status": "running", "sub_status": "ai_eval_queued", "last_action_desc": "AI打分完成，等待流转"}
    if p_status in _RUNNING_CLEAN_STATES:
        return {"status": "running", "sub_status": "ai_eval_queued", "last_action_desc": "清洗排雷处理中"}
    if p_status == process_status.READY_TO_DELIVER:
        return {"status": "ready_to_deliver", "sub_status": None, "last_action_desc": "待投递"}
    if p_status == process_status.SYNCED:
        return {"status": "done", "sub_status": None, "last_action_desc": "已同步飞书"}
    # 未知状态兜底：按淘汰呈现+告警文案（绝不伪装成活跃流转态——词表漂移宁可显眼也不误导）
    return {
        "status": "rejected",
        "sub_status": None,
        "last_action_desc": f"⚠️ 未知状态「{p_status[:12]}」按淘汰兜底，请反馈开发者",
    }
