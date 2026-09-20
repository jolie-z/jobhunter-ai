"""评估报告渲染：HTML 构建（V2 深色头卡+5分制点阵+迷你markdown）→ 长图 → 附件回写。

从 job_entry_chat.py 拆出（模块化瘦身）；被 materials_delivery 调用；
job_entry_chat 保留同名 re-export，既有调用方与测试路径不受影响。
"""
import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


# ==========================================
# 评估报告（HTML → 长图）
# ==========================================
_EVAL_REPORT_FIELD = "评估报告"

_REPORT_GRADE_COLORS = {"A": "#16a34a", "B": "#2563eb", "C": "#d97706", "D": "#ea580c", "E": "#dc2626", "F": "#7f1d1d"}

_REPORT_SECTIONS = (
    ("🔭 理想画像与能力信号", "理想画像与能力信号"),
    ("🧭 核心能力词典", "核心能力词典"),
    ("🔍 简历逐行审计", "简历逐行审计"),
    ("⚡ 高杠杆匹配点", "高杠杆匹配点"),
    ("🚨 致命硬伤与毒点", "致命硬伤与毒点"),
    ("🧪 破局行动计划", "破局行动计划"),
)

_REPORT_DIMENSIONS = (
    "核心-角色匹配", "核心-技能重合", "高权-职级资历", "高权-薪资契合",
    "高权-面试概率", "中权-公司阶段", "中权-赛道前景", "中权-成长空间",
)


