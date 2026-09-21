import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from app.core.config import settings
from app.session.registry import canonicalize_platform_name, detect_platform_by_url
from common.config import get_openai_client

logger = logging.getLogger(__name__)

# LLM 各路 prompt 约定的占位兜底值：出现即视为"该字段没拿到"
_PLACEHOLDER_VALUES = {"", "-", "未知", "无", "未解析出岗位名", "未知猎头/公司"}


class VisionNotConfiguredError(ValueError):
    """带图请求但视觉模型未配置（detail.code=vision_not_configured，前端据此弹配置引导）。"""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"视觉模型未配置：缺少 {'、'.join(missing)}")


def _meaningful(value: Any) -> bool:
    """字段值是否真正拿到了（非空且不是占位兜底值）。"""
    return str(value if value is not None else "").strip() not in _PLACEHOLDER_VALUES


def _detect_platform(url: str) -> str:
    """平台判定收敛到 session/registry 单一事实源（含小红书，输出注册表规范显示名）。"""
    return detect_platform_by_url(url)


_BOSS_MOBILE_JOB_URL = re.compile(
    r'(?:m\.zhipin\.com/(?:mpa/html/weijd(?:/weijd-job)?|job_detail)|www\.zhipin\.com/mpa/html/weijd(?:/weijd-job)?)/([0-9a-zA-Z~_-]+)'
)

_51JOB_MOBILE_JOB_URL = re.compile(
    r'(?:msearch\.51job\.com|m\.51job\.com)/jobs/(?:([a-zA-Z0-9_-]+)/)?(\d+)\.html'
)


def normalize_job_url(url: str) -> str:
    """岗位链接入库前转译：手机端分享链接 → 桌面端规范详情页链接（两端通吃）。

    支持平台：
    1. BOSS 直聘：m.zhipin.com/mpa/html/weijd/... ➔ https://www.zhipin.com/job_detail/{id}.html
    2. 前程无忧 (51job)：msearch.51job.com/jobs/all/{id}.html ➔ https://jobs.51job.com/{city_or_all}/{id}.html
    仅转译匹配到的移动端岗位链接，其余原样返回。
    """
    if not url:
        return url
    # 1. BOSS 直聘转译
    m_boss = _BOSS_MOBILE_JOB_URL.search(url)
    if m_boss:
        return f"https://www.zhipin.com/job_detail/{m_boss.group(1)}.html"
    # 2. 前程无忧 51job 转译
    m_51 = _51JOB_MOBILE_JOB_URL.search(url)
    if m_51:
        city = m_51.group(1) or "all"
        return f"https://jobs.51job.com/{city}/{m_51.group(2)}.html"
    return url


_TEXT_SERVICE_PROMPT = """你是一个极度专业的招聘信息解析引擎。
请从用户提供的文本中，精准抽取出招聘的核心字段，并以严格的 JSON 格式输出。

### 输出字段与提取规则：
1. company_name: 公司名称。必须白纸黑字在文本中出现；若未提及则填 "-"。
2. job_name: 岗位名称/职位名称。必须在文本中明确提及；若未提及则填 "-"。
3. salary: 薪资待遇。保留原格式，如 "15-25K"、"20-35K·14薪"；未提及填 "-"。
4. city: 工作城市。从地址或正文中提取城市级别（如 "北京"、"上海"、"广州"、"深圳"、"杭州" 等）；未提及填 "-"。
5. work_address: 具体工作地点/地址。若包含写字楼、园区、门牌号等详细地址一并提取；未提及填 "-"。
6. company_size: 公司规模。如 "100-499人"、"10000人以上"；未提及填 "-"。
7. industry: 所属行业。如 "互联网"、"智能硬件"、"企业服务"；未提及填 "-"。
8. experience: 经验要求。如 "3-5年"、"5-10年"、"经验不限"；未提及填 "-"。
9. education: 学历要求。如 "本科"、"硕士"、"大专"、"学历不限"；未提及填 "-"。
10. job_detail: 岗位详情（包含岗位职责、工作内容、任职资格、技能要求等）。
- 【重要铁律】必须一字不漏地原汁原味保留输入文本中所有职责与要求！
- 【严禁总结/精简/篡改/润色】绝不允许提炼要点、缩写、删除任何条款！
- 若文本没有任何职责描述，填 "-"。
11. job_link: 岗位链接。从文本中提取完整的 URL；未提及填 "-"。
12. publish_date: 岗位发布或更新时间。如 "2026-08-17"、"8月17日更新"、"今日"；未提及填 "-"。

### 最高铁律：
- 严格基于输入文本中明确写明的内容提取，绝不凭空捏造公司名、岗位名或编造任职要求；
- 如果文本仅仅是补充薪资或缺少某些字段，未提及的字段一律填 "-"，严禁自行编造类似"产品经理"、"字节跳动"等任何虚假信息！
- 输出必须且仅能是一个合法的 JSON 对象，不要包裹任何 markdown 代码块标记，不要包含多余文字。
"""


