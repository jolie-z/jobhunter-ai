"""
Pure Python standalone HTML renderer for ResumeDataV2.
Generates self-contained, pixel-perfect, clean HTML for PDF and Image rendering
100% aligned with the Frontend Web Preview (ResumeClassic, ResumeColor, ResumeColorV2).
"""
import re
from typing import Any


def _markdown_to_html_snippet(text: Any) -> str:
    if not text:
        return ""
    if isinstance(text, dict):
        if "content" in text:
            text = text["content"]
        else:
            rows = []
            for k, v in text.items():
                if not v:
                    continue
                if isinstance(v, list):
                    for item in v:
                        s_item = str(item).strip()
                        if not s_item or s_item in ("-", "*", "—"):
                            continue
                        rows.append(s_item if s_item.startswith(("-", "*")) else f"- {s_item}")
                else:
                    rows.append(f"- **{k}**: {v}")
            text = "\n".join(rows)
    elif isinstance(text, list):
        rows = []
        for x in text:
            s_x = str(x).strip()
            if not s_x or s_x in ("-", "*", "—"):
                continue
            rows.append(s_x if s_x.startswith(("-", "*")) else f"- {s_x}")
        text = "\n".join(rows)
    else:
        text = str(text)

    # 🌟 彻底清除内部证据强度标签（如 [稳]、[需补证]、[补证后可用]）
    text = re.sub(r'\s*\[(?:稳|需补证|补证后可用)\]', '', text)

    # Convert **bold** to <strong>bold</strong>
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Convert *italic* to <em>italic</em>
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    # Convert [text](url) to <a href="url">text</a>
    html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank">\1</a>', html)

    # Handle newlines
    lines = html.split('\n')
    out_lines = []
    for line in lines:
        line_s = line.strip()
        if not line_s:
            continue
        if line_s.startswith('- ') or line_s.startswith('* '):
            out_lines.append(f'<li>{line_s[2:].strip()}</li>')
        elif re.match(r'^\d+\.\s+', line_s):
            clean = re.sub(r'^\d+\.\s+', '', line_s)
            out_lines.append(f'<li>{clean.strip()}</li>')
        else:
            out_lines.append(f'<p class="resume-p">{line_s}</p>')

    # Wrap lis in ul if needed
    final_html = []
    in_ul = False
    for item in out_lines:
        if item.startswith('<li>'):
            if not in_ul:
                final_html.append('<ul class="resume-ul">')
                in_ul = True
            final_html.append(item)
        else:
            if in_ul:
                final_html.append('</ul>')
                in_ul = False
            final_html.append(item)
    if in_ul:
        final_html.append('</ul>')
    return "".join(final_html)

def _consolidate_technical_skills(skills: list) -> list:
    """清洗与合并可能被大模型切碎的技能列表，输出紧凑工整的 4~5 个子弹点。"""
    if not isinstance(skills, list):
        return skills

    # 1. 过滤空行与纯符号
    cleaned = []
    for s in skills:
        if isinstance(s, str):
            st = s.strip()
            if st and st not in ("-", "*", "—", ""):
                cleaned.append(st)
        elif s:
            cleaned.append(str(s).strip())

    if not cleaned:
        return []

    # 2. 如果已是良好格式（多为长句或带冒号的类别描述），直接返回
    short_items = sum(1 for s in cleaned if len(re.sub(r'[\*\-_]', '', s).strip()) < 14 and '：' not in s and ':' not in s)
    if short_items < 4:
        return cleaned

    # 3. 针对碎片化词汇进行聚合排版
    consolidated = []
    pending_items: list[str] = []

    for s in cleaned:
        if ('：' in s or ':' in s) and len(s) > 15:
            if pending_items:
                for i in range(0, len(pending_items), 6):
                    chunk = pending_items[i:i+6]
                    consolidated.append(f"- {'、'.join(chunk)}")
                pending_items = []
            consolidated.append(s if s.startswith(('- ', '* ')) else f"- {s}")
            continue

        pure = re.sub(r'^[-*]\s+', '', s).strip()
        bold_match = re.match(r'^\*\*(.+?)\*\*$', pure)
        word = f"**{bold_match.group(1).strip()}**" if bold_match else pure
        if word:
            pending_items.append(word)

    if pending_items:
        for i in range(0, len(pending_items), 6):
            chunk = pending_items[i:i+6]
            consolidated.append(f"- {'、'.join(chunk)}")

    return consolidated


