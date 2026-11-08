import asyncio
import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.llm_client import get_openai_client

logger = logging.getLogger("resume_structurer")

# ---------------------------------------------------------------------------
# Pydantic Models for Structured Resume Data
# ---------------------------------------------------------------------------
# extra="allow"：LLM 可能输出 schema 之外的字段/模块，默认 extra=ignore 会在数据层
# 静默丢弃导致内容丢失（2026-09-23 简历库七项修复），改为保留；json_to_markdown
# 末尾对未被消费的顶层额外模块有兜底渲染（见 _render_unconsumed_modules）。
class _PreserveExtraModel(BaseModel):
    model_config = {"extra": "allow"}


class PersonalInfo(_PreserveExtraModel):
    name: str = ""
    title: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    website: str | None = None

class Experience(_PreserveExtraModel):
    title: str = ""
    company: str = ""
    location: str | None = None
    years: str = ""
    description: list[str] = Field(default_factory=list)

class Education(_PreserveExtraModel):
    institution: str = ""
    major: str = ""
    degree: str = ""
    years: str = ""
    description: str | None = None

class Project(_PreserveExtraModel):
    name: str = ""
    role: str = ""
    years: str = ""
    description: list[str] = Field(default_factory=list)

class AdditionalInfo(_PreserveExtraModel):
    # skillOverview：承接"专业技能"段落中的散文/描述性文字（非 bullet 部分），
    # 修复描述被结构性丢弃的问题；旧数据无此字段时默认空串，完全向后兼容。
    skillOverview: str = ""
    technicalSkills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    certificationsTraining: list[str] = Field(default_factory=list)

class ResumeData(_PreserveExtraModel):
    personalInfo: PersonalInfo = Field(default_factory=PersonalInfo)
    summary: str = ""
    workExperience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    personalProjects: list[Project] = Field(default_factory=list)
    additional: AdditionalInfo = Field(default_factory=AdditionalInfo)
    moduleOrder: list[str] = Field(default_factory=list)
    moduleTitles: dict = Field(default_factory=dict)
    customModules: dict[str, list[Experience]] = Field(default_factory=dict)

# ---------------------------------------------------------------------------
# ATS Target Diff Model
# ---------------------------------------------------------------------------
class ResumeChange(BaseModel):
    path: str
    action: str
    original: str | None = None
    value: Any
    reason: str