def build_eval_report_html(fields: dict[str, Any]) -> str:
    """评估报告长图 V2：深色头卡 + 5 分制分段点阵 + 迷你 markdown 正文（粗体/【标签】/列表结构化）。"""
    import html as _html

    def _rt(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, str):
            return v.strip()
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, list):
            return "".join(str(i.get("text", "")) for i in v if isinstance(i, dict)).strip()
        return str(v).strip()

    grade = _rt(fields.get("综合评级 (A-F)")).upper()[:1] or "—"
    gcolor = _REPORT_GRADE_COLORS.get(grade, "#64748b")
    company = _rt(fields.get("公司名称")) or "未知公司"
    job = _rt(fields.get("岗位名称")) or "未知岗位"
    meta_chips = [x for x in (_rt(fields.get("招聘平台")), _rt(fields.get("城市")), _rt(fields.get("薪资"))) if x]

    # ── 迷你 markdown：转义后做粗体/【标签】/列表三种转换 ──
    def _inline(escaped: str) -> str:
        escaped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
        escaped = re.sub(r'【(.+?)】', r'<span class="chip">\1</span>', escaped)
        return escaped

    def _body_md(v: Any) -> str:
        text = _rt(v)
        if not text:
            return ""
        out: list[str] = []
        list_buf: list[str] = []

        def flush_list():
            if list_buf:
                out.append('<ul class="md-list">' + "".join(f"<li>{_inline(i)}</li>" for i in list_buf) + "</ul>")
                list_buf.clear()

        for raw_line in text.split("\n"):
            line = _html.escape(raw_line.strip())
            if not line:
                flush_list()
                continue
            if line.startswith("- "):
                list_buf.append(line[2:])
                continue
            flush_list()
            # 独立【标签】行 → 分组小标题；否则普通段落（内联粗体/chip 转换）
            if re.fullmatch(r'【[^】]+】', line):
                out.append(f'<div class="group-title">{_inline(line)}</div>')
            else:
                out.append(f'<p>{_inline(line)}</p>')
        flush_list()
        return "".join(out)

    # ── AI评估详情解析：**【维度名】** 分/5 + 原因段落 → 维度名 → 原因 ──
    reason_map: dict[str, str] = {}
    detail_raw = _rt(fields.get("AI评估详情"))
    if detail_raw:
        blocks = re.split(r'\*\*【', detail_raw)
        for block in blocks:
            if "】" not in block:
                continue
            dim_name = block.split("】")[0].strip()
            body = block.split("】", 1)[1]
            body = re.sub(r'^\s*\*\*\s*', '', body)  # 剥掉维度名后的收尾 **
            body = re.sub(r'^\s*\d\s*/\s*5\s*', '', body).strip()
            body = _html.escape(re.sub(r'【岗位基本信息】', '', body)).strip()
            if dim_name and body:
                reason_map[dim_name] = body

    # ── 8 维得分：5 分制分段点阵 + 逐维评分依据 ──
    def _dots(score: int) -> str:
        color = "#10b981" if score >= 4 else "#3b82f6" if score >= 3 else "#f59e0b" if score >= 2 else "#ef4444"
        return "".join(
            f'<span class="dot{" f" if i < score else ""}" style="{f"background:{color}" if i < score else ""}"></span>'
            for i in range(5)
        )

    score_rows = ""
    for label in _REPORT_DIMENSIONS:
        raw = fields.get(label)
        try:
            score = max(0, min(5, int(float(raw))))
        except (TypeError, ValueError):
            score = 0
        reason = next((v for k, v in reason_map.items() if k in label or label.endswith(k)), "")
        reason_html = f'<div class="score-reason">{_inline(reason)}</div>' if reason else ""
        score_rows += (
            f'<div class="score-row"><div class="score-label">{_html.escape(label)}</div>'
            f'<div class="dots">{_dots(score)}</div>'
            f'<div class="score-num" data-s="{score}">{score}/5</div></div>{reason_html}'
        )

    sections_html = ""
    for title, key in _REPORT_SECTIONS:
        body = _body_md(fields.get(key))
        if not body:
            continue
        sections_html += (
            f'<div class="sec-card" style="border-left-color:{gcolor}">'
            f'<div class="sec-title">{_html.escape(title)}</div>'
            f'<div class="sec-body">{body}</div></div>'
        )
    if not sections_html:
        sections_html = '<div class="sec-card"><div class="sec-body">（本岗位无深度评估报告）</div></div>'

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: "PingFang SC", "Microsoft YaHei", sans-serif; background: #eef2f7; }}
.resume-container {{ width: 760px; margin: 0 auto; background: #eef2f7; padding: 24px 20px; }}
.header {{ position: relative; border-radius: 18px; padding: 26px 30px; color: #fff;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 70%, {gcolor}33 160%); overflow: hidden; }}
.header::after {{ content: ""; position: absolute; right: -40px; top: -60px; width: 200px; height: 200px;
  border-radius: 50%; background: {gcolor}22; }}
.h-top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
.h-company {{ font-size: 15px; opacity: 0.85; margin-bottom: 6px; }}
.h-job {{ font-size: 26px; font-weight: 700; letter-spacing: 0.5px; }}
.chips {{ margin-top: 14px; display: flex; gap: 8px; flex-wrap: wrap; }}
.h-chip {{ font-size: 12px; padding: 3px 12px; border-radius: 20px; background: rgba(255,255,255,0.12);
  border: 1px solid rgba(255,255,255,0.25); }}
.grade-wrap {{ text-align: center; z-index: 1; }}
.grade-badge {{ width: 62px; height: 62px; border-radius: 18px; background: {gcolor}; color: #fff;
  font-size: 34px; font-weight: 800; display: flex; align-items: center; justify-content: center;
  box-shadow: 0 6px 18px {gcolor}55; }}
.grade-label {{ font-size: 11px; opacity: 0.75; margin-top: 6px; }}
.card {{ background: #fff; border-radius: 16px; padding: 20px 24px; margin-top: 16px;
  box-shadow: 0 1px 4px rgba(15,23,42,0.06); }}
.block-title {{ font-size: 16px; font-weight: 700; color: #0f172a; margin-bottom: 14px; }}
.score-row {{ display: flex; align-items: center; padding: 7px 0; border-bottom: 1px dashed #f1f5f9; }}
.score-row:last-child {{ border-bottom: none; }}
.score-label {{ width: 140px; font-size: 13px; color: #334155; flex-shrink: 0; }}
.dots {{ flex: 1; display: flex; gap: 6px; }}
.dot {{ width: 15px; height: 15px; border-radius: 50%; background: #e8edf3; }}
.score-num {{ width: 42px; text-align: right; font-size: 13px; font-weight: 700; color: #0f172a;
  font-variant-numeric: tabular-nums; }}
.score-reason {{ font-size: 12px; line-height: 1.7; color: #64748b; padding: 2px 0 10px 140px;
  border-bottom: 1px dashed #f1f5f9; }}
.score-reason .chip {{ background: #f1f5f9; color: #475569; }}
.sec-card {{ background: #fff; border-radius: 14px; padding: 18px 22px; margin-top: 14px;
  border-left: 4px solid {gcolor}; box-shadow: 0 1px 4px rgba(15,23,42,0.05); }}
.sec-title {{ font-size: 15px; font-weight: 700; color: #0f172a; margin-bottom: 10px; }}
.sec-body {{ font-size: 13px; line-height: 1.85; color: #475569; word-break: break-all; }}
.sec-body p {{ margin-bottom: 8px; }}
.sec-body strong {{ color: #0f172a; font-weight: 700; }}
.md-list {{ padding-left: 18px; margin-bottom: 8px; }}
.md-list li {{ margin-bottom: 5px; }}
.chip {{ display: inline-block; background: #eef2ff; color: #4338ca; border-radius: 6px;
  padding: 0 8px; font-size: 12px; font-weight: 600; margin: 0 2px; }}
.group-title {{ font-size: 13px; font-weight: 700; color: #334155; margin: 10px 0 6px; }}
.footer {{ margin: 20px 0 8px; font-size: 11px; color: #94a3b8; text-align: center; }}
</style></head>
<body><div class="resume-container">
  <div class="header">
    <div class="h-top">
      <div>
        <div class="h-company">{_html.escape(company)}</div>
        <div class="h-job">{_html.escape(job)}</div>
        <div class="chips">{''.join(f'<span class="h-chip">{_html.escape(m)}</span>' for m in meta_chips)}</div>
      </div>
      <div class="grade-wrap">
        <div class="grade-badge">{_html.escape(grade)}</div>
        <div class="grade-label">综合评级</div>
      </div>
    </div>
  </div>
  <div class="card">
    <div class="block-title">📊 AI 初评 · 8 维得分 <span style="font-size:12px;color:#94a3b8;font-weight:400">（满分 5）</span></div>
    {score_rows}
  </div>
  <div class="block-title" style="margin:22px 4px 2px">🧠 深度评估报告</div>
  {sections_html}
  <div class="footer">JobHunter 评估报告 · 跟进状态：{_html.escape(_rt(fields.get("跟进状态")) or "—")} · 已停在复核断点，绝不自动投递</div>
</div></body></html>"""


async def _generate_eval_report_image(fields: dict[str, Any]) -> bytes | None:
    """评估报告 HTML 渲染为长图 bytes；失败返回 None（不影响主流程）。"""
    from app.core.pdf_renderer import render_html_to_image

    try:
        return await render_html_to_image(build_eval_report_html(fields))
    except Exception as e:
        logger.warning(f"[聊天录入] 评估报告渲染失败: {e}")
        return None


async def _ensure_eval_report_field() -> bool:
    """确保多维表格存在「评估报告」附件字段（已存在或创建成功返回 True）。"""
    import httpx

    from app.core.feishu_client import feishu_client

    try:
        existing = await feishu_client.list_bitable_fields(settings.FEISHU_TABLE_ID_JOBS)
        if _EVAL_REPORT_FIELD in existing:
            return True
        token = await feishu_client.get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{feishu_client.app_token}/tables/{settings.FEISHU_TABLE_ID_JOBS}/fields"
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"field_name": _EVAL_REPORT_FIELD, "type": 17},
            )
            ok = resp.json().get("code") == 0
            if ok:
                logger.info(f"[聊天录入] 已创建多维表格字段「{_EVAL_REPORT_FIELD}」")
            return ok
    except Exception as e:
        logger.warning(f"[聊天录入] 确保「{_EVAL_REPORT_FIELD}」字段失败: {e}")
        return False


async def _store_eval_report_attachment(record_id: str, fields: dict[str, Any], report_image: bytes) -> None:
    """HTML 原件 + 报告长图存入「评估报告」附件字段。"""
    import tempfile

    from app.core.feishu_client import feishu_client
    from app.services.export_service import upload_file_to_feishu_async

    if not await _ensure_eval_report_field():
        return
    attachments = []
    tmp_paths = []
    try:
        html_str = build_eval_report_html(fields)
        for suffix, data in ((".html", html_str.encode()), (".jpg", report_image)):
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                tmp = f.name
                tmp_paths.append(tmp)
                f.write(data)
        html_token, img_token = await asyncio.gather(
            upload_file_to_feishu_async(Path(tmp_paths[0]), file_name="评估报告.html"),
            upload_file_to_feishu_async(Path(tmp_paths[1]), file_name="评估报告-长图.jpg"),
        )
        if html_token:
            attachments.append({"file_token": html_token, "name": "评估报告.html"})
        if img_token:
            attachments.append({"file_token": img_token, "name": "评估报告-长图.jpg"})
        if attachments:
            await feishu_client.update_record(settings.FEISHU_TABLE_ID_JOBS, record_id, {_EVAL_REPORT_FIELD: attachments})
            logger.info(f"[聊天录入] 评估报告已存入「{_EVAL_REPORT_FIELD}」附件字段 | record_id={record_id}")
    except Exception as e:
        logger.warning(f"[聊天录入] 评估报告存档失败（不影响发送）: {e}")
    finally:
        for tmp in tmp_paths:
            Path(tmp).unlink(missing_ok=True)