def build_resume_html(data: dict[str, Any], skin: str = "classic") -> str:
    """Build a complete, standalone, high-fidelity HTML string from ResumeDataV2 dict.

    Supported skins:
      - 'classic': 经典普通模版（纯黑白极简风，对齐图3）
      - 'color_v1': 商务蓝模版
      - 'color_v2': 大厂风/极客高密版
    """
    personal = data.get("personalInfo", {}) or {}
    raw_name = personal.get("name", "")

    # 🌟 容错自愈：若 personalInfo 缺失或姓名为空，尝试从基准简历补充或安全兜底
    if not raw_name:
        try:
            import json

            import requests

            from app.core.config import settings
            from app.services.feishu_service import (
                feishu_field_to_plain_str,
                get_tenant_access_token,
            )
            token = get_tenant_access_token()
            if token:
                url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.FEISHU_APP_TOKEN}/tables/{settings.FEISHU_TABLE_ID_RESUMES}/records/search"
                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                payload = {
                    "filter": {
                        "conjunction": "and",
                        "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}]
                    }
                }
                no_proxies: dict[str, str | None] = {"http": None, "https": None}
                resp = requests.post(url, headers=headers, json=payload, timeout=5, proxies=no_proxies)
                if resp.status_code == 200:
                    items = resp.json().get("data", {}).get("items", [])
                    if items:
                        raw_struct = feishu_field_to_plain_str(items[0].get("fields", {}).get("结构化数据", ""))
                        if raw_struct:
                            base_data = json.loads(raw_struct)
                            if base_data.get("personalInfo"):
                                personal = {**base_data["personalInfo"], **personal}
                                raw_name = personal.get("name", "")
                                data["personalInfo"] = personal
        except Exception:
            pass

    if not raw_name:
        # 兜底只保证标题不出现空姓名，不注入任何个人联系方式
        personal = {"name": "张三"}
        raw_name = "张三"
        data["personalInfo"] = personal

    # 姓名中文排版：2~4个汉字自动加字距空格 (张三 -> 张 三)
    clean_name = re.sub(r'\s+', '', raw_name)
    if re.match(r'^[\u4e00-\u9fa5]{2,4}$', clean_name):
        display_name = ' '.join(list(clean_name))
    else:
        display_name = raw_name

    title = personal.get("title", "")
    avatar_url = personal.get("avatar_url") or data.get("avatar_url")

    # 构建联系方式（去 Emoji，纯净竖线分隔）
    contact_parts = []
    if personal.get("phone"):
        contact_parts.append(f'<span>{personal["phone"]}</span>')
    if personal.get("email"):
        contact_parts.append(f'<span>{personal["email"]}</span>')

    gh = personal.get("GitHub主页") or personal.get("github")
    if gh:
        clean_gh = re.sub(r'^https?://', '', gh).rstrip('/')
        if not clean_gh.startswith("github.com") and not clean_gh.startswith("GitHub"):
            clean_gh = f"github.com/{clean_gh}"
        contact_parts.append(f'<span>GitHub: <a href="https://{clean_gh}" target="_blank">{clean_gh}</a></span>')

    loc = personal.get("location") or personal.get("city")
    if loc:
        contact_parts.append(f'<span>{loc}</span>')

    summary = data.get("summary", "")
    work_exp = data.get("workExperience", [])
    projects = data.get("personalProjects", [])
    education = data.get("education", [])
    additional = data.get("additional", "")
    custom_modules = data.get("customModules", {})

    module_order = data.get("moduleOrder", ["summary", "workExperience", "personalProjects", "education", "additional"])
    module_titles = data.get("moduleTitles", {
        "summary": "个人总结",
        "workExperience": "工作经历",
        "personalProjects": "项目经历",
        "education": "教育背景",
        "additional": "专业技能"
    })

    sections_html = []

    for mod in module_order:
        if mod == "personalInfo":
            continue
        title_text = module_titles.get(mod, mod)

        if mod == "summary" and summary:
            content_html = _markdown_to_html_snippet(summary)
            sections_html.append(f"""
            <section class="resume-section">
                <h3 class="section-title">{title_text}</h3>
                <div class="section-content text-justify">{content_html}</div>
            </section>
            """)

        elif mod == "workExperience" and work_exp:
            items_html = []
            for item in work_exp:
                c_name = item.get("company", "")
                c_title = item.get("title", "")
                c_years = item.get("years", "")
                c_desc = item.get("description", "")
                desc_html = _markdown_to_html_snippet(c_desc) if isinstance(c_desc, str) else _markdown_to_html_snippet("\n".join(c_desc)) if isinstance(c_desc, list) else ""
                items_html.append(f"""
                <div class="resume-item">
                    <div class="item-grid">
                        <div class="col-left">{c_name}</div>
                        <div class="col-center">{c_title}</div>
                        <div class="col-right">{c_years}</div>
                    </div>
                    {f'<div class="item-desc">{desc_html}</div>' if desc_html else ''}
                </div>
                """)
            sections_html.append(f"""
            <section class="resume-section">
                <h3 class="section-title">{title_text}</h3>
                <div class="resume-items">{"".join(items_html)}</div>
            </section>
            """)

        elif mod == "personalProjects" and projects:
            items_html = []
            for item in projects:
                p_name = item.get("project", "") or item.get("name", "")
                p_role = item.get("role", "")
                p_years = item.get("years", "") or item.get("date", "")
                p_desc = item.get("description", "")
                desc_html = _markdown_to_html_snippet(p_desc) if isinstance(p_desc, str) else _markdown_to_html_snippet("\n".join(p_desc)) if isinstance(p_desc, list) else ""
                items_html.append(f"""
                <div class="resume-item">
                    <div class="item-grid">
                        <div class="col-left">{p_name}</div>
                        <div class="col-center">{p_role}</div>
                        <div class="col-right">{p_years}</div>
                    </div>
                    {f'<div class="item-desc">{desc_html}</div>' if desc_html else ''}
                </div>
                """)
            sections_html.append(f"""
            <section class="resume-section">
                <h3 class="section-title">{title_text}</h3>
                <div class="resume-items">{"".join(items_html)}</div>
            </section>
            """)

        elif mod == "education" and education:
            items_html = []
            for item in education:
                e_school = item.get("school", "") or item.get("institution", "")
                e_major = item.get("major", "")
                e_degree = item.get("degree", "")
                e_sub = f"{e_major} · {e_degree}" if e_major and e_degree else (e_major or e_degree)
                e_years = item.get("years", "")
                e_desc = item.get("description", "")
                desc_html = _markdown_to_html_snippet(e_desc) if e_desc else ""
                items_html.append(f"""
                <div class="resume-item">
                    <div class="item-grid">
                        <div class="col-left">{e_school}</div>
                        <div class="col-center">{e_sub}</div>
                        <div class="col-right">{e_years}</div>
                    </div>
                    {f'<div class="item-desc">{desc_html}</div>' if desc_html else ''}
                </div>
                """)
            sections_html.append(f"""
            <section class="resume-section">
                <h3 class="section-title">{title_text}</h3>
                <div class="resume-items">{"".join(items_html)}</div>
            </section>
            """)

        elif mod == "additional" and additional:
            if isinstance(additional, dict):
                tech_skills = additional.get("technicalSkills", []) or []
                languages = additional.get("languages", []) or []
                certs = additional.get("certificationsTraining", []) or []

                parts = []
                if tech_skills:
                    consolidated_skills = _consolidate_technical_skills(tech_skills)
                    parts.append(_markdown_to_html_snippet(consolidated_skills))
                if languages:
                    parts.append(f'<div class="skill-sub-row"><strong>语言：</strong>{" / ".join(languages)}</div>')
                if certs:
                    parts.append(f'<div class="skill-sub-row"><strong>证书与培训：</strong>{" / ".join(certs)}</div>')

                content_html = "".join(parts) or _markdown_to_html_snippet(str(additional))
            else:
                content_html = _markdown_to_html_snippet(additional)
            sections_html.append(f"""
            <section class="resume-section">
                <h3 class="section-title">{title_text}</h3>
                <div class="section-content text-justify">{content_html}</div>
            </section>
            """)

        elif mod in custom_modules:
            c_val = custom_modules[mod]
            if c_val:
                content_html = _markdown_to_html_snippet(str(c_val))
                sections_html.append(f"""
                <section class="resume-section">
                    <h3 class="section-title">{title_text}</h3>
                    <div class="section-content text-justify">{content_html}</div>
                </section>
                """)

    # 模版色彩与主题定制
    accent_color = "#000000"
    border_color = "#000000"
    if skin == "color_v1":
        accent_color = "#1d4ed8"
        border_color = "#1d4ed8"
    elif skin == "color_v2":
        accent_color = "#1e40af"
        border_color = "#1e40af"

    contacts_rendered = ' <span class="meta-sep">|</span> '.join(contact_parts)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{display_name} - 个人简历</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        :root {{
            --accent: {accent_color};
            --border-accent: {border_color};
            --text-primary: #000000;
            --text-body: #1f2937;
            --text-sub: #111827;
            --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
        }}
        body {{
            background-color: #ffffff;
            font-family: var(--font-family);
            font-size: 11.5px;
            line-height: 1.48;
            color: var(--text-body);
            -webkit-font-smoothing: antialiased;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}
        .resume-container {{
            width: 800px;
            margin: 0 auto;
            padding: 24px 32px 32px 32px;
            background: #ffffff;
            position: relative;
        }}
        .resume-header {{
            position: relative;
            margin-bottom: 10px;
            min-height: 65px;
        }}
        .resume-header-inner {{
            text-align: center;
        }}
        .resume-header-inner.has-avatar {{
            padding: 0 90px;
        }}
        .resume-avatar {{
            position: absolute;
            right: 0;
            top: 0;
            width: 70px;
            height: 94px;
            border-radius: 4px;
            border: 1px solid #e5e7eb;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
            background: #f9fafb;
        }}
        .resume-avatar img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
            display: block;
        }}
        .resume-name {{
            font-size: 24px;
            font-weight: 700;
            color: var(--text-primary);
            letter-spacing: 0.1em;
            text-align: center;
            margin-bottom: 3px;
            line-height: 1.2;
        }}
        .resume-title {{
            font-size: 12.5px;
            font-weight: 500;
            color: var(--text-sub);
            margin-bottom: 3px;
            text-align: center;
        }}
        .resume-meta {{
            display: flex;
            justify-content: center;
            align-items: center;
            flex-wrap: wrap;
            gap: 2px 8px;
            font-size: 11.5px;
            color: var(--text-primary);
        }}
        .meta-sep {{
            color: #9ca3af;
            font-size: 11px;
            user-select: none;
        }}
        .resume-section {{
            margin-bottom: 8px;
        }}
        .resume-section:last-child {{
            margin-bottom: 0;
        }}
        .section-title {{
            font-size: 13.5px;
            font-weight: 700;
            color: var(--accent);
            border-bottom: 1.5px solid var(--border-accent);
            padding-bottom: 2px;
            margin-bottom: 4px;
            letter-spacing: 0.02em;
        }}
        .section-content {{
            font-size: 11.5px;
            line-height: 1.48;
            color: var(--text-body);
        }}
        .text-justify {{
            text-align: justify;
        }}
        .resume-items {{
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .resume-item {{
            margin-bottom: 3px;
        }}
        .resume-item:last-child {{
            margin-bottom: 0;
        }}
        .item-grid {{
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            align-items: baseline;
            margin-bottom: 1px;
        }}
        .col-left {{
            text-align: left;
            font-weight: 700;
            font-size: 12.5px;
            color: var(--text-primary);
        }}
        .col-center {{
            text-align: center;
            font-weight: normal;
            font-size: 12px;
            color: var(--text-sub);
            padding: 0 8px;
        }}
        .col-right {{
            text-align: right;
            font-size: 11.5px;
            color: var(--text-primary);
            white-space: nowrap;
        }}
        .item-desc {{
            margin-top: 2px;
            font-size: 11.5px;
            line-height: 1.48;
        }}
        .resume-ul {{
            margin: 2px 0 4px 18px;
            padding: 0;
        }}
        .resume-ul li {{
            margin-bottom: 2px;
            line-height: 1.55;
        }}
        .resume-p {{
            margin-bottom: 3px;
            line-height: 1.55;
        }}
        .skill-sub-row {{
            margin-top: 3px;
            font-size: 12px;
        }}
        strong, b {{
            font-weight: 700;
            color: #000000;
        }}
        a {{
            color: inherit;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        @media print {{
            body {{
                background: #ffffff;
            }}
            .resume-container {{
                padding: 0;
                width: 100%;
                max-width: 100%;
            }}
            .resume-section {{
                page-break-inside: auto;
            }}
            .resume-item {{
                page-break-inside: avoid;
            }}
            h1, h2, h3, .section-title {{
                page-break-after: avoid;
            }}
        }}
    </style>
</head>
<body>
    <div class="resume-container">
        <header class="resume-header">
            {f'<div class="resume-avatar"><img src="{avatar_url}" alt="证件照" /></div>' if avatar_url else ''}
            <div class="resume-header-inner{' has-avatar' if avatar_url else ''}">
                <h1 class="resume-name">{display_name}</h1>
                {f'<div class="resume-title">{title}</div>' if title else ''}
                <div class="resume-meta">
                    {contacts_rendered}
                </div>
            </div>
        </header>
        {"".join(sections_html)}
    </div>
</body>
</html>
"""