def _call_llm_for_job_parsing(text: str) -> str:
    """调用大模型抽取文本中的招聘字段。优先从环境变量中读取配置。"""
    client = get_openai_client()
    if client is None:
        raise ValueError("AI 服务未配置（缺少 OPENAI_API_KEY），无法解析文本")
    model_name = settings.OPENAI_MODEL or "gpt-4o"
    logger.info(f"--> 正在调用 LLM 进行文本解析 (Model: {model_name})...")

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": _TEXT_SERVICE_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.1,
    )
    res = response.choices[0].message.content or ""
    logger.info("--> LLM 原始返回文本片段:\n", res[:200], "...\n" if len(res) > 200 else "")
    return res


def _clean_and_parse_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception as e:
        logger.error(f"大模型返回非有效 JSON: {raw[:300]}")
        raise ValueError(f"大模型返回的内容无法解析为 JSON: {e}")


def _get_parsed_str(parsed: dict[str, Any], key: str, default: str = "-") -> str:
    val = parsed.get(key)
    return str(val) if val else default


def _resolve_job_link(parsed_link: Any, detected_url: str) -> str | None:
    link = str(parsed_link) if parsed_link else ""
    final_link = link if (link and link != "-") else detected_url
    return final_link if (final_link and final_link.startswith("http")) else None


def _resolve_publish_date(parsed_date: Any) -> str:
    """标准化招聘发布/更新日期为 YYYY-MM-DD 格式。

    支持格式：
    - 猎聘/BOSS 常见月日更新标签：'8月17日更新'、'8月17日'、'08-17' ➔ 自动补齐当前年份 'YYYY-08-17'
    - 相对时间：'今日'、'今天'、'刚刚' ➔ 当天；'昨天' ➔ 当天-1天；'前天' ➔ 当天-2天；'N天前' ➔ 当天-N天
    - 完整日期：'2026-08-17'、'2026/08/17'、'2026.08.17'、'2026年8月17日' ➔ 统一归一化为 '2026-08-17'
    - 无法解析或占位符 ➔ 返回 '-'
    """
    if not parsed_date:
        return "-"
    raw = str(parsed_date).strip()
    if raw in ("-", "未知", "无", "null", "None", ""):
        return "-"

    now = datetime.now()
    # 1. 相对时间：今日/今天/刚刚
    if any(kw in raw for kw in ("今日", "今天", "刚刚")):
        return now.strftime("%Y-%m-%d")
    # 2. 昨天
    if "昨天" in raw:
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    # 3. 前天
    if "前天" in raw:
        return (now - timedelta(days=2)).strftime("%Y-%m-%d")
    # 4. N 天前（如 '3天前'、'5天前更新'）
    m_days = re.search(r"(\d+)\s*天前", raw)
    if m_days:
        return (now - timedelta(days=int(m_days.group(1)))).strftime("%Y-%m-%d")

    # 5. 完整年月日：2026-08-17, 2026/08/17, 2026.08.17, 2026年8月17日
    m_full = re.search(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", raw)
    if m_full:
        y, m, d = int(m_full.group(1)), int(m_full.group(2)), int(m_full.group(3))
        return f"{y:04d}-{m:02d}-{d:02d}"

    # 6. 月日：8月17日更新, 8月17日, 08-17, 8.17
    m_md = re.search(r"(\d{1,2})月(\d{1,2})[日号]?", raw)
    if m_md:
        m, d = int(m_md.group(1)), int(m_md.group(2))
        return f"{now.year:04d}-{m:02d}-{d:02d}"

    m_dash = re.search(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})(?!\d)", raw)
    if m_dash:
        m, d = int(m_dash.group(1)), int(m_dash.group(2))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{now.year:04d}-{m:02d}-{d:02d}"

    # 清理掉诸如'更新'、'发布'等多余文字
    cleaned = re.sub(r"(?:更新|发布|上线)", "", raw).strip()
    return cleaned if cleaned else "-"


