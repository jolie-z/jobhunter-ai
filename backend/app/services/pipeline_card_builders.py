# backend/app/services/pipeline_card_builders.py
"""
全链路指挥中心 · 战报子卡片渲染构建器。
负责将结构化的 JobCardItem 渲染为飞书交互式卡片 (Card 2.0 协议)：
1. build_sub_card_ab：精投岗位清单及放行卡片
2. build_sub_card_mass：海投复核岗位清单及放行卡片
3. build_sub_card_rejected：淘汰岗位清单及召回放行卡片
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.services.action_card_builders import build_action_result_card  # noqa: F401

SUB_CARD_MAX: int = 20


def extract_job_record_id(job: Any) -> str:
    """统一从岗位字典中提取权威 record_id，严格遵循 record_id > job_id 优先级。"""
    if not isinstance(job, dict):
        return ""
    return str(job.get("record_id") or job.get("job_id") or "").strip()


@dataclass
class JobCardItem:
    """卡片渲染与交互的统一结构化数据项。"""
    job_id: str             # 飞书 record_id 或本地 SQLite rowid
    title: str              # [平台] 公司 - 岗位
    grade: str              # 评级或状态简述 (A级 / B级 / 淘汰原因 / 公司规模)
    short_name: str         # 简写名称，供多选下拉框展示
    color: str = "blue"     # 飞书字体颜色
    detail_url: str = ""    # 直达详情链接
    extra_info: str = ""    # 额外元信息 (如淘汰原因、大厂规模等)


def get_base_url() -> str:
    """获取飞书多维表格的 Base URL。"""
    app_token = getattr(settings, "FEISHU_BITABLE_APP_TOKEN", "") or getattr(settings, "FEISHU_APP_TOKEN", "")
    table_id = getattr(settings, "FEISHU_TABLE_ID_JOBS", "") or getattr(settings, "FEISHU_TABLE_ID", "")
    return f"https://feishu.cn/base/{app_token}?table={table_id}" if app_token and table_id else ""


def build_sub_card_ab(jobs: list[JobCardItem] | None = None, total: int | None = None) -> dict[str, Any]:
    """构建【🌟 精投岗位清单及放行】卡片。"""
    job_list = jobs if jobs is not None else []
    if not job_list:
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "🌟 精投岗位清单及放行 (0 条待审)"}, "template": "indigo"},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": "🎉 **本轮暂无待审批的精投岗位**\n所有精投候选均已放行或已在待投递队列中，无需重复处理。"}},
                {"tag": "hr"},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": "JobHunter 全链路指挥中心 · 状态已同步"}]}
            ]
        }

    card_lines = []
    card_options = []
    for item in job_list:
        line = f"{item.title}\n   <font color='{item.color}'>**[{item.grade}]**</font>"
        if item.detail_url:
            line += f" ｜ [🔍 详情直达]({item.detail_url})"
        card_lines.append(line)
        card_options.append({
            "text": {"tag": "plain_text", "content": f"[{item.grade}] {item.short_name}"},
            "value": item.job_id
        })

    title_text = f"🌟 精投岗位清单及放行 (共 {len(job_list)} 条就绪)"
    if total and total > len(job_list):
        title_text = f"🌟 精投岗位清单及放行 (本轮共 {total} 条 · 展示前 {len(job_list)} 条)"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title_text},
            "template": "indigo"
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "📋 **本轮精投岗位完整清单 (展示上限 20 条，更多岗位信息前往电脑端查看)**：\n\n"
                        + "📝 均已完成定制简历改写与针对性话术，勾选或一键放行后将移入「待投递」队列：\n\n"
                        + "\n\n".join(card_lines)
                    )
                }
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": "**🎯 方式一：多选勾选特定岗位放行**"}},
            {
                "tag": "form",
                "name": "form_approve_ab",
                "elements": [
                    {
                        "tag": "multi_select_static",
                        "name": "selected_jobs",
                        "placeholder": {"tag": "plain_text", "content": "☑️ 点击此处下拉，勾选要放行的精投岗位 (支持多选)..."},
                        "options": card_options
                    },
                    {
                        "tag": "button",
                        "name": "btn_approve_selected_ab",
                        "text": {"tag": "plain_text", "content": "✅ 放行已勾选的精投岗位"},
                        "type": "primary",
                        "action_type": "form_submit",
                        "value": {"action": "approve_selected_ab"}
                    }
                ]
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": "**⚡ 方式二：一键全选快速放行**"}},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": f"🚀 一键全部放行本轮 {len(job_list)} 个精投岗位"},
                        "type": "primary",
                        "value": {"action": "approve_all_ab", "record_ids": [j.job_id for j in job_list]}
                    }
                ]
            },
            {
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": "JobHunter · 放行后的岗位将进入「待投递」池，由每日发射定时任务自动投出"}]
            }
        ]
    }


def build_sub_card_mass(jobs: list[JobCardItem] | None = None, total: int | None = None) -> dict[str, Any]:
    """构建【🏢 海投复核岗位清单及放行】卡片。"""
    job_list = jobs if jobs is not None else []
    if not job_list:
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "🏢 海投复核岗位清单及放行 (0 条待审)"}, "template": "wathet"},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": "🎉 **本轮无被拦截的大厂海投岗位**\n未触发千人大厂安检风控，常规海投通道顺畅。"}},
                {"tag": "hr"},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": "JobHunter 全链路指挥中心 · 状态已同步"}]}
            ]
        }

    card_lines = []
    card_options = []
    for item in job_list:
        line = f"{item.title}\n   🏢 {item.extra_info or item.grade}"
        if item.detail_url:
            line += f" ｜ [🔍 详情直达]({item.detail_url})"
        card_lines.append(line)
        card_options.append({
            "text": {"tag": "plain_text", "content": f"{item.short_name}"},
            "value": item.job_id
        })

    title_text = f"🏢 海投复核岗位清单及放行 (共 {len(job_list)} 条待审)"
    if total and total > len(job_list):
        title_text = f"🏢 海投复核岗位清单及放行 (本轮共 {total} 条 · 展示前 {len(job_list)} 条)"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title_text},
            "template": "wathet"
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "📋 **本轮海投大厂安检拦截清单 (展示上限 20 条)**：\n\n"
                        + "⚠️ 该类岗位为海投岗位，但因所属企业属于 **千人以上大厂规模**，系统启动风控踩刹车挂起，避免盲目海投浪费大厂机会：\n\n"
                        + "\n\n".join(card_lines)
                    )
                }
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": "**🎯 方式一：多选勾选放行大厂海投**"}},
            {
                "tag": "form",
                "name": "form_approve_mass",
                "elements": [
                    {
                        "tag": "multi_select_static",
                        "name": "selected_jobs",
                        "placeholder": {"tag": "plain_text", "content": "☑️ 点击此处下拉，勾选放行的大厂岗位 (支持多选)..."},
                        "options": card_options
                    },
                    {
                        "tag": "button",
                        "name": "btn_approve_selected_mass",
                        "text": {"tag": "plain_text", "content": "✅ 放行已勾选的大厂海投岗"},
                        "type": "primary",
                        "action_type": "form_submit",
                        "value": {"action": "approve_selected_mass"}
                    }
                ]
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": "**⚡ 方式二：一键全选放行海投**"}},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": f"🚀 一键放行全部 {len(job_list)} 个大厂海投岗"},
                        "type": "primary",
                        "value": {"action": "approve_all_mass", "record_ids": [j.job_id for j in job_list]}
                    }
                ]
            },
            {
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": "JobHunter · 放行后将装配标准通用海投物料并推入「待投递」队列"}]
            }
        ]
    }


def build_sub_card_rejected(jobs: list[JobCardItem] | None = None, total: int | None = None) -> dict[str, Any]:
    """构建【🗑️ 淘汰岗位清单及召回放行】卡片。"""
    job_list = jobs if jobs is not None else []
    if not job_list:
        return {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "🗑️ 淘汰岗位清单 (0 条淘汰)"}, "template": "carmine"},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": "🎉 **本轮无淘汰岗位**\n抓取岗位均已顺利通过硬清洗与 AI 排雷通道。"}},
                {"tag": "hr"},
                {"tag": "note", "elements": [{"tag": "plain_text", "content": "JobHunter 全链路指挥中心 · 状态已同步"}]}
            ]
        }

    card_lines = []
    card_options = []
    for item in job_list:
        line = f"{item.title}\n   🚫 <font color='red'>{item.extra_info or item.grade}</font>"
        if item.detail_url:
            line += f" ｜ [🔍 详情直达]({item.detail_url})"
        card_lines.append(line)
        card_options.append({
            "text": {"tag": "plain_text", "content": item.short_name},
            "value": item.job_id
        })

    title_text = f"🗑️ 淘汰岗位清单及召回 (共 {len(job_list)} 条淘汰)"
    if total and total > len(job_list):
        title_text = f"🗑️ 淘汰岗位清单及召回 (本轮共 {total} 条 · 展示前 {len(job_list)} 条)"

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title_text},
            "template": "carmine"
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "📋 **本轮规则清洗 / AI排雷 / 提前终止岗位清单 (展示上限 20 条)**：\n\n"
                        + "⚠️ 如果你认为某岗位属于 AI 误判或仍想尝试初评，可在下方勾选进行**「误杀召回」**：\n\n"
                        + "\n\n".join(card_lines)
                    )
                }
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": "**🎯 误杀召回：勾选误杀岗位并确认召回**"}},
            {
                "tag": "form",
                "name": "form_recall_rejected",
                "elements": [
                    {
                        "tag": "multi_select_static",
                        "name": "selected_jobs",
                        "placeholder": {"tag": "plain_text", "content": "☑️ 点击此处下拉，勾选要误杀召回的岗位 (支持多选)..."},
                        "options": card_options
                    },
                    {
                        "tag": "button",
                        "name": "btn_recall_selected_rejected",
                        "text": {"tag": "plain_text", "content": "♻️ 确认召回已勾选岗位进入 AI 初评"},
                        "type": "primary",
                        "action_type": "form_submit",
                        "value": {"action": "recall_selected_rejected"}
                    }
                ]
            },
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "确认淘汰"},
                        "type": "default",
                        "value": {"action": "confirm_trash", "record_ids": [j.job_id for j in job_list]}
                    }
                ]
            },
            {
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": "JobHunter · 召回后的岗位将解除淘汰锁定，重新转入「AI 初评」队列；点击「确认淘汰」将彻底完成归档"}]
            }
        ]
    }




def build_master_pipeline_card(
    task_time: str = "",
    duration_mins: int = 28,
    total_scraped: int = 20,
    hard_passed: int = 20,
    hard_rejected: int = 0,
    ai_passed: int = 16,
    ai_rejected: int = 4,
    precision_cnt: int = 8,
    channel_counts: dict[str, int] | None = None,
    grade_counts: dict[str, int] | None = None,
    mass_review_cnt: int = 4,
    other_review_cnt: int = 0,
    dedup_count: int = 0,
    ab_record_ids: list[str] | None = None,
    mass_record_ids: list[str] | None = None,
    rejected_record_ids: list[str] | None = None,
) -> dict[str, Any]:
    """构建【📊 全链路指挥中心 · 定时任务】主战报卡片（严格对齐图 2 规范标准）。"""
    t_str = task_time or datetime.now().strftime("%Y-%m-%d %H:%M")
    hhmm = t_str.split(" ")[-1] if " " in t_str else "09:00"

    total_ai = ai_passed + ai_rejected
    ai_rate = round((ai_passed / total_ai) * 100) if total_ai > 0 else (100 if ai_passed > 0 else 0)

    ch = channel_counts if channel_counts is not None else {"BOSS直聘": 5, "猎聘": 5, "智联招聘": 5, "51job": 5}
    gr = grade_counts if grade_counts is not None else {"A": 2, "B": 6, "C": 4, "D/F": 3}
    total_eval = sum(gr.values())
    total_other = mass_review_cnt + other_review_cnt

    # 精投占比分母规范：以实际进入初评的岗位数为分母
    eval_cnt = total_eval if total_eval > 0 else (ai_passed if ai_passed > 0 else 1)
    prec_rate = round((precision_cnt / eval_cnt) * 100)

    # 初评与去重说明
    eval_header = f"· **初评等级** (共 {total_eval} 条进入评估"
    if dedup_count > 0:
        eval_header += f" ｜ 🧬 疑似重复：<font color='blue'>**{dedup_count}**</font> 条"
    eval_header += ")：\n"

    eval_extra = ""
    # 真实异常中断防御检测：排除去重拦截后仍有岗位丢失
    eval_loss = max(0, (ai_passed - dedup_count) - total_eval)
    if eval_loss > 0:
        eval_extra = f"\n  ⚠️ 评估异常中断：<font color='red'>**{eval_loss}**</font> 条"

    def _build_btn_val(action_name: str, ids: list[str] | None) -> dict[str, Any]:
        val: dict[str, Any] = {"action": action_name}
        if ids is not None:
            id_list = list(ids)
            val["record_ids"] = id_list[:SUB_CARD_MAX]
            val["total"] = len(id_list)
        return val

    ab_val = _build_btn_val("open_ab_card", ab_record_ids)
    mass_val = _build_btn_val("open_mass_card", mass_record_ids)
    rej_val = _build_btn_val("open_rejected_card", rejected_record_ids)

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📊 全链路指挥中心 · 定时任务 · {hhmm}"},
            "template": "blue"
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"⏱ **{t_str}** · 用时约 **{duration_mins} 分钟** · <font color='green'>已完成</font>"
                }
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": "**⚡ 本轮流水线流转效能**"}},
            {
                "tag": "column_set",
                "flex_mode": "bisect",
                "columns": [
                    {
                        "tag": "column", "width": "weighted", "weight": 1, "background_style": "grey",
                        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": f"<font color='grey'>本轮抓取</font>\n<font color='blue'>**{total_scraped} 条**</font>\n<font color='grey'>4 平台聚合</font>"}}]
                    },
                    {
                        "tag": "column", "width": "weighted", "weight": 1, "background_style": "grey",
                        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": f"<font color='grey'>硬清洗通过</font>\n<font color='green'>**{hard_passed} 条**</font>\n<font color='grey'>拦截 {hard_rejected} 条</font>"}}]
                    },
                    {
                        "tag": "column", "width": "weighted", "weight": 1, "background_style": "grey",
                        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": f"<font color='grey'>AI清洗通过</font>\n<font color='green'>**{ai_passed} 条**</font>\n<font color='grey'>拦截 {ai_rejected} 条，通过率 {ai_rate}%</font>"}}]
                    },
                    {
                        "tag": "column", "width": "weighted", "weight": 1, "background_style": "grey",
                        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": f"<font color='grey'>精投岗位</font>\n<font color='orange'>**{precision_cnt} 条**</font>\n<font color='grey'>精投占比 {prec_rate}%</font>"}}]
                    }
                ]
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        "**📡 渠道来源与初评梯队**\n"
                        "· **抓取渠道**：\n"
                        f"  BOSS直聘：<font color='blue'>**{ch.get('BOSS直聘', 0)}**</font> 条 ｜ 猎聘：<font color='blue'>**{ch.get('猎聘', 0)}**</font> 条\n"
                        f"  智联招聘：<font color='blue'>**{ch.get('智联招聘', 0)}**</font> 条 ｜ 51job：<font color='blue'>**{ch.get('51job', 0)}**</font> 条\n"
                        f"{eval_header}"
                        f"  🌟 A级：<font color='green'>**{gr.get('A', 0)}**</font> 条 ｜ ✨ B级：<font color='blue'>**{gr.get('B', 0)}**</font> 条\n"
                        f"  🔹 C级：<font color='grey'>**{gr.get('C', 0)}**</font> 条 ｜ ⚪ D/F级：<font color='grey'>**{gr.get('D/F', gr.get('D', 0))}**</font> 条"
                        f"{eval_extra}"
                    )
                }
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**🌟 精投岗位概览 (共 {precision_cnt} 条)**\n"
                        "📝 全部已生成定制简历与针对性话术，挂起等待人工审批放行。"
                    )
                }
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**⏸️ 其他待审批 ({total_other} 条 · 海投撞门槛)**\n"
                        f"· 触发海投规则审批（如大厂）的岗位有 <font color='blue'>**{mass_review_cnt}**</font> 条\n"
                        f"· 其他情况的岗位有 <font color='grey'>**{other_review_cnt}**</font> 条"
                    )
                }
            },
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🌟 精投岗位清单及放行"},
                        "type": "primary",
                        "value": ab_val
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🏢 海投复核岗位清单及放行"},
                        "type": "default",
                        "value": mass_val
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "🗑️ 淘汰岗位清单及放行"},
                        "type": "danger",
                        "value": rej_val
                    }
                ]
            },
            {"tag": "note", "elements": [{"tag": "plain_text", "content": "JobHunter 全链路指挥中心 · 点击上方卡片按钮可调出各分流清单与多选放行组件"}]}
        ]
    }