# ---------------------------------------------------------------------------
# Parser Logic (Markdown -> JSON AST)
# ---------------------------------------------------------------------------
PARSE_RESUME_PROMPT = """You are an expert resume parser. Your task is to extract all information from the provided Markdown resume and structure it EXACTLY according to the JSON schema below.
DO NOT leave out any details, bullet points, or skills. Preserve the original language and tone.
CRITICAL: 简历上给的是什么大模块，回来就是什么模块名称，不能擅自改变内容！请通过识别 `# ` 开头的一级标题，按顺序记录在 moduleOrder 中，并将确切的原标题保存在 moduleTitles 中。
如果你遇到了无法归类于以下标准模块（summary, workExperience, education, personalProjects, additional）的全新模块（如“获奖经历”、“开源贡献”等），请为你识别到的这个模块自行想一个拼音或英文小写 key（例如 "awards"），将其加入 moduleOrder 和 moduleTitles 中，并存入 customModules[key] 中。
CUSTOM MODULES RULE (CRITICAL): customModules 条目禁止用 title/company/years 承载内容——这些字段语义不通用（论文/获奖/开源各不相同），填错位置会导致内容对用户不可见。每个条目的所有文字必须【逐行逐字】放进 description（保持原文行序，一行一个元素），title/company/years 一律输出空字符串 ""。

### SCHEMA EXPECTED ###
{
  "moduleOrder": ["summary", "additional", "workExperience", "personalProjects", "education"],
  "moduleTitles": {
    "summary": "个人总结",
    "additional": "专业技能",
    "workExperience": "工作经历",
    "personalProjects": "项目经历",
    "education": "教育背景"
  },
  "personalInfo": {"name": "", "title": "", "email": "", "phone": "", "location": ""},
  "summary": "",
  "workExperience": [
    {
      "title": "Job Title",
      "company": "Company Name",
      "years": "YYYY - YYYY",
      "description": ["Bullet point 1", "Bullet point 2"]
    }
  ],
  "education": [
    {
      "institution": "School",
      "major": "Major",
      "degree": "Degree",
      "years": "YYYY - YYYY",
      "description": "Optional details"
    }
  ],
  "personalProjects": [
    {
      "name": "Project Name",
      "role": "Your Role",
      "years": "YYYY",
      "description": ["Point 1", "Point 2"]
    }
  ],
  "additional": {
    "skillOverview": "该段落中的散文/描述性文字原文（如无则留空字符串）",
    "technicalSkills": ["Skill 1", "Skill 2"],
    "languages": [],
    "certificationsTraining": []
  },
  "customModules": {
    "awards": [
      {
        "title": "",
        "company": "",
        "years": "",
        "description": ["原文行1（逐字保留）", "原文行2（逐字保留）"]
      }
    ]
  }
}

CRITICAL: Do NOT output `...` anywhere in the JSON. If a list is empty or a string is missing, output an empty array `[]` or an empty string `""`. Do not use placeholders.

### CONTENT PRESERVATION RULES (CRITICAL - 内容丢失不可接受) ###
1. additional（专业技能）模块：原文可能同时包含「散文描述」和「bullet point 技能条目」。所有非 bullet 的描述性句子必须【逐字】放进 `additional.skillOverview`（保持原语言原文，禁止概括改写）；只有具体的技能名词/短语才进 `additional.technicalSkills`。两者都要，缺一不可。
   特别地，「大模型与 AI 工程：技能A、技能B、技能C」这类【分类名：技能清单】格式的整行内容（无论是否有 bullet 标记）必须【整行逐字】放进 `additional.skillOverview`（每行一条，用换行符分隔），严禁只保留技能名词或拆散分类结构；`technicalSkills` 仅作辅助索引同步收集具体技能名词。
2. workExperience / personalProjects 的 description 数组：原文里的每一个 bullet point 都必须成为数组中独立的一个元素，并且【逐字保留原文措辞】（如原文有 **加粗** 标记也要保留）。禁止把多条 bullet 合并成一条，禁止丢弃任何一条，禁止改写、翻译或删减。
3. 任何段落下的独立描述段落（非 bullet 的普通文字）也不允许丢弃：workExperience/personalProjects 里作为 description 数组的第一个元素保留；additional 里放进 `skillOverview`。
4. customModules（自定义模块）条目：所有内容必须逐行逐字放进 description（保持原文行序），title/company/years 输出空字符串。禁止把条目的标题行拆进 title/company——字段错位会让内容在编辑器里不可见。

### RESUME TEXT ###
{resume_text}
"""

def _extract_json_block(text: str) -> dict:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())


# 自定义模块条目的标准字段：语义不通用（论文/获奖/开源各不同），出口统一折叠进 description
_CUSTOM_ITEM_STD_KEYS = ("company", "title", "years")


def _normalize_custom_modules(data: dict) -> dict:
    """自定义模块条目出口归一化：非空 company/title/years 折叠进 description 头部后清空。

    自定义模块字段语义不通用，LLM 填充位置随机且编辑器对自定义条目默认不渲染这三个
    字段行——在结构化唯一出口统一折叠，保证「编辑器可见 ≡ 打印可见」，内容绝不因
    字段错位而对用户隐藏（2026-10-28）。已存飞书的老数据不经过这里，由前端对非空
    字段照常显示兜底。
    """
    custom = data.get("customModules")
    if not isinstance(custom, dict):
        return data
    for items in custom.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            folded = [str(item[k]).strip() for k in _CUSTOM_ITEM_STD_KEYS
                      if str(item.get(k) or "").strip()]
            # 纯空白的标准字段即便无可折叠内容也清成 ""：前端按真值决定是否画字段行，" " 会被当成有内容
            for k in _CUSTOM_ITEM_STD_KEYS:
                if k in item and not str(item[k] or "").strip():
                    item[k] = ""
            if not folded:
                continue
            desc = item.get("description")
            if isinstance(desc, list):
                desc_lines = [str(d) for d in desc if str(d or "").strip()]
            elif str(desc or "").strip():
                desc_lines = [str(desc)]
            else:
                desc_lines = []
            item["description"] = folded + desc_lines
            for k in _CUSTOM_ITEM_STD_KEYS:
                item[k] = ""
    return data