def _parse_fields_by_text(text: str, detected_url: str, detected_platform: str) -> dict[str, Any]:
    """文本路解析：LLM 提取 → 中文字段 dict（岗位链接保留裸 URL 字符串，落库时才包 link 对象）。"""
    raw = _call_llm_for_job_parsing(text)
    parsed = _clean_and_parse_json(raw)

    valid_url = _resolve_job_link(parsed.get("job_link"), detected_url)
    valid_url = normalize_job_url(valid_url) if valid_url else valid_url
    logger.info(f"--> 最终岗位链接: {valid_url or '(无，确认页可补录)'}")

    job_detail = _get_parsed_str(parsed, "job_detail")
    skill_req = _get_parsed_str(parsed, "skill_req", "")
    if skill_req and skill_req != "-" and skill_req not in job_detail:
        if job_detail and job_detail != "-":
            job_detail = f"{job_detail}\n任职要求/技能：{skill_req}"
        else:
            job_detail = f"任职要求/技能：{skill_req}"

    return {
        "公司名称": _get_parsed_str(parsed, "company_name", "未知猎头/公司"),
        "岗位名称": _get_parsed_str(parsed, "job_name", "未解析出岗位名"),
        "城市": _get_parsed_str(parsed, "city"),
        "工作地址": _get_parsed_str(parsed, "work_address"),
        "公司规模": _get_parsed_str(parsed, "company_size"),
        "所属行业": _get_parsed_str(parsed, "industry"),
        "薪资": _get_parsed_str(parsed, "salary"),
        "经验要求": _get_parsed_str(parsed, "experience"),
        "学历要求": _get_parsed_str(parsed, "education"),
        "岗位详情": job_detail,
        "招聘平台": str(detected_platform),
        "发布日期": _resolve_publish_date(parsed.get("publish_date")),
        "岗位链接": valid_url or "",
    }


_VISION_SERVICE_PROMPT = """你是一个极度精准的招聘信息文本提取引擎。
用户会提供 1 张或多张包含招聘信息的截图。请仔细阅读这些截图中的文字，提取出核心字段，并严格按照以下 JSON 格式输出。

### 输出格式（必须输出纯 JSON，不要带 markdown 代码块标记，不要包含多余文字）：
{
  "公司名称": "公司名，若图片中未出现填 -",
  "岗位名称": "职位名，若图片中未出现填 -",
  "城市": "工作城市，若图片中未出现填 -",
  "工作地址": "具体工作地址或商圈，若图片中未出现填 -",
  "公司规模": "如 100-499人，若未出现填 -",
  "所属行业": "如 互联网/电子商务，若未出现填 -",
  "薪资": "如 15-25K 或 20-30K·14薪，若未出现填 -",
  "经验要求": "如 3-5年，若未出现填 -",
  "学历要求": "如 本科，若未出现填 -",
  "岗位详情": "完整保留图片中的岗位职责与任职要求全文，若未出现填 -",
  "招聘平台": "BOSS直聘/猎聘/智联招聘/前程无忧/小红书/拉勾 等，根据界面风格识别，无法确定填 未知",
  "发布日期": "提取招聘发布或最后更新时间，如 '8月17日更新'、'2026-08-17'、'3天前'。注意：仅提取岗位更新/发布时间标签，不要提取HR最后在线时间！若未出现填 -"
}

### 极重要提取铁律：
1. 岗位详情（JD）：必须 100% 完整原样提取图片中出现的「岗位职责」与「任职要求/岗位要求」全部文字！
   - 【严禁总结、概括、提炼或润色】输入是什么文字就逐字输出什么文字；
   - 绝不允许擅自将多条要求浓缩为一两句概括性语言！
2. 招聘平台：请根据界面 UI 规范为规范名（如 BOSS直聘、猎聘、智联招聘、前程无忧 等）。
3. 信息忠实度：图片中没有出现的字段一律填 "-"，严禁无中生有！
"""

_KEY_ALIASES = {
    "company_name": "公司名称",
    "company": "公司名称",
    "job_name": "岗位名称",
    "job_title": "岗位名称",
    "title": "岗位名称",
    "city": "城市",
    "location": "城市",
    "work_address": "工作地址",
    "address": "工作地址",
    "company_size": "公司规模",
    "scale": "公司规模",
    "industry": "所属行业",
    "salary": "薪资",
    "experience": "经验要求",
    "education": "学历要求",
    "job_detail": "岗位详情",
    "detail": "岗位详情",
    "description": "岗位详情",
    "platform": "招聘平台",
    "publish_date": "发布日期",
    "date": "发布日期",
}


