import logging
import re

logger = logging.getLogger("resume_parser")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(ch)

def extract_and_truncate_personal_info(raw_text: str) -> tuple[dict[str, str], str]:
    """
    基于高价值特征锚点的区域斩击法，提取并脱敏个人信息。

    Args:
        raw_text: 原始解析出的简历文本（如 PDF 或 Word 提取出的文本）

    Returns:
        (extracted_info字典, safe_text_for_llm准备喂给大模型的安全文本)
    """
    info = {
        "name": "未识别",
        "phone": "未填写",
        "email": "未填写",
        "wechat": "未填写",
        "urls": "未填写"
    }

    if not raw_text:
        return info, ""

    # 0. 预处理：剔除所有巨大的 base64 图片数据，防止占满头部扫描区且浪费 LLM Token
    raw_text = re.sub(r'data:image/[a-zA-Z0-9]+;base64,[a-zA-Z0-9+/=]+', '', raw_text)

    # 1. 严格限制扫描深度：前 1000 个字符
    scan_limit = 1000
    header_text = raw_text[:scan_limit]
    body_text = raw_text[scan_limit:]

    logger.info("[File: resume_parser.py -> Func: extract_and_truncate_personal_info] 开始执行正则匹配...")
    # 2. 核心特征锚点正则
    phone_pattern = re.compile(r'(?:\+86)?\s*1[3-9]\d[\s\-]?\d{4}[\s\-]?\d{4}')
    # 兼容 Markdown 可能转义下划线的情况 (如 fei\_wang@)
    email_pattern = re.compile(r'[a-zA-Z0-9._%+-\\]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    url_pattern = re.compile(r'(https?://[^\s]+|(?:www\.)?(?:github\.com|gitee\.com)[^\s]+)')
    wechat_pattern = re.compile(r'(?i)(?:微信|wechat|weixin)[\s:：]*([a-zA-Z][a-zA-Z0-9_-]{5,19})')

    # 提取信息
    phone_match = phone_pattern.search(header_text)
    email_match = email_pattern.search(header_text)
    wechat_match = wechat_pattern.search(header_text)
    url_matches = url_pattern.findall(header_text)

    if phone_match:
        info["phone"] = phone_match.group(0).strip()
    if email_match:
        info["email"] = email_match.group(0).replace("\\", "").strip()
    if wechat_match:
        info["wechat"] = wechat_match.group(1).replace("\\", "").strip()
    elif phone_match:
        info["wechat"] = info["phone"] # 微信号没有则默认取手机号

    if url_matches:
        info["urls"] = " / ".join([u for u in url_matches if u])

    # 3. 智能姓名提取与降级保护
    lines = header_text.split('\n')

    found_contact = False
    for line in lines[:15]:
        # 移除 markdown 表格线、加粗等符号
        clean_line = re.sub(r'[\|\-\*#\>!\[\]\(\)\_]', ' ', line)

        if phone_pattern.search(line) or email_pattern.search(line):
            found_contact = True

        # 寻找 2-4 字中文姓名（允许字之间有空格）
        matches = re.findall(r'[\u4e00-\u9fa5](?:\s*[\u4e00-\u9fa5]){1,3}', clean_line)
        for m in matches:
            nm_clean = m.replace(" ", "")
            if 2 <= len(nm_clean) <= 4:
                # 排除简历中常见的非姓名词汇
                if nm_clean not in {"个人总结", "专业技能", "工作经历", "项目经历", "教育背景", "个人信息", "简历", "求职", "意向", "电话", "邮箱", "手机", "年龄"} \
                   and not any(kw in nm_clean for kw in ["开发", "经理", "工程", "管理", "总监", "意向", "目标", "总结", "经历", "背景", "照片", "联系"]):
                    info["name"] = nm_clean
                    break

        if info["name"] == "未识别":
            # 备选：寻找英文名 (如 Jane Doe)
            eng_match = re.search(r'\b[A-Z][a-z]+\s[A-Z][a-z]+\b', clean_line)
            if eng_match:
                info["name"] = eng_match.group(0)

        if info["name"] != "未识别":
            break

        if found_contact:
            # 如果已经扫到了手机号或邮箱，且还没找到名字，就不再往下找了，名字通常在联系方式之前或同一行
            break

    # 换行降级机制判断：少于 3 个换行符说明可能粘连
    if len(lines) < 3:
        # 按字符索引斩击
        indices = []
        for match in [phone_match, email_match, wechat_match]:
            if match:
                indices.extend([match.start(), match.end()])

        if indices:
            min_idx = min(indices)
            max_idx = max(indices)
            start_cut = max(0, min_idx - 50)
            end_cut = min(len(header_text), max_idx + 100)

            safe_header = header_text[:start_cut] + "\n[个人信息已物理脱敏]\n" + header_text[end_cut:]
        else:
            safe_header = header_text
    else:
        # 按行斩击 (仅在前 15 行内寻找强锚点)
        anchor_line_indices = []
        for i, line in enumerate(lines[:15]):
            if phone_pattern.search(line) or email_pattern.search(line) or wechat_pattern.search(line):
                anchor_line_indices.append(i)

        if anchor_line_indices:
            # 向前扩展 2 行作为危险区
            min_line = max(0, min(anchor_line_indices) - 2)

            # 向后最多扩展 3 行，但如果遇到正文模块的标题，则立即停止扩展（防止误伤个人总结等）
            max_line = max(anchor_line_indices)
            for offset in range(1, 4):
                idx = max(anchor_line_indices) + offset
                if idx < len(lines):
                    # 检查是否遇到常见简历模块标题
                    if any(kw in lines[idx] for kw in ["总结", "技能", "经历", "背景", "评价", "经验"]):
                        break
                    max_line = idx

            # 删除危险区的内容
            safe_lines = lines[:min_line] + ["\n[个人信息已物理脱敏]\n"] + lines[max_line + 1:]
            safe_header = "\n".join(safe_lines)
        else:
            safe_header = header_text

    # 将清洗后的头部与原本的正文拼合
    safe_text_for_llm = safe_header + body_text

    logger.info(f"[File: resume_parser.py -> Func: extract_and_truncate_personal_info] 成功提取原始信息 -> 邮箱: {info.get('email', '未填写')}, 手机: {info.get('phone', '未填写')}, 已暂存本地上下文。")

    return info, safe_text_for_llm


def assemble_final_markdown(extracted_info: dict[str, str], llm_generated_md: str) -> str:
    """
    终极数据驱动缝合（UI 渲染契约）
    将 Python 提取到的个人信息，严格硬编码为前端 PersonalInfo 组件可无缝反序列化的 Markdown 格式。

    Args:
        extracted_info: extract_and_truncate_personal_info 提取出的字典
        llm_generated_md: 大模型生成的其余 Markdown 文本

    Returns:
        最终完整的 Markdown 简历底稿
    """
    # 严格使用全角冒号 `：`
    personal_info_md = f"""# 个人信息
姓名：{extracted_info.get('name', '未识别')}
手机：{extracted_info.get('phone', '未填写')}
邮箱：{extracted_info.get('email', '未填写')}
微信：{extracted_info.get('wechat', '未填写')}
个人主页：{extracted_info.get('urls', '未填写')}
求职意向：待填写
"""

    # 确保不会出现多余的空行或格式混乱
    return personal_info_md.strip() + "\n\n" + llm_generated_md.strip()