async def parse_resume_to_json(
    markdown_text: str,
    progress_cb: Any = None,
    strict: bool = False,
) -> dict:
    """Parses raw Markdown resume into a structured ResumeData dictionary.

    progress_cb: 可选回调 cb(chars_so_far)。提供时走流式调用，按已生成字符数回报进度，
    供上传链路透出实时进度；注意回退覆盖流式全程——任何阶段（含中途断连）失败都会
    整单重发一次非流式请求，保证出结果，代价是该情形下的一次重复计费。
    strict: True 时 JSON 解析/校验失败直接抛 ValueError（上传链路用于诚实报错+可重试）；
            默认 False 保持旧行为（返回空结构兜底，ATS 诊断等既有调用方不受影响）。
    """
    client = get_openai_client()
    if not client:
        raise ValueError("OpenAI client not configured.")

    prompt = PARSE_RESUME_PROMPT.replace("{resume_text}", markdown_text)
    model = settings.OPENAI_MODEL if settings.OPENAI_MODEL else "gpt-4o"
    messages = [
        {"role": "system", "content": "You are a JSON extraction engine. Output ONLY valid JSON, no explanations or markdown blocks if possible."},
        {"role": "user", "content": prompt}
    ]

    def call_llm_stream() -> str:
        parts: list[str] = []
        last_reported = 0
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
            stream=True,
        )
        for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content if chunk.choices else None
            except Exception:
                delta = None
            if delta:
                parts.append(delta)
                total = sum(len(p) for p in parts)
                if progress_cb is not None and total - last_reported >= 150:
                    last_reported = total
                    try:
                        progress_cb(total)
                    except Exception:
                        pass
        return "".join(parts)

    def call_llm():
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content or "{}"

    logger.info("🚀 Parsing resume to JSON AST...")
    if progress_cb is not None:
        try:
            llm_reply = await asyncio.to_thread(call_llm_stream)
        except Exception:
            logger.warning("流式结构化失败，回退非流式调用一次", exc_info=True)
            llm_reply = await asyncio.to_thread(call_llm)
    else:
        llm_reply = await asyncio.to_thread(call_llm)

    try:
        parsed_json = _extract_json_block(llm_reply)
        validated = ResumeData.model_validate(parsed_json)
        return _normalize_custom_modules(validated.model_dump())
    except Exception as e:
        logger.error(f"Failed to parse resume JSON: {e}\nReply was: {llm_reply[:500]}")
        if strict:
            raise ValueError(
                "AI 返回的内容无法解析为结构化简历（可能是模型输出被截断或格式异常），请重试。"
                f"模型返回片段：{llm_reply[:200]}"
            ) from e
        # Fallback to empty structure
        return ResumeData().model_dump()


def _render_desc_line(desc: str) -> str:
    """bullet 保真渲染：LLM 返回的条目若已带 bullet/加粗前缀则保持，• 与 * 规范化为 '- '，纯文本补 '- '。"""
    if not desc:
        return ""
    if desc.startswith("**"):
        return desc
    if desc.startswith("- ") or desc.startswith("-\t"):
        return desc
    if desc.startswith("•") or desc.startswith("*"):
        return "- " + desc[1:].lstrip()
    return f"- {desc}"