def _parse_fields_by_vision(base64_list: list[str]) -> dict[str, Any]:
    """视觉路解析：Vision 模型读截图 → 中文字段 dict（不走通用 OCR，不写跟进状态/抓取时间，落库时统一补）。"""
    from common.config import get_vision_llm_client
    logger.info(">>> [1/3] 正在建立与视觉大模型 (Vision Model) 的专属连接...")
    # 视觉通道：优先 VISION_* 独立配置，未配置回落主通道（get_vision_llm_client 内部处理）
    temp_client = get_vision_llm_client(caller="job_import_vision")

    # ⚠️ MiMo 官方格式要求图片部分在前、文字部分在后（文字在前时模型不走多模态路由，会自称看不了图）
    image_parts = []
    for b64 in base64_list:
        img_url = b64 if b64.startswith("data:image") else f"data:image/jpeg;base64,{b64}"
        image_parts.append({
            "type": "image_url",
            "image_url": {"url": img_url}
        })
    user_content = image_parts + [{"type": "text", "text": "请解析以上截图中的招聘信息："}]

    logger.info(f">>> [2/3] 正在让大模型同时阅读 {len(base64_list)} 张图片... (Vision 模型耗时较长)")
    vision_model = settings.VISION_MODEL or "gpt-4o"
    response = temp_client.chat.completions.create(
        model=vision_model,
        messages=[
            {"role": "system", "content": _VISION_SERVICE_PROMPT},
            {"role": "user", "content": user_content}
        ],
        temperature=0.1,
    )
    content = (response.choices[0].message.content or "").strip()
    logger.info(">>> ✅ 视觉大模型成功返回数据！开始解析 JSON...")

    extracted_data = _clean_and_parse_json(content)
    if not isinstance(extracted_data, dict):
        raise ValueError(f"视觉大模型返回非有效 JSON 对象: {content[:200]}")

    if "招聘平台" in extracted_data and extracted_data["招聘平台"]:
        extracted_data["招聘平台"] = canonicalize_platform_name(str(extracted_data["招聘平台"]))

    for eng_k, chn_k in _KEY_ALIASES.items():
        if eng_k in extracted_data and chn_k not in extracted_data:
            extracted_data[chn_k] = extracted_data.pop(eng_k)

    raw_pub = extracted_data.get("发布日期")
    extracted_data["发布日期"] = _resolve_publish_date(raw_pub)
    logger.info(f">>> [3/3] 视觉解析完毕，提取到发布日期: {extracted_data['发布日期']} (原始: {raw_pub})")
    return extracted_data


_SHARE_BOILERPLATE = re.compile(
    r'(?:https?://[^\s\u4e00-\u9fff，。！？\)\]]+|#小程序://[^\s]+|'
    r'【?[a-zA-Z0-9_\u4e00-\u9fff]{0,10}(?:招聘|直聘|无忧|脉脉|拉勾|51job|boss|zhipin)[a-zA-Z0-9_\u4e00-\u9fff]{0,10}】?|'
    r'(?:帮我|请帮我|麻烦)?(?:录入|解析|添加|提取)?(?:岗位|职位)?(?:链接|网址|地址)?|'
    r'(?:复制|打开|查看|进入|点击|分享|前往)?(?:此|该|这段|整段)?(?:链接|口令|[a-zA-Z]*[aA][pP]{2}|小程序|客户端)?(?:查看|了解)?(?:岗位|职位)?(?:详情)?|'
    r'(?:岗位|职位|分享|网页|移动端|电脑端|原生)?(?:链接|网址|地址|详情|来源|直达)|'
    r'[:：\s,，。!！\(\)\[\]\-\?&=#]+)',
    re.IGNORECASE
)


def _has_substantial_job_text(text: str) -> bool:
    """判断文本中是否包含实质性的招聘正文或用户手写补充信息。

    过滤机制：
    1. 剥除所有 URL 链接与小程序短链口令；
    2. 剥除主流平台复制分享常见套话（如'【BOSS直聘】复制整段，打开App查看详情'、'链接：'、'岗位链接：'等）；
    3. 只要剩余有效信息字符 >= 4（如'薪资20k'、'补充薪资：50-70K'），即认定包含有效补充内容，启动文本解析；
    4. 若仅为纯链接或套话，坚决短路避免纯文本大模型产生幻觉编造假岗位。
    """
    if not text:
        return False
    cleaned = _SHARE_BOILERPLATE.sub('', text)
    real_chars = re.findall(r'[\u4e00-\u9fffA-Za-z0-9]', cleaned)
    return len(real_chars) >= 4


