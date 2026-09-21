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
class PersonalInfo(BaseModel):
    name: str = ""
    title: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    website: str | None = None

class Experience(BaseModel):
    title: str = ""
    company: str = ""
    location: str | None = None
    years: str = ""
    description: list[str] = Field(default_factory=list)

class Education(BaseModel):
    institution: str = ""
    major: str = ""
    degree: str = ""
    years: str = ""
    description: str | None = None

class Project(BaseModel):
    name: str = ""
    role: str = ""
    years: str = ""
    description: list[str] = Field(default_factory=list)

class AdditionalInfo(BaseModel):
    technicalSkills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    certificationsTraining: list[str] = Field(default_factory=list)

class ResumeData(BaseModel):
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
如果你遇到了无法归类于以下标准模块（summary, workExperience, education, personalProjects, additional）的全新模块（如“获奖经历”、“开源贡献”等），请为你识别到的这个模块自行想一个拼音或英文小写 key（例如 "awards"），将其加入 moduleOrder 和 moduleTitles 中，并将该模块的具体条目解析为类似 Experience 的结构，存入 customModules[key] 中。

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
    "technicalSkills": ["Skill 1", "Skill 2"],
    "languages": [],
    "certificationsTraining": []
  },
  "customModules": {
    "awards": [
      {
        "title": "Award Name",
        "company": "Organization",
        "years": "YYYY",
        "description": ["Detail 1"]
      }
    ]
  }
}

CRITICAL: Do NOT output `...` anywhere in the JSON. If a list is empty or a string is missing, output an empty array `[]` or an empty string `""`. Do not use placeholders.

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
        return validated.model_dump()
    except Exception as e:
        logger.error(f"Failed to parse resume JSON: {e}\nReply was: {llm_reply[:500]}")
        if strict:
            raise ValueError(
                "AI 返回的内容无法解析为结构化简历（可能是模型输出被截断或格式异常），请重试。"
                f"模型返回片段：{llm_reply[:200]}"
            ) from e
        # Fallback to empty structure
        return ResumeData().model_dump()


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
            skills = data["additional"].get("technicalSkills", [])
            if skills:
                lines.append(f"# {title}")
                lines.append(" / ".join(skills))
                lines.append("")

        elif mod == "workExperience" and data.get("workExperience"):
            lines.append(f"# {title}")
            for exp in data["workExperience"]:
                title_parts = [exp.get("company", ""), exp.get("title", ""), exp.get("years", "")]
                title_parts = [p for p in title_parts if p]
                lines.append(f"## {' · '.join(title_parts)}")
                for desc in exp.get("description", []):
                    if desc.startswith("**"):
                        lines.append(desc)
                    else:
                        lines.append(f"- {desc}")
                lines.append("")

        elif mod == "personalProjects" and data.get("personalProjects"):
            lines.append(f"# {title}")
            for proj in data["personalProjects"]:
                title_parts = [proj.get("name", ""), proj.get("role", ""), proj.get("years", "")]
                title_parts = [p for p in title_parts if p]
                lines.append(f"## {' · '.join(title_parts)}")
                for desc in proj.get("description", []):
                    if desc.startswith("**"):
                        lines.append(desc)
                    else:
                        lines.append(f"- {desc}")
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
                        if desc.startswith("**"):
                            lines.append(desc)
                        else:
                            lines.append(f"- {desc}")
                    lines.append("")

    return "\n".join(lines).strip()