def _render_unconsumed_modules(data: dict, module_order: list, lines: list) -> None:
    """兜底渲染：extra="allow" 保留的 schema 外顶层模块若未被 module_order 消费，
    以 `# 字段名 + 原文` 附加到输出末尾，保证 LLM 多识别的内容对用户可见而非烂在 JSON 里。"""
    known = set(module_order) | {
        "personalInfo", "summary", "workExperience", "education",
        "personalProjects", "additional", "moduleOrder", "moduleTitles", "customModules",
    }
    module_titles = data.get("moduleTitles", {}) or {}
    for key, value in data.items():
        if key in known or not value:
            continue
        lines.append(f"# {module_titles.get(key, key)}")
        if isinstance(value, str):
            lines.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    parts = [str(v) if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False) for v in item.values() if v]
                    lines.append("- " + " · ".join(parts))
                else:
                    lines.append(f"- {item}")
        elif isinstance(value, dict):
            for k, v in value.items():
                if v:
                    lines.append(f"- {k}：{v}")
        lines.append("")


def json_to_markdown(data: dict) -> str:
    """
    Deterministic renderer to convert JSON ATS data into strict Markdown format expected by the frontend.
    This eliminates the need for a second LLM pass to format Markdown.
    """
    lines = []

    # 获取模块顺序和标题
    module_order = data.get("moduleOrder", ["summary", "additional", "workExperience", "personalProjects", "education"])
    module_titles = data.get("moduleTitles", {})

    # 默认标题映射
    default_titles = {
        "summary": "个人总结",
        "additional": "专业技能",
        "workExperience": "工作经历",
        "personalProjects": "项目经历",
        "education": "教育背景"
    }

    for mod in module_order:
        title = module_titles.get(mod, default_titles.get(mod, ""))

        if mod == "summary" and data.get("summary"):
            lines.append(f"# {title}")
            lines.append(data["summary"])
            lines.append("")

        elif mod == "additional" and data.get("additional"):
            additional = data["additional"]
            overview = (additional.get("skillOverview") or "").strip()
            skills = additional.get("technicalSkills", []) or []
            if overview or skills:
                lines.append(f"# {title}")
                if overview:
                    lines.append(overview)
                if overview and skills:
                    lines.append("")
                if skills:
                    lines.append(" / ".join(skills))
                lines.append("")

        elif mod == "workExperience" and data.get("workExperience"):
            lines.append(f"# {title}")
            for exp in data["workExperience"]:
                title_parts = [exp.get("company", ""), exp.get("title", ""), exp.get("years", "")]
                title_parts = [p for p in title_parts if p]
                lines.append(f"## {' · '.join(title_parts)}")
                for desc in exp.get("description", []):
                    rendered = _render_desc_line(desc)
                    if rendered:
                        lines.append(rendered)
                lines.append("")

        elif mod == "personalProjects" and data.get("personalProjects"):
            lines.append(f"# {title}")
            for proj in data["personalProjects"]:
                title_parts = [proj.get("name", ""), proj.get("role", ""), proj.get("years", "")]
                title_parts = [p for p in title_parts if p]
                lines.append(f"## {' · '.join(title_parts)}")
                for desc in proj.get("description", []):
                    rendered = _render_desc_line(desc)
                    if rendered:
                        lines.append(rendered)
                lines.append("")

        elif mod == "education" and data.get("education"):
            lines.append(f"# {title}")
            for edu in data["education"]:
                # 学校、专业、学历、时间
                title_parts = [edu.get("institution", ""), edu.get("major", ""), edu.get("degree", ""), edu.get("years", "")]
                title_parts = [p for p in title_parts if p]
                lines.append(f"## {' · '.join(title_parts)}")
                if edu.get("description"):
                    lines.append(edu["description"])
                lines.append("")

        elif data.get("customModules") and mod in data["customModules"]:
            custom_list = data["customModules"][mod]
            if custom_list:
                lines.append(f"# {title}")
                for item in custom_list:
                    title_parts = [item.get("company", ""), item.get("title", ""), item.get("years", "")]
                    title_parts = [p for p in title_parts if p]
                    if title_parts:
                        lines.append(f"## {' · '.join(title_parts)}")
                    for desc in item.get("description", []):
                        rendered = _render_desc_line(desc)
                        if rendered:
                            lines.append(rendered)
                    lines.append("")

    # schema 外的额外模块兜底渲染（extra="allow" 配套，防内容不可见）
    _render_unconsumed_modules(data, module_order, lines)

    return "\n".join(lines).strip()