def _merge_parsed_fields(base: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    """图文同传精细合并：
    base 为视觉解析（眼见为实的截图原图），overlay 为文本解析。
    原则：
    1. 视觉路已有效提取的核心事实（公司、岗位、城市、地址、经验、学历、平台）坚决优先保留，严禁被文本路冲掉；
    2. 视觉路为占位符（'-'、'未知'）的字段，若文本路有值，则用文本路补全；
    3. 薪资字段：若文本路明确提取到了有效薪资（如用户文字补充'补充薪资：50-70K'），优先采纳文本补充值；
    4. 岗位详情（JD）：若视觉路已提取了充实正文(>=50字)，坚决保留视觉路原样文本，杜绝大模型精简/总结覆盖；若视觉路缺失或过短，才由文本路补充；
    5. 岗位链接与发布日期：若视觉路没有，采用文本路。
    """
    merged = dict(base)
    overlay = overlay or {}
    for key, val in overlay.items():
        if key in ("跟进状态", "抓取时间"):
            continue
        base_val = merged.get(key)
        if not _meaningful(base_val) and _meaningful(val):
            merged[key] = val
        elif key == "薪资" and _meaningful(val):
            merged[key] = val
        elif key == "岗位详情" and _meaningful(val):
            if not _meaningful(base_val) or len(str(base_val).strip()) < 50:
                merged[key] = val
    return merged


async def parse_job_from_sources(raw_text: str = "", images_base64: list[str] | None = None) -> dict[str, Any]:
    """极速录入解析（不落库）：有图走视觉、有文走文本；图文同传时智能防幻觉解析与精细合并。

    返回统一的中文字段 dict（招聘平台已归一为注册表规范名，岗位链接为规范 URL 字符串）。
    """
    raw_text = (raw_text or "").strip()
    images = [img for img in (images_base64 or []) if img]
    if not raw_text and not images:
        raise ValueError("请提供招聘文本或至少一张截图")

    # 视觉前置闸门：带图请求必须有可用视觉模型，否则后续只会拿着硬编码兜底模型名盲跑报错
    if images:
        from common.config import get_missing_vision_keys
        missing_vision = get_missing_vision_keys()
        if missing_vision:
            raise VisionNotConfiguredError(missing_vision)

    detected_url, detected_platform = "", "未知"
    if raw_text:
        _url_match = re.search(r'https?://[^\s\u4e00-\u9fff，。！？\)\]]+', raw_text)
        detected_url = _url_match.group(0).rstrip('.,;') if _url_match else ""
        if not detected_url:
            _wx_match = re.search(r'#小程序://([^\s/]+)', raw_text)
            if _wx_match:
                detected_url = raw_text.strip()
                detected_platform = canonicalize_platform_name(_wx_match.group(1))
        if detected_url and detected_platform == "未知":
            detected_platform = _detect_platform(detected_url)
        logger.info(f"--> 预检测 URL/口令: {detected_url or '(无)'} | 平台: {detected_platform}")

    has_text = _has_substantial_job_text(raw_text)

    if images and has_text:
        logger.info("--> [图文同传] 检测到同时存在截图与实质性招聘正文，启动并行解析与精细合并...")
        vision_fields, text_fields = await asyncio.gather(
            asyncio.to_thread(_parse_fields_by_vision, images),
            asyncio.to_thread(_parse_fields_by_text, raw_text, detected_url, detected_platform),
        )
        fields = _merge_parsed_fields(vision_fields, text_fields)
    elif images:
        logger.info("--> [纯截图/截图+短链] 仅提供截图或简短链接，为防大模型幻觉，全量使用视觉解析结果...")
        vision_fields = await asyncio.to_thread(_parse_fields_by_vision, images)
        if detected_url:
            norm_url = normalize_job_url(detected_url)
            vision_fields["岗位链接"] = norm_url
            if detected_platform != "未知" and (not _meaningful(vision_fields.get("招聘平台")) or vision_fields.get("招聘平台") == "未知"):
                vision_fields["招聘平台"] = detected_platform
        fields = vision_fields
    else:
        if not has_text and detected_url:
            logger.info(f"--> [纯链接短路] 文本仅包含 URL 链接 ({detected_url})，直接提取平台与链接，防大模型幻觉...")
            norm_url = normalize_job_url(detected_url)
            fields = {
                "公司名称": "-",
                "岗位名称": "-",
                "城市": "-",
                "工作地址": "-",
                "公司规模": "-",
                "所属行业": "-",
                "薪资": "-",
                "经验要求": "-",
                "学历要求": "-",
                "岗位详情": "-",
                "招聘平台": detected_platform if detected_platform != "未知" else "未知",
                "发布日期": "-",
                "岗位链接": norm_url,
            }
        else:
            fields = await asyncio.to_thread(_parse_fields_by_text, raw_text, detected_url, detected_platform)

    return fields
