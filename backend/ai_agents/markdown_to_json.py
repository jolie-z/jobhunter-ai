import json
import re
from typing import Dict, Any
from app.core.llm_client import get_openai_client
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

def _post_process_array(arr: list) -> list:
    if not isinstance(arr, list):
        return arr
    new_arr = []
    for line in arr:
        if not isinstance(line, str):
            new_arr.append(line)
            continue
            
        line = line.strip()
        if not line:
            continue
            
        # Check if line is a bold heading: **Something**
        is_bold_heading = line.startswith("**") and line.endswith("**")
        is_bullet = line.startswith("- ") or line.startswith("* ")
        
        # Insert empty string BEFORE bold heading (if not first item)
        if is_bold_heading and new_arr and new_arr[-1] != "":
            new_arr.append("")
            
        # Add bullet point if it's a normal description line
        if not is_bold_heading and not is_bullet:
            # Exception for technical stack lists which are inline
            if "技术栈" not in line and "核心技术" not in line:
                line = "- " + line
                
        new_arr.append(line)
        
        # Insert empty string AFTER bold heading
        if is_bold_heading:
            new_arr.append("")
            
    # Clean up trailing empty strings
    while new_arr and new_arr[-1] == "":
        new_arr.pop()
        
    return new_arr

def parse_markdown_to_json(markdown_content: str) -> Dict[str, Any]:
    """
    轻量级后置解析器，将 Skill 生成的高质量 Markdown 原封不动地结构化为 ResumeDataV2 JSON。
    """
    client = get_openai_client() 
    
    prompt = """
请将以下 Markdown 格式的简历文本，严格转换为指定的 JSON 结构。
这纯粹是一个结构化提取任务，请保持文本内容一字不差地提取，不要修改任何文案！

输出的 JSON 必须严格遵守以下结构：
{
  "personalInfo": {},
  "summary": "提取出来的个人总结部分文本，保留换行符。如果没有则为空字符串",
  "workExperience": [
    {
      "title": "职位名称，如 '高级后端工程师'",
      "company": "提取出的公司名称，如 '字节跳动'",
      "location": null,
      "years": "起止时间，如 '2021.03-至今'",
      "description": ["提取出来的子弹点或描述，每一行或者每一个点作为数组的一个元素"]
    }
  ],
  "personalProjects": [
    {
      "name": "项目名称",
      "role": "项目角色（如果没有则为空）",
      "years": "起止时间",
      "description": ["整个项目下方的所有内容（包括技术栈、背景、贡献等），拆分为字符串数组"]
    }
  ],
  "education": [
    {
      "institution": "学校名称",
      "major": "专业",
      "degree": "学历",
      "years": "起止时间",
      "description": ""
    }
  ],
  "additional": {
    "technicalSkills": ["核心技能部分的每一项作为数组的一个元素"],
    "languages": [],
    "certificationsTraining": []
  },
  "moduleOrder": [
    "summary",
    "additional",
    "personalProjects",
    "workExperience",
    "education"
  ],
  "moduleTitles": {
    "summary": "个人总结",
    "additional": "专业技能",
    "personalProjects": "项目经历",
    "workExperience": "工作经历",
    "education": "教育背景"
  },
  "customModules": {}
}

说明：
- **【自动排版规则 - 极其重要】**：在提取过程中，请务必应用以下排版规则，将 Markdown 完美镶嵌在 JSON 中！
  1. 对每条亮点/工作经历中的**核心关键词（如具体技能、数据、核心成果等）使用加粗**（`**关键词**`），提高扫描效率。
  2. 所有的子弹点（即数组中的每一项描述）结尾**绝对不要使用句号（。）**，请直接去掉结尾句号，保持干净利落。
  3. 当识别到描述“技术栈”等包含众多并列短语或名词的内容时，请将其处理为同一行内的普通文本，各项之间使用中文顿号（、）分隔，不要对每个短语单独加粗，也不要使用换行。
  4. 如果遇到包含网址链接的内容，请保持纯文本形式，**绝对不要对其加粗，不要变成超链接**。
- **【极度重要：保留Markdown结构】**：在提取 `description`、`technicalSkills` 等数组时，**必须原封不动地保留原文的 Markdown 符号**！如果原文是用 `- ` 开头的子弹点，提取到数组中时必须依然是 `- ` 开头，**绝对不能吃掉减号**！
- 如果原文包含大分类小标题，请将大分类小标题**加粗并独占一项**（如 `["**项目背景**", "- 内容1", "", "**核心贡献**", "- 内容2"]`）。
- **【极度重要：强制分类间距】**：在 `description` 和 `technicalSkills` 数组中，在每一个**加粗的大分类小标题**（例如 `**项目背景**`、`**核心贡献**`、`**前端开发**`）**前面，必须插入一个空字符串 `""` 作为数组的一项**（如果是数组的第一项则不需要）。这能确保前端渲染时不同分类之间有空行！
- 对于 `summary` 字符串，请直接在段落之间保留 `\n\n` 换行符。**极度注意：只提取总结正文内容，绝对不能把模块的大标题（如 `## 💡 个人总结`）给提取进去！**
- `personalInfo` 直接返回空对象 `{}` 即可，后续代码会自动合并。

以下是需要解析的 Markdown 内容：
"""
    prompt += f"\n{markdown_content}\n"
    
    try:
        # 使用 gpt-4o-mini 或 glm-4-flash，这里因为环境配置通常会有 gpt-4o 或者 glm
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL, # 遵循全局模型配置
            messages=[
                {"role": "system", "content": "你是一个严格的 JSON 解析器。必须按照用户要求的字段返回合法的 JSON 对象。"},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        json_str = response.choices[0].message.content or "{}"
        
        # 清理可能带有的 ```json 标签
        if json_str.startswith("```json"):
            json_str = json_str[7:]
        if json_str.endswith("```"):
            json_str = json_str[:-3]
            
        parsed_json = json.loads(json_str.strip())
        
        # 统一进行后置格式约束清洗，确保格式100%符合前端排版预期
        if "summary" in parsed_json and isinstance(parsed_json["summary"], str):
            # 强制剔除大模型自作主张提取出来的 ## 标题
            parsed_json["summary"] = re.sub(r'^##\s*[^\n]+\n*', '', parsed_json["summary"]).strip()

        if "additional" in parsed_json and "technicalSkills" in parsed_json["additional"]:
            parsed_json["additional"]["technicalSkills"] = _post_process_array(parsed_json["additional"]["technicalSkills"])
            
        for key in ["workExperience", "personalProjects", "education"]:
            if key in parsed_json and isinstance(parsed_json[key], list):
                for item in parsed_json[key]:
                    if "description" in item and isinstance(item["description"], list):
                        item["description"] = _post_process_array(item["description"])

        # 模型兼容：个别模型会返回 JSON 数组，归一为 dict，避免下游缝合崩溃
        if isinstance(parsed_json, list):
            parsed_json = next((x for x in parsed_json if isinstance(x, dict)), {})

        return parsed_json
    except Exception as e:
        logger.exception(f"解析 Markdown 为 JSON 失败: {e}")
        return {"error": str(e), "original_markdown": markdown_content}

def convert_and_stitch_resume(md_resume: str) -> str:
    """
    将 process_resume_rewrite 吐出的纯 Markdown 转换成完整的 JSON 结构，
    并自动从飞书中拉取原版简历的 personalInfo 和 education 拼接进去。
    """
    parsed_json = parse_markdown_to_json(md_resume)
    
    # 尝试从飞书提取个人信息和教育背景
    original_personal_info = {}
    original_education = []
    
    try:
        import requests
        from app.services.feishu_service import get_tenant_access_token, feishu_field_to_plain_str
        from app.core.config import settings
        
        token = get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "filter": {
                "conjunction": "and",
                "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}]
            }
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=10, proxies={"http": None, "https": None})
        if resp.status_code == 200:
            items = resp.json().get("data", {}).get("items", [])
            if items:
                raw_text = feishu_field_to_plain_str(items[0].get("fields", {}).get("结构化数据", ""))
                if raw_text:
                    import json
                    data_dict = json.loads(raw_text)
                    original_personal_info = data_dict.get("personalInfo", {})
                    original_education = data_dict.get("education", [])
    except Exception as e:
        logger.error(f"缝合个人信息失败: {e}")
        
    if not original_personal_info:
        original_personal_info = {
            "name": "未填写",
            "phone": "未填写",
            "email": "未填写",
            "location": "未填写"
        }
        
    # 缝合 personalInfo
    if "personalInfo" not in parsed_json or not parsed_json["personalInfo"]:
        parsed_json["personalInfo"] = original_personal_info
    else:
        parsed_json["personalInfo"].update(original_personal_info)
        
    # 缝合 education (如果改写后的缺失)
    if "education" not in parsed_json or not parsed_json["education"]:
        parsed_json["education"] = original_education
        
    import json
    return json.dumps(parsed_json, ensure_ascii=False)
