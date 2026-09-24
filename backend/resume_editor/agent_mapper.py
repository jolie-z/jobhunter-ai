"""
Agent 映射器 —— 飞书主简历 → 4 平台字段映射（Phase 1）

流程：
  飞书主简历(结构化数据+个人信息) ──► LLM(json_object) ──► 执行报告(fields/unfilled/warnings)
  人工审报告确认后，由 apply_mapping 写入 {platform}_fields.json。

设计约束（决定质量的红线）：
  - 下拉/枚举字段只能参考现有 current_value 的格式，找不到参照就放 unfilled，绝不编造 code
  - 不得编造主简历里没有的内容
  - 每个字段带 confidence(high/medium/low) + source + note

纯函数（flatten_schema / get_path / set_path / validate_mapping_result / apply_mapping /
build_mapping_prompt）不依赖网络，可单测。
"""

import json
import logging
import os
import re
from datetime import datetime
from resume_editor.paths import DATA_DIR  # 单一事实源（Q-M5-2 收敛）

logger = logging.getLogger("resume_editor.agent_mapper")


# 映射报告持久化文件（刷新/重启不丢，省 LLM token；剥离静态选项，恢复时重新附加）
REPORT_FILE = os.path.join(DATA_DIR, "agent_map_reports.json")
PLATFORMS = ["boss", "liepin", "51job", "zhilian"]

# 主简历中需要剔除的块（归档内容不参与映射，省 token）
_MASTER_DROP_KEYS = {"archivedProjects", "archivedWorkExperience", "moduleOrder"}


# ============ 平台专属选项表（字段取值约束） ============

# 平台 → 选项组名 → 数据文件列表（多个文件取并集；"a.json#key" 表示取该 JSON 的指定 key；
# "a.json@提取器" 表示用提取器函数从文件生成列表）
_OPTION_FILES = {
    "boss": {
        "industries": ["boss_industry_options.json", "boss_industry_raw.json"],
        "positions": ["boss_job_titles.json", "boss_fulltime_positions.json"],
        "cities": ["boss_city_full.json@cities_flat"],
        "salary_ranges": ["boss_options.json#salary_ranges"],
        "job_statuses": ["boss_options.json#job_statuses"],
        "education_levels": ["boss_options.json#education_levels"],
        # —— 以下与 boss-tab（BOSS直聘 tab）成功实现的列表同源 ——
        "job_types": ["boss_options.json@job_types"],
        "genders": ["boss_fields.json@genders"],
        "edu_types": ["boss_options.json@edu_types"],
        "degrees_combo": ["boss_options.json@degrees_combo"],
        "countries": ["boss_country_config.json@countries"],
        "languages": ["boss_overseas_languages.json@languages"],
        "durations": ["boss_duration_config.json@durations"],
        "parttime_preferences": ["boss_parttime_preference.json@parttime_prefs"],
        "parttime_times": ["boss_parttime_filter.json@parttime_times"],
        "certificates": ["boss_certificates.json@certificates"],
    },
    "liepin": {
        "positions": ["liepin_job_categories.json@liepin_positions"],
        "industries": ["liepin_industry_categories.json@liepin_industries"],
        "cities": ["liepin_cities.json@liepin_cities"],
        "salary_k": ["liepin_salary_k.json@liepin_salary_k"],
        "job_statuses": ["liepin_dropdowns.json@liepin_status"],
        "political_status": ["liepin_dropdowns.json@liepin_political"],
        "education_levels": ["liepin_options.json@liepin_degrees"],
        "certificates": ["liepin_certificates.json@certificates"],
        "languages": ["liepin_languages.json#languages"],
        "proficiency_levels": ["liepin_languages.json#proficiency_levels"],
    },
}

# 平台 → 哪些字段受选项表约束：scalars 是"字段path→选项组"；arrays 是"数组path→{条目key: 选项组}"；
# string_arrays 是"字符串数组path→选项组"（如海外经历的 countries/languages，整组多选）
_PLATFORM_OPTION_FIELDS = {
    "boss": {
        "scalars": {
            "job_status": "job_statuses",
            "gender": "genders",
            "overseas.duration": "durations",
            # 注意：education_degree / experience_years 在 BOSS 平台是自由文本（fields.json type=text），
            # boss-tab 也无对应下拉，故不附加选项，避免误报「不在平台选项中」
        },
        "string_arrays": {
            "overseas.countries": "countries",
            "overseas.languages": "languages",
            "certificates": "certificates",
        },
        "arrays": {
            "work_experience": {"industry": "industries", "position": "positions"},
            "expectations": {"jobType": "job_types", "position": "positions", "positions": "positions",
                             "city": "cities", "otherCities": "cities", "salary": "salary_ranges",
                             "industries": "industries", "parttime_preference": "parttime_preferences",
                             "parttime_time": "parttime_times"},
            "education": {"degree": "degrees_combo", "eduType": "edu_types"},
        },
    },
    "liepin": {
        "scalars": {
            "basic_info.job_status": "job_statuses",
            "basic_info.political_status": "political_status",
            # 注意：basic_info 的 gender/work_years/education_degree 在猎聘是自由文本/派生字段，
            # 不附加选项，避免误报「不在平台选项中」；work_experience.position 可能为自定义文本
            # （如「电商副店长（统筹运营）」），不做枚举校验，仅校验 job_category 分类
        },
        "string_arrays": {
            "certificates": "certificates",
        },
        "arrays": {
            "expectations": {"position": "positions", "city": "cities", "other_cities": "cities",
                             "industries": "industries", "salary_min": "salary_k", "salary_max": "salary_k"},
            "work_experience": {"job_category": "positions", "industry": "industries", "work_city": "cities"},
            "education": {"degree": "education_levels"},
            "languages": {"language": "languages", "proficiency": "proficiency_levels"},
        },
    },
}

# 选项值的展示标签（BOSS 期望职位 jobType 存 code，前端下拉显示中文）
_OPTION_VALUE_LABELS = {
    "boss": {"job_types": {"fulltime": "全职", "parttime": "兼职"}},
}

# —— 复杂提取器：从爬取 JSON 生成扁平合法取值列表 ——
def _extractor_cities_flat(data):
    """boss_city_full：热门城市 + 全部省份城市（与 boss-tab CitySelector 同源）"""
    out = []
    for c in (data.get("hot_cities") or []) + [c for cities in (data.get("provinces") or {}).values() for c in cities]:
        if c and c not in out:
            out.append(c)
    return out


def _extractor_job_types(data):
    """boss 期望职位类型：全职/兼职（BOSS 官网仅全职、兼职两种 tab）"""
    return ["fulltime", "parttime"]


def _extractor_genders(data):
    """boss_fields 的 gender 选项"""
    node = data.get("gender")
    if isinstance(node, dict):
        return list(node.get("options") or [])
    return ["男", "女"]


def _extractor_edu_types(data):
    """学历二级：全日制/非全日制（与 boss-tab DegreeSelector 一致）"""
    return ["全日制", "非全日制"]


def _extractor_degrees_combo(data):
    """学历组合（BOSS 官网保存格式「学历 / 学制」：大专~博士 × 全日制/非全日制）"""
    combo = []
    for deg in ["大专", "本科", "硕士", "博士"]:
        for t in ["全日制", "非全日制"]:
            combo.append(f"{deg} / {t}")
    return combo


def _extractor_countries(data):
    """boss_country_config：大洲名 + 各国/地区名（与 boss-tab CountrySelector 同源）"""
    out = []
    for region in (data.get("zpData") or {}).get("configList") or []:
        name = region.get("name")
        if name and name != "不限":
            out.append(name)
        for sub in region.get("subLevelModelList") or []:
            n = sub.get("name")
            if n and n != "不限国家/地区" and n not in out:
                out.append(n)
    return out


def _extractor_languages(data):
    """boss_overseas_languages：常用语言（中文/粤语/英语）+ 全部外语并集（与 boss-tab LanguageSelector 同源）"""
    out = []
    for lang in (data.get("allLanguageConfig") or []) + (data.get("languageConfig") or []):
        n = lang.get("name")
        if n and n not in out:
            out.append(n)
    return out


def _extractor_durations(data):
    """驻外时长 12 项（与前端 lib/overseas-options.ts durationOptions 完全一致，boss-tab 同源）"""
    return ["偶尔出差", "频繁出差", "1个月内", "1~3个月", "3~6个月", "6~12个月",
            "1年", "2年", "3年", "4年", "5年以上", "长期驻外"]


def _extractor_parttime_prefs(data):
    """boss_parttime_preference：兼职类型偏好（「您期望做什么类型的兼职」问题的选项）"""
    out = []
    for q in data or []:
        if "类型" not in (q.get("questionTitle") or ""):
            continue
        for o in (q.get("options") or []):
            n = o.get("content")
            if n and n not in out:
                out.append(n)
    return out


def _extractor_parttime_times(data):
    """boss_parttime_filter：兼职时间段（workDayList[].name）"""
    out = []
    for d in (data.get("workDayList") or []):
        n = d.get("name")
        if n and n not in out:
            out.append(n)
    return out


def _extractor_certificates(data):
    """boss_certificates：{分类: [证书名]} → 全部分类并集的证书名（与 boss-tab CertificateSelector 同源）"""
    out = []
    for items in (data or {}).values():
        if not isinstance(items, list):
            continue
        for c in items:
            if isinstance(c, str) and c and c not in out:
                out.append(c)
    return out


# ============ 猎聘选项提取器（与 liepin-tab 各选择器同源） ============

def _extractor_liepin_positions(data):
    """liepin_job_categories：23 个一级类目树形 → 二级类目名 + 三级职位名（与 liepin-tab JobSelector 同源）"""
    out = []
    for cat in data or []:
        for sub in cat.get("subcategories") or []:
            n = sub.get("name")
            if n and n not in out:
                out.append(n)
            for j in sub.get("jobs") or []:
                jn = j.get("name")
                if jn and jn not in out:
                    out.append(jn)
    return out


def _extractor_liepin_industries(data):
    """liepin_industry_categories：一级类目名 + 二级类目名（与 liepin-tab IndustrySelector 同源）"""
    out = []
    for cat in data or []:
        n = cat.get("name")
        if n and n not in out:
            out.append(n)
        for sub in cat.get("subcategories") or []:
            sn = sub.get("name")
            if sn and sn not in out:
                out.append(sn)
    return out


def _extractor_liepin_cities(data):
    """liepin_cities：国内分组 + 海外分组 → 组名 + 城市名（与 liepin-tab CitySelector 同源）"""
    out = []

    def _collect(groups):
        for name, node in (groups or {}).items():
            if name and name not in out:
                out.append(name)
            if isinstance(node, dict):
                for c in (node.get("cities") or []):
                    n = c.get("name") if isinstance(c, dict) else c
                    if n and n not in out:
                        out.append(n)

    _collect(data.get("domestic"))
    _collect(data.get("overseas"))
    return out


def _extractor_liepin_salary_k(data):
    """liepin_salary_k：k 值列表 → 「15k」格式（与 liepin-tab SalarySelector 同源）"""
    return [f"{k}k" for k in (data or []) if isinstance(k, (int, float)) and k > 0]


def _extractor_liepin_status(data):
    """liepin_dropdowns：work_status → options（求职状态 4 项）"""
    for g in ((data or {}).get("work_status") or []):
        return list(g.get("options") or [])
    return []


def _extractor_liepin_political(data):
    """liepin_dropdowns：political_status → options（政治面貌 6 项）"""
    for g in ((data or {}).get("political_status") or []):
        return list(g.get("options") or [])
    return []


def _extractor_liepin_degrees(data):
    """学历 8 项（与 liepin-tab DegreeSelector 同源；liepin_options.json 的 education_levels 仅 7 项缺 MBA/EMBA）"""
    return ["博士", "MBA/EMBA", "硕士", "本科", "大专", "中专/中技", "高中", "初中及以下"]


_EXTRACTORS = {
    "cities_flat": _extractor_cities_flat,
    "job_types": _extractor_job_types,
    "genders": _extractor_genders,
    "edu_types": _extractor_edu_types,
    "degrees_combo": _extractor_degrees_combo,
    "countries": _extractor_countries,
    "languages": _extractor_languages,
    "durations": _extractor_durations,
    "parttime_prefs": _extractor_parttime_prefs,
    "parttime_times": _extractor_parttime_times,
    "certificates": _extractor_certificates,
    "liepin_positions": _extractor_liepin_positions,
    "liepin_industries": _extractor_liepin_industries,
    "liepin_cities": _extractor_liepin_cities,
    "liepin_salary_k": _extractor_liepin_salary_k,
    "liepin_status": _extractor_liepin_status,
    "liepin_political": _extractor_liepin_political,
    "liepin_degrees": _extractor_liepin_degrees,
}

_option_cache: dict = {}
_option_cache_mtime: dict = {}


def _collect_strs(node, out: list):
    """递归提取 dict/list 结构中所有字符串（分层职位/行业表的叶子名）"""
    if isinstance(node, dict):
        for v in node.values():
            _collect_strs(v, out)
    elif isinstance(node, list):
        for x in node:
            if isinstance(x, str):
                out.append(x)
            else:
                _collect_strs(x, out)


def _load_platform_options(platform: str) -> dict:
    """加载平台选项组：{组名: [合法取值去重...]}（带缓存，按选项文件 mtime 失效）"""
    files_map = _OPTION_FILES.get(platform, {})
    newest_mtime = 0.0
    for specs in files_map.values():
        for spec in specs:
            f = str(spec).split("@", 1)[0].split("#", 1)[0]
            try:
                newest_mtime = max(newest_mtime, os.path.getmtime(os.path.join(DATA_DIR, f)))
            except OSError:
                continue
    cached = _option_cache.get(platform)
    if cached is not None and _option_cache_mtime.get(platform) == newest_mtime:
        return cached
    groups = {}
    for group_name, specs in files_map.items():
        values: list = []
        for spec in specs:
            extractor = None
            if "@" in spec:
                spec, extractor = spec.split("@", 1)
            path_key = None
            if "#" in spec:
                spec, path_key = spec.split("#", 1)
            p = os.path.join(DATA_DIR, spec)
            if not os.path.exists(p):
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if path_key:
                    data = (data or {}).get(path_key, [])
                if extractor and extractor in _EXTRACTORS:
                    values.extend(_EXTRACTORS[extractor](data) or [])
                else:
                    _collect_strs(data, values)
            except Exception as e:
                # 选项文件损坏不再静默跳过：LLM 将失去该组枚举约束，必须留痕
                logger.warning("加载 %s 选项文件失败（LLM 将失去 %s 组取值约束）: %s", spec, group_name, e)
                continue
        # 去重且保序
        seen = set()
        uniq = []
        for v in values:
            if v and v not in seen:
                seen.add(v)
                uniq.append(v)
        if uniq:
            groups[group_name] = uniq
    _option_cache[platform] = groups
    _option_cache_mtime[platform] = newest_mtime
    return groups


def _format_option_group_summary(g: list, max_sample: int = 30) -> str:
    if len(g) <= max_sample:
        return f"可选({len(g)}项): {', '.join(g)}"
    sample = ", ".join(g[:max_sample])
    return f"可选({len(g)}项，如: {sample} ... 等共{len(g)}项，支持标准规范匹配)"


def _build_options_prompt_text(platform: str) -> str:
    """生成喂给 LLM 的「平台字段取值约束」段落"""
    groups = _load_platform_options(platform)
    fieldmap = _PLATFORM_OPTION_FIELDS.get(platform, {})
    labels = _OPTION_VALUE_LABELS.get(platform, {})
    if not groups or not fieldmap:
        return ""
    lines = ["===== 平台字段取值约束（禁止自造名称，必须从列表精确选择） ====="]
    for scalar_path, group_name in fieldmap.get("scalars", {}).items():
        g = groups.get(group_name)
        if g:
            lines.append(f"- {scalar_path} → {_format_option_group_summary(g)}")
    for array_path, group_name in fieldmap.get("string_arrays", {}).items():
        g = groups.get(group_name)
        if g:
            lines.append(f"- {array_path}（数组，可为空）→ 每个元素{_format_option_group_summary(g)}")
    for array_path, key_map in fieldmap.get("arrays", {}).items():
        for key, group_name in key_map.items():
            g = groups.get(group_name)
            if g:
                note = ""
                lm = labels.get(group_name)
                if lm:
                    note = "（" + "，".join(f"{v}={lm[v]}" for v in g if v in lm) + "）"
                lines.append(f"- {array_path} 的 {key} 字段 → {_format_option_group_summary(g)}{note}")
    lines.append("数组条目规则：每个 key 都必须给出值，禁止省略或 null；没有对应内容用空字符串；")
    lines.append("枚举类 key（行业/职位/城市等）必须从上面列表中精确选择，找不到就选语义最接近的并标 confidence=low。")
    return "\n".join(lines)


def _attach_field_options(report: dict, platform: str) -> dict:
    """
    为报告条目附加平台选项（前端渲染下拉框用）：
      - 标量字段 → options: [合法取值]
      - 数组/对象字段 → item_options: {条目key: [合法取值]}（对象如 overseas 的 value 为 dict）
      - item_value_labels: {条目key: {code: 中文}}，前端下拉显示中文、存储 code
    """
    groups = _load_platform_options(platform)
    fieldmap = _PLATFORM_OPTION_FIELDS.get(platform, {})
    labels = _OPTION_VALUE_LABELS.get(platform, {})
    scalars = fieldmap.get("scalars", {})
    string_arrays = fieldmap.get("string_arrays", {})
    arrays = fieldmap.get("arrays", {})
    for f in report.get("fields", []):
        path = f["path"]
        if path in scalars:
            g = groups.get(scalars[path])
            if g:
                f["options"] = g
        elif path in string_arrays:
            g = groups.get(string_arrays[path])
            if g:
                f["options"] = g
        elif path in arrays:
            item_opts = {}
            for key, group_name in arrays[path].items():
                g = groups.get(group_name)
                if g:
                    item_opts[key] = g
            if item_opts:
                f["item_options"] = item_opts
                f["type"] = "object" if isinstance(f.get("value"), dict) else "array"
                vlabels = {}
                for key, group_name in arrays[path].items():
                    lm = labels.get(group_name)
                    if lm:
                        vlabels[key] = lm
                if vlabels:
                    f["item_value_labels"] = vlabels
    return report


def _validate_option_consistency(report: dict, platform: str) -> dict:
    """
    校验映射值是否在平台选项内，不在则追加告警（人工在报告里下拉修正）。
    """
    groups = _load_platform_options(platform)
    fieldmap = _PLATFORM_OPTION_FIELDS.get(platform, {})
    scalars = fieldmap.get("scalars", {})
    string_arrays = fieldmap.get("string_arrays", {})
    arrays = fieldmap.get("arrays", {})
    warnings = list(report.get("warnings", []))

    def _bad_items(value, allowed):
        """返回不在选项内的值列表"""
        if isinstance(value, list):
            return [str(x) for x in value if x not in (None, "") and str(x) not in allowed]
        if isinstance(value, str) and value and value not in allowed:
            return [value]
        return []

    for f in report.get("fields", []):
        path = f["path"]
        if path in scalars:
            g = groups.get(scalars[path])
            if g:
                for v in _bad_items(f.get("value"), g):
                    warnings.append(f"{path} 的值「{v}」不在平台选项中，请在报告里选择合法值")
        elif path in string_arrays:
            g = groups.get(string_arrays[path])
            if g:
                for v in _bad_items(f.get("value"), g):
                    warnings.append(f"{path} 的值「{v}」不在平台选项中，请在报告里选择合法值")
        elif path in arrays:
            key_map = arrays[path]
            items = f.get("value") or []
            if isinstance(items, list):
                for i, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue
                    for key, group_name in key_map.items():
                        g = groups.get(group_name)
                        if not g:
                            continue
                        v = item.get(key)
                        # 兼职项的 position 是多项聚合展示串（如「A、B、C」），跳过单值校验
                        if key == "position" and isinstance(v, str) and ("、" in v or "," in v):
                            continue
                        for bad in _bad_items(v, g):
                            warnings.append(f"{path}[{i}].{key} 的值「{bad}」不在平台选项中，请在报告里选择合法值")
            elif isinstance(items, dict):
                # object 类型字段（如 overseas）
                for key, group_name in key_map.items():
                    g = groups.get(group_name)
                    if not g:
                        continue
                    for v in _bad_items(items.get(key), g):
                        warnings.append(f"{path}.{key} 的值「{v}」不在平台选项中，请在报告里选择合法值")
    if warnings:
        report["warnings"] = warnings
    return report


# ============ 配置 / 飞书主简历 ============

# 简历同步中心消费的全部配置键（load_env_config 读取清单；
# tests/test_agent_mapper_config_chain.py 引用同一常量，勿在测试里重复硬编码）
RESUME_SYNC_CONFIG_KEYS = (
    "FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN",
    "FEISHU_TABLE_ID_RESUMES",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
)


def load_env_config() -> dict:
    """LLM 与飞书配置统一走 common.config 的运行时同源链：
    settings.json（配置大盘页面保存）> 环境变量（.env 注入）。

    旧实现只读 backend/.env 文件，绕过了配置大盘——新机器没有 .env 时
    简历同步中心直接报「飞书配置缺失」（2026-09-24 修复）。
    返回 dict 契约保持不变（list_feishu_resumes / load_master_resume /
    _llm_classify_titles / map_platform 四处消费方零改动）。"""
    from common.config import get_configured_value

    # 空值/纯空白键直接剔除（而非留空串）：消费方依赖 cfg.get("OPENAI_MODEL", "gpt-4o-mini")
    # 这类默认值语义，键存在但值为空会吞掉默认值；strip 兜住大盘误填纯空格的场景
    config = {k: v for k in RESUME_SYNC_CONFIG_KEYS if (v := get_configured_value(k).strip())}
    # OpenAI SDK 会自动拼 /chat/completions：配置写成完整请求路径时归一化回基址
    base_url = config.get("OPENAI_BASE_URL", "")
    if base_url.endswith("/chat/completions"):
        config["OPENAI_BASE_URL"] = base_url[: -len("/chat/completions")]
    return config


def _extract_feishu_text(value):
    """把飞书富文本字段拍平成纯文本（与主后端 extract_feishu_text 同逻辑）"""
    if not value:
        return ""
    if isinstance(value, str):
        return value.strip()
    parts = []

    def _dfs(obj):
        if isinstance(obj, dict):
            if "text" in obj and isinstance(obj["text"], str):
                parts.append(obj["text"])
            elif "value" in obj and isinstance(obj["value"], str):
                parts.append(obj["value"])
            for v in obj.values():
                _dfs(v)
        elif isinstance(obj, list):
            for item in obj:
                _dfs(item)

    _dfs(value)
    return "".join(parts).strip() if parts else str(value).strip()


def _get_feishu_token(cfg: dict):
    import requests

    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": cfg.get("FEISHU_APP_ID", ""), "app_secret": cfg.get("FEISHU_APP_SECRET", "")},
        timeout=15,
        # 与数据请求一致绕过系统代理：代理异常时不至于先挂在 token 步骤
        proxies={"http": None, "https": None},
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"飞书鉴权失败: {data.get('msg', 'unknown')}")
    return data["tenant_access_token"]


def _require_feishu_cfg(cfg: dict):
    missing = [k for k in ("FEISHU_APP_ID", "FEISHU_APP_TOKEN", "FEISHU_TABLE_ID_RESUMES") if not cfg.get(k)]
    if missing:
        try:
            from common.config import missing_guide_text
        except ImportError:
            raise RuntimeError(f"飞书配置缺失({'/'.join(missing)})")
        raise RuntimeError(missing_guide_text(missing, "简历同步中心"))


def list_feishu_resumes(cfg: dict = None) -> dict:
    """
    列出飞书简历库全部简历（含停用），供「主简历来源」下拉选择。

    Returns:
        {"ok": True, "resumes": [{"record_id", "name", "status", "char_count"}], "message": str}
        或 {"ok": False, "resumes": [], "message": str}
    """
    cfg = cfg if cfg is not None else load_env_config()
    try:
        import requests

        _require_feishu_cfg(cfg)
        token = _get_feishu_token(cfg)
        url = (
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{cfg['FEISHU_APP_TOKEN']}"
            f"/tables/{cfg['FEISHU_TABLE_ID_RESUMES']}/records"
        )
        headers = {"Authorization": f"Bearer {token}"}
        resumes = []
        page_token = None
        while True:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(url, headers=headers, params=params, timeout=15,
                                proxies={"http": None, "https": None})
            body = resp.json()
            if body.get("code") != 0:
                raise RuntimeError(f"飞书列表失败: {body.get('msg', 'unknown')}")
            data = body.get("data", {})
            for item in data.get("items", []):
                fields = item.get("fields", {})
                raw = _extract_feishu_text(fields.get("结构化数据", ""))
                resumes.append({
                    "record_id": item.get("record_id", ""),
                    "name": _extract_feishu_text(fields.get("简历版本", "")) or "未命名简历",
                    "status": _extract_feishu_text(fields.get("当前状态", "")) or "未知",
                    "char_count": len(raw),
                })
            page_token = data.get("page_token")
            if not page_token or not data.get("has_more"):
                break
        return {"ok": True, "resumes": resumes, "message": f"共 {len(resumes)} 份简历"}
    except Exception as e:
        return {"ok": False, "resumes": [], "message": f"飞书简历库不可用: {e}"}


def load_master_resume(cfg: dict = None, record_id: str = None) -> dict:
    """
    加载主简历。
    - record_id 指定：按 record_id 读取简历库该记录（停用/历史版本均可）
    - record_id 未指定：优先飞书【启用】简历（兼容旧行为）
    失败回退本地 unified_resume.json。

    Returns:
        {
          "ok": bool,
          "source": "feishu" | "local-unified" | None,
          "data": dict,              # 结构化主简历
          "personal_info": str,      # 恒为空：按产品需求不读取「个人信息」MD 列
          "char_count": int,
          "message": str,            # 失败/回退原因
          "record_id": str,          # feishu 来源时：所选记录
          "name": str,               # feishu 来源时：简历版本名
        }
    """
    cfg = cfg if cfg is not None else load_env_config()

    # 1) 飞书
    try:
        import requests

        _require_feishu_cfg(cfg)
        token = _get_feishu_token(cfg)

        if record_id:
            # 指定记录：GET /records/{record_id}（支持停用/历史版本）
            url = (
                f"https://open.feishu.cn/open-apis/bitable/v1/apps/{cfg['FEISHU_APP_TOKEN']}"
                f"/tables/{cfg['FEISHU_TABLE_ID_RESUMES']}/records/{record_id}"
            )
            resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15,
                                proxies={"http": None, "https": None})
            body = resp.json()
            if body.get("code") != 0:
                raise RuntimeError(f"飞书读取记录失败: {body.get('msg', 'unknown')}")
            record = body.get("data", {}).get("record", {})
            fields = record.get("fields", {})
            name = _extract_feishu_text(fields.get("简历版本", "")) or record_id
        else:
            # 默认：搜索【启用】状态的第一份
            url = (
                f"https://open.feishu.cn/open-apis/bitable/v1/apps/{cfg['FEISHU_APP_TOKEN']}"
                f"/tables/{cfg['FEISHU_TABLE_ID_RESUMES']}/records/search"
            )
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "filter": {
                        "conjunction": "and",
                        "conditions": [{"field_name": "当前状态", "operator": "is", "value": ["启用"]}],
                    }
                },
                timeout=15,
                proxies={"http": None, "https": None},
            )
            items = resp.json().get("data", {}).get("items", [])
            if not items:
                raise RuntimeError("飞书无【启用】状态的简历")
            record = items[0]
            fields = record.get("fields", {})
            record_id = record.get("record_id", "")
            name = _extract_feishu_text(fields.get("简历版本", "")) or "启用简历"

        raw = _extract_feishu_text(fields.get("结构化数据", ""))
        if not raw or not raw.strip():
            raise RuntimeError("飞书记录缺少「结构化数据」列内容，无法作为映射源")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as je:
            raise RuntimeError(f"飞书「结构化数据」列不是合法 JSON: {je}")
        # 模块语义归一（思考能力）：标准模块为空时从「简历内容」Markdown 按标题语义回填
        data = _normalize_master_modules(data, _extract_feishu_text(fields.get("简历内容", "")), cfg)
        # 按产品需求：只读取「结构化数据」列，「个人信息」MD 列不读取、不进 prompt
        personal_info = ""
        # 剔除归档块，控制 token
        for k in _MASTER_DROP_KEYS:
            data.pop(k, None)
        return {
            "ok": True,
            "source": "feishu",
            "data": data,
            "personal_info": personal_info,
            "char_count": len(raw),
            "record_id": record_id,
            "name": name,
            "message": f"飞书云端简历读取成功（{len(raw)} 字符）",
        }
    except Exception as e:
        feishu_err = str(e)

    # 2) 本地回退
    unified_path = os.path.join(DATA_DIR, "unified_resume.json")
    try:
        if os.path.exists(unified_path):
            with open(unified_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data:
                return {
                    "ok": True,
                    "source": "local-unified",
                    "data": data,
                    "personal_info": "",
                    "char_count": len(json.dumps(data, ensure_ascii=False)),
                    "message": f"飞书不可用（{feishu_err}），已回退本地汇总数据（可能非最新，请注意核对简历时效）",
                }
    except Exception:
        pass

    return {"ok": False, "source": None, "data": {}, "personal_info": "", "char_count": 0,
            "message": f"主简历加载失败: {feishu_err}"}


def master_payload(master: dict) -> str:
    """把主简历压成喂给 LLM 的文本块（只含结构化数据，个人信息列不读取）"""
    data = {k: v for k, v in master.get("data", {}).items() if k not in _MASTER_DROP_KEYS}
    return "【结构化主简历】\n" + json.dumps(data, ensure_ascii=False)


# ============ 平台字段 schema（纯函数） ============

# 模块分类定义（支持前置按需选择映射模块）
MODULE_KEYS = {
    "basic_info": (
        "basic_info", "name", "phone", "email", "wechat", "gender", "birth_month", "start_work_year",
        "current_salary", "current_city", "political_status", "marriage", "avatar",
        "hideResume", "job_status", "firstWorkTime", "currentCity", "profile",
        "liveCity", "userWorkAge", "address", "homePage", "hukou", "maritalStatus",
        "political", "idCard", "work_status", "age", "marital_status", "work_years",
        "city", "birth", "work_start_date", "identity", "show_gender_suffix",
        "current_salary_month", "current_salary_months", "salary_confidential",
        "education_degree", "current_company", "current_title", "current_industry",
        "household", "nationality", "experience_years", "work_age"
    ),
    "personal_advantage": ("personal_advantage", "self_evaluation", "summary", "selfEvaluation", "self_assessment", "self_introduction"),
    "expectations": ("expectations", "wanna", "job_preferences", "hopeJob", "hopeCity", "hopeSalary", "preferred_city", "intentions"),
    "work_experience": ("work_experience", "workExperience", "works"),
    "projects": ("projects", "project", "projectExperience"),
    "education": ("education", "educations"),
    "skills": ("skills", "professionalSkills", "skill_tags"),
    "certificates": (
        "certificates", "certificate", "certifications", "languages", "language",
        "social_experience", "custom_fields"
    ),
    "trainings": ("trainings", "training"),
    "overseas": ("overseas",),
}


def _field_path_to_module(path: str) -> str:
    """根据字段 path（例如 profile.name, work_experience, overseas.allowView）识别所属模块 key"""
    p = str(path or "").strip()
    root = p.split(".")[0].strip()
    for mod, keys in MODULE_KEYS.items():
        if root in keys or p in keys:
            return mod
    return "basic_info"


def flatten_schema(fields_data: dict, selected_modules: list[str] | None = None) -> list:
    """
    把 {platform}_fields.json 拍平成字段清单。
    可选 selected_modules 过滤：仅输出指定模块的字段清单，大幅缩减 Prompt 体积并实现前置隔离。

    返回:
      [ {path, kind:"scalar"|"array"|"object", label, type, required,
         current(str 摘要), item_keys(array 时)} ]

    规则：
      - 顶层 type=object 且 current_value 是 dict → 展开为 "key.sub" 标量
      - type=array → kind=array，item_keys 取自 current_value[0]
      - 智联等原生节点结构（profile 为 dict，workExperience/education/selfEvaluation 为 list）智能展开
      - 以 Translation 结尾的派生字段跳过（由主字段推导）
    """
    out = []
    if not isinstance(fields_data, dict):
        return out

    zhilian_labels = {
        "profile": "基本信息",
        "jobStatus": "求职状态",
        "wanna": "求职意向",
        "workExperience": "工作经历",
        "education": "教育经历",
        "project": "项目经历",
        "projectExperience": "项目经历",
        "training": "培训经历",
        "language": "语言能力",
        "professionalSkills": "专业技能",
        "skills": "专业技能",
        "certificate": "资格证书",
        "selfEvaluation": "个人优势/自我评价",
    }

    for key, node in fields_data.items():
        if key.endswith("Translation"):
            continue

        # 智联等原生 list 结构适配
        if isinstance(node, list):
            item_keys = []
            if node and isinstance(node[0], dict):
                item_keys = list(node[0].keys())
            label = zhilian_labels.get(key, key)
            if key == "selfEvaluation":
                cur_text = node[0].get("selfEvaContent", "") if node and isinstance(node[0], dict) else ""
                out.append({
                    "path": "self_evaluation",
                    "kind": "scalar",
                    "label": "个人优势/自我评价",
                    "type": "textarea",
                    "required": True,
                    "current": cur_text,
                })
            else:
                mapped_path = "work_experience" if key == "workExperience" else ("projects" if key in ("project", "projectExperience") else key)
                out.append({
                    "path": mapped_path,
                    "kind": "array",
                    "label": label,
                    "type": "array",
                    "required": False,
                    "current": f"list[{len(node)}]",
                    "item_keys": item_keys,
                })
            continue

        if not isinstance(node, dict):
            out.append({"path": key, "kind": "scalar", "label": key, "type": "raw",
                        "required": False, "current": _brief(node)})
            continue

        t = node.get("type", "")
        label = node.get("label", zhilian_labels.get(key, key))
        required = bool(node.get("required"))

        # 智联 profile 原生 dict 适配
        if "current_value" not in node and key == "profile":
            for sub, val in node.items():
                if sub.endswith("Translation"):
                    continue
                out.append({
                    "path": f"profile.{sub}",
                    "kind": "scalar",
                    "label": f"基本信息·{sub}",
                    "type": "text",
                    "required": False,
                    "current": _brief(val),
                })
            continue

        cv = node.get("current_value")

        if t == "array" or isinstance(cv, list):
            item_keys = []
            if cv and isinstance(cv[0], dict):
                item_keys = list(cv[0].keys())
            out.append({"path": key, "kind": "array", "label": label, "type": "array",
                        "required": required, "current": f"list[{len(cv) if isinstance(cv, list) else 0}]",
                        "item_keys": item_keys})
        elif t == "object" or isinstance(cv, dict):
            if isinstance(cv, dict) and cv:
                for sub, val in cv.items():
                    if sub.endswith("Translation"):
                        continue
                    out.append({"path": f"{key}.{sub}", "kind": "scalar", "label": f"{label}·{sub}",
                                "type": "object-field", "required": False, "current": _brief(val)})
            else:
                out.append({"path": key, "kind": "object", "label": label, "type": t,
                            "required": required, "current": "空对象"})
        else:
            # textarea 长文本给 LLM 完整现有值
            current = cv if (t == "textarea" and isinstance(cv, str)) else _brief(cv)
            out.append({"path": key, "kind": "scalar", "label": label, "type": t or "text",
                        "required": required, "current": current})

    if selected_modules and len(selected_modules) > 0:
        sel_set = set(selected_modules)
        out = [f for f in out if _field_path_to_module(f.get("path", "")) in sel_set]

    return out


def _brief(v, limit=80) -> str:
    if v is None or v == "" or v == [] or v == {}:
        return "空"
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + "…"


def get_path(fields_data: dict, path: str):
    """按点路径读字段值：兼容 current_value 包装与智联等原生节点结构"""
    if not isinstance(fields_data, dict) or not path:
        return None

    # 别名兼容：自述
    if path in ("self_evaluation", "selfEvaluation", "self_assessment", "personal_advantage", "self_introduction"):
        if "selfEvaluation" in fields_data:
            se = fields_data["selfEvaluation"]
            if isinstance(se, list) and se and isinstance(se[0], dict):
                return se[0].get("selfEvaContent", "")
            return se
        if "self_evaluation" in fields_data:
            node = fields_data["self_evaluation"]
            return node.get("current_value") if isinstance(node, dict) and "current_value" in node else node

    # 别名兼容：工作经历
    if path in ("work_experience", "workExperience", "works"):
        if "workExperience" in fields_data:
            return fields_data["workExperience"]
        if "work_experience" in fields_data:
            node = fields_data["work_experience"]
            return node.get("current_value") if isinstance(node, dict) and "current_value" in node else node
        if "works" in fields_data:
            node = fields_data["works"]
            return node.get("current_value") if isinstance(node, dict) and "current_value" in node else node

    # 别名兼容：项目经历
    if path in ("projects", "project", "projectExperience"):
        if "project" in fields_data:
            return fields_data["project"]
        if "projectExperience" in fields_data:
            return fields_data["projectExperience"]
        if "projects" in fields_data:
            node = fields_data["projects"]
            return node.get("current_value") if isinstance(node, dict) and "current_value" in node else node

    # 别名兼容：教育经历
    if path in ("education", "educations"):
        if "education" in fields_data:
            node = fields_data["education"]
            if isinstance(node, list):
                return node
            return node.get("current_value") if isinstance(node, dict) and "current_value" in node else node
        if "educations" in fields_data:
            node = fields_data["educations"]
            return node.get("current_value") if isinstance(node, dict) and "current_value" in node else node

    # 别名兼容：证书 (certificate / certificates / certifications)
    if path in ("certificates", "certificate", "certifications"):
        for k in ("certificate", "certificates", "certifications"):
            if k in fields_data:
                node = fields_data[k]
                return node.get("current_value") if isinstance(node, dict) and "current_value" in node else node

    # 别名兼容：专业技能 (professionalSkills / skill_tags / skills)
    if path in ("professionalSkills", "professional_skills", "skill_tags", "skills"):
        for k in ("professionalSkills", "professional_skills", "skill_tags", "skills"):
            if k in fields_data:
                node = fields_data[k]
                return node.get("current_value") if isinstance(node, dict) and "current_value" in node else node

    # 别名兼容：基本信息标量
    if path in ("name", "gender", "birthyear", "birthmonth", "currentIdentity", "currentStatus", "mobile", "email"):
        if "profile" in fields_data and isinstance(fields_data["profile"], dict):
            return fields_data["profile"].get(path)

    parts = path.split(".")
    node = fields_data.get(parts[0])
    if node is None:
        return None
    if len(parts) == 1:
        if isinstance(node, dict) and "current_value" in node:
            return node.get("current_value")
        return node

    if isinstance(node, dict):
        if "current_value" in node and isinstance(node["current_value"], dict):
            return node["current_value"].get(parts[1])
        return node.get(parts[1])
    return None


def set_path(fields_data: dict, path: str, value) -> bool:
    """按点路径写字段值：兼容 current_value 包装与智联等原生节点结构。成功返回 True。"""
    if not isinstance(fields_data, dict) or not path:
        return False

    # 1. 自我评价 / 个人优势
    if path in ("self_evaluation", "selfEvaluation", "self_assessment", "personal_advantage", "self_introduction"):
        if "selfEvaluation" in fields_data or ("profile" in fields_data and "selfEvaluation" not in fields_data):
            if isinstance(value, str):
                if "selfEvaluation" in fields_data and isinstance(fields_data["selfEvaluation"], list) and fields_data["selfEvaluation"]:
                    fields_data["selfEvaluation"][0]["selfEvaContent"] = value
                    fields_data["selfEvaluation"][0]["selfEvaTitle"] = "自我介绍"
                else:
                    fields_data["selfEvaluation"] = [{"selfEvaContent": value, "selfEvaTitle": "自我介绍"}]
                return True
            elif isinstance(value, list):
                fields_data["selfEvaluation"] = value
                return True
        if "self_evaluation" in fields_data:
            node = fields_data["self_evaluation"]
            if isinstance(node, dict) and "current_value" in node:
                node["current_value"] = value
            else:
                fields_data["self_evaluation"] = value
            return True
        if "self_assessment" in fields_data:
            node = fields_data["self_assessment"]
            if isinstance(node, dict) and "current_value" in node:
                node["current_value"] = value
            else:
                fields_data["self_assessment"] = value
            return True
        if "personal_advantage" in fields_data:
            node = fields_data["personal_advantage"]
            if isinstance(node, dict) and "current_value" in node:
                node["current_value"] = value
            else:
                fields_data["personal_advantage"] = value
            return True

    # 2. 工作经历
    if path in ("work_experience", "workExperience", "works"):
        if "workExperience" in fields_data or ("profile" in fields_data and "workExperience" not in fields_data):
            fields_data["workExperience"] = value
            return True
        if "work_experience" in fields_data:
            node = fields_data["work_experience"]
            if isinstance(node, dict) and "current_value" in node:
                node["current_value"] = value
            else:
                fields_data["work_experience"] = value
            return True
        if "works" in fields_data:
            node = fields_data["works"]
            if isinstance(node, dict) and "current_value" in node:
                node["current_value"] = value
            else:
                fields_data["works"] = value
            return True

    # 3. 项目经历
    if path in ("projects", "project", "projectExperience"):
        if "project" in fields_data or ("profile" in fields_data and "project" not in fields_data and "projectExperience" not in fields_data):
            fields_data["project"] = value
            return True
        if "projectExperience" in fields_data:
            fields_data["projectExperience"] = value
            return True
        if "projects" in fields_data:
            node = fields_data["projects"]
            if isinstance(node, dict) and "current_value" in node:
                node["current_value"] = value
            else:
                fields_data["projects"] = value
            return True

    # 4. 教育经历
    if path in ("education", "educations"):
        if "education" in fields_data or ("profile" in fields_data and "education" not in fields_data):
            if isinstance(fields_data.get("education"), list) or "profile" in fields_data:
                fields_data["education"] = value
                return True
            elif isinstance(fields_data["education"], dict) and "current_value" in fields_data["education"]:
                fields_data["education"]["current_value"] = value
                return True
            else:
                fields_data["education"] = value
                return True
        if "educations" in fields_data:
            node = fields_data["educations"]
            if isinstance(node, dict) and "current_value" in node:
                node["current_value"] = value
            else:
                fields_data["educations"] = value
            return True

    # 5. 证书 (certificate / certificates / certifications)
    if path in ("certificates", "certificate", "certifications"):
        for k in ("certificate", "certificates", "certifications"):
            if k in fields_data:
                node = fields_data[k]
                if isinstance(node, dict) and "current_value" in node:
                    node["current_value"] = value
                else:
                    fields_data[k] = value
                return True

    # 6. 专业技能 (professionalSkills / skill_tags / skills)
    if path in ("professionalSkills", "professional_skills", "skill_tags", "skills"):
        norm_val = value
        if isinstance(value, list):
            valid_items = []
            for it in value:
                if isinstance(it, str) and it.strip():
                    valid_items.append({
                        "proskillName": it.strip(),
                        "proskillLevel": "熟练",
                        "proskillType": "13",
                        "proskillUseTime": "12"
                    })
                elif isinstance(it, dict):
                    name = str(it.get("proskillName") or it.get("name") or it.get("skill") or "").strip()
                    if name:
                        valid_items.append({
                            "path": it.get("path", ""),
                            "proskillName": name,
                            "proskillLevel": it.get("proskillLevel") or "熟练",
                            "proskillType": str(it.get("proskillType") or "13"),
                            "proskillUseTime": re.sub(r"[^\d]", "", str(it.get("proskillUseTime") or "12")) or "12",
                        })
            norm_val = valid_items if valid_items else value

        for k in ("professionalSkills", "professional_skills", "skill_tags", "skills"):
            if k in fields_data:
                node = fields_data[k]
                if isinstance(node, dict) and "current_value" in node:
                    if isinstance(node["current_value"], list) and node["current_value"] and isinstance(node["current_value"][0], str):
                        node["current_value"] = [
                            (x if isinstance(x, str) else x.get("proskillName", ""))
                            for x in (norm_val if isinstance(norm_val, list) else [])
                        ]
                    else:
                        node["current_value"] = norm_val
                else:
                    fields_data[k] = norm_val
                return True

    # 7. 基本信息标量
    if path in ("name", "gender", "birthyear", "birthmonth", "currentIdentity", "currentStatus", "mobile", "email"):
        if "profile" in fields_data and isinstance(fields_data["profile"], dict):
            fields_data["profile"][path] = value
            return True

    # 6. profile 整体
    if path == "profile" and isinstance(value, dict):
        if "profile" in fields_data and isinstance(fields_data["profile"], dict):
            fields_data["profile"].update(value)
            return True

    # 7. 一般点路径处理
    parts = path.split(".")
    if len(parts) == 1:
        k = parts[0]
        if k in fields_data:
            node = fields_data[k]
            if isinstance(node, dict) and "current_value" in node:
                node["current_value"] = value
            else:
                fields_data[k] = value
            return True
        return False

    # 路径约定只有"顶层键"与"键.子键"两级：含数组索引段（works.0.companyName 之类）
    # 的路径会把索引当 key 写进 wrapper dict 污染 schema，明确拒绝
    if len(parts) > 2 or any(p.isdigit() for p in parts):
        logger.warning("set_path 拒绝非法路径（不支持数组索引/三级路径）: %s", path)
        return False

    node = fields_data.get(parts[0])
    if node is None:
        return False
    if isinstance(node, dict):
        if "current_value" in node and isinstance(node["current_value"], dict):
            if parts[1] in node["current_value"]:
                node["current_value"][parts[1]] = value
                return True
            node["current_value"][parts[1]] = value
            return True
        elif parts[1] in node:
            node[parts[1]] = value
            return True
        else:
            node[parts[1]] = value
            return True
    return False


# ============ Prompt 与校验（纯函数） ============

CONFIDENCE_LEVELS = ("high", "medium", "low")

# 平台专属映射规则（追加在通用规则之后）
_PLATFORM_PROMPT_EXTRA = {
    "51job": """===== 平台专属规则（前程无忧） =====
P1. projects 项目经历时间：主简历某项目只有单个时间点（如 '2026.03'，无结束时间也未写'至今'）时，该条 endTime 必须等于 startTime（同月），严禁填'至今'；仅当主简历明确写了'至今'才填 endTime='至今'。
P2. works 工作经历：
    a) 条目完整性：主简历的所有工作经历必须全部映射输出到 works 数组（若条数多于平台现有条目，自动追加新条目）；
    b) 相关技能（workVocationalSkills / skills）：针对每段经历，从职责与项目描述中提炼 3～8 个具体的核心技能关键词（如技术栈、工具、方法、业务能力），输出字符串数组；
    c) 工作类型（workType / seekType）：根据经历描述、公司与职位推测工作类型（"0" 为全职, "1" 为兼职/自由职业, "2" 为实习），默认为 "0"；
    d) 职位类目（workFunction / workFunctionString）：原样输出该条现有值即可，系统会根据主简历职位自动精确匹配修正，禁止自行猜测或编造代码。
P3. skills 专业技能（前程无忧官方标准白名单限制）：
    a) 白名单约束：必须严格从 51job 官方标准技能库（如 Python, SQL, 数据分析, 数据挖掘, MySQL, Linux, Shell, HTML5, JavaScript, Web前端, TensorFlow, MS Excel, MS Powerpoint, Photoshop 等）中挑选 8～12 个与主简历实际掌握和项目深度高度契合的核心技术词；严禁输出段落大纲分类标题（严禁输出“大模型与 AI 工程”、“全栈开发与架构”等标题），严禁输出白名单以外无法对齐的自造词；
    b) 熟练程度智能评估（ability）：根据候选人在主简历中的项目主导深度、技术运用年限客观评估分配熟练度枚举代码：
       - "0": 精通（独立架构从0到1研发、核心主力技术）
       - "1": 熟练（熟练运用交付核心模块）
       - "3": 良好（日常使用或常用辅助工具）
       - "2": 一般（基础了解或初级使用）
       严禁输出空 ability 字符串！
    c) 字段格式：每个技能条目输出结构：
       - skillType: 官方技能码（4位字符串，如 "0413" 为 Python, "0202" 为 数据分析, "0215" 为 SQL）；
       - skillName: 官方技能名称（如 "Python", "数据分析", "SQL"）；
       - ability: 熟练程度码（"0", "1", "3", "2"）；
       - isEnglish: false（布尔值）。""",
    "zhilian": """===== 平台专属规则（智联招聘） =====
P1. 个人优势 (self_evaluation)：必须将主简历 summary 完整提取填入 self_evaluation，官网上限 500 字，禁止写入 profile。
P2. 工作经历 (work_experience)：
    a) 条目完整性：主简历的所有工作经历必须全部映射输出到 work_experience 数组；
    b) 描述正文 (workDesc)：将主简历每段工作经历的职责与业绩完整填入 workDesc；
    c) 公司与职位：companyName 填公司名称，jobTitle/title 填职位名称；
    d) 起止时间：startDate 格式为 'YYYY.MM'（如 '2024.04'），若未结束则 endDate 填 '至今'，结束时间格式为 'YYYY.MM'。
P3. 项目经历 (projects)：proExpProjectName 填项目名称，proExpProjectDesc 填项目描述，proExpStartDate 填开始时间，proExpEndDate 填结束时间。
P4. 教育经历 (education)：eduSchoolName 填学校名称，eduMajorV 填专业名称，eduStartDate 填开始时间，eduEndDate 填结束时间。""",
}


def build_mapping_prompt(platform: str, platform_label: str, master_text: str, schema: list,
                         options_text: str = "") -> str:
    """构造单平台映射 prompt"""
    schema_lines = []
    for f in schema:
        if f["kind"] == "array":
            keys = ",".join(f.get("item_keys") or []) or "（无现成条目，结构自定）"
            schema_lines.append(f"- {f['path']} | 数组 | {f['label']} | required={f['required']} | 现有条目字段: [{keys}] | 现有: {f['current']}")
        else:
            schema_lines.append(f"- {f['path']} | {f['type']} | {f['label']} | required={f['required']} | 现有值: {f['current']}")

    options_block = f"\n{options_text}\n" if options_text else ""
    platform_extra = _PLATFORM_PROMPT_EXTRA.get(platform, "")
    platform_extra_block = f"\n{platform_extra}\n" if platform_extra else ""

    return f"""你是招聘平台简历字段映射专家。任务：把「主简历」的内容**原样搬运**到「{platform_label}」平台的字段里——你是搬运工，不是写手。

===== 主简历 =====
{master_text}

===== 目标平台字段清单（{platform}） =====
{chr(10).join(schema_lines)}
{options_block}===== 映射规则（必须严格遵守） =====
1. 只输出主简历里真实存在的信息，严禁编造、润色出主简历没有的内容（"了解"级也不要脑补成"精通"）。
2. 枚举/下拉/编码类字段：优先从「平台字段取值约束」的列表中精确选择（若存在该段落）；没有取值约束的，参照该字段「现有值」的格式与取值风格；两者都拿不准就放入 unfilled，绝不编造 code。
   **数组条目的枚举字段（如 position/industry）必须从取值约束列表精确选择**：列表内找不到精确匹配时，该字段填空字符串 ""（禁止近似匹配、禁止编造新词），并把该条目写入 warnings 提示人工选择。
3. 以 Translation/String 结尾的派生字段不用填（系统自动推导）。
4. 数组字段（工作经历/项目经历/教育经历等）：输出完整数组，每个条目的 key 必须与「现有条目字段」完全一致，且每个 key 都必须给出值——没有对应内容用空字符串，禁止省略 key、禁止填 null；时间拆成平台要求的年/月字段；没有现成条目结构时按主简历内容合理构造。
   **数组条目字段类型**：布尔字段（如 hideResume）必须输出 true/false 布尔值，禁止输出字符串。**技能字段（如 BOSS 工作经历的 skills、51job 工作经历的 workVocationalSkills / skills）是全任务唯一要求并允许你运用大模型分析提炼能力的字段，不受规则 4b/4c 照抄约束**：大模型必须深度分析该段工作经历的职责与项目描述，精准提炼技能关键词（技术栈、工具、框架、方法、业务能力等），输出为字符串数组，每段经历提取 3～8 个核心关键词；关键词必须具体简短（一般不超过 12 字，禁止输出整句、禁止带标点或序号），先去重再按重要度从高到低排列；该条描述确实没有技能线索时输出 []，禁止把主简历其他条目或其他板块的内容混入。
4b. **文本内容字段必须照抄主简历原文并输出为纯文本（本条为最高优先级硬约束）**：工作经历/项目经历的描述内容（content/description/achievement）、教育经历的 campus_experience/thesisDesc、自我评价等自由文本字段，必须**逐字保留**主简历对应条目的文字内容——禁止改写、重组、压缩、扩写、润色、调整换行或标点，禁止把主简历其他板块（自我评价/项目经历/技能等）的内容混入该条描述，禁止凭记忆补写主简历没有写过的句子。唯一允许的加工：把主简历的时间拆成平台要求的年/月字段。**若主简历该条描述是多段数组，必须完整保留全部段落，禁止省略任何一段。输出时去除所有 Markdown 格式符号转为纯文本**：如 **加粗** → 加粗、- 或 * 列表符号、# 标题符号、`代码`反引号一律去掉，仅保留文字内容本身。
4c. **公司名等自由文本字段同样逐字照抄主简历**（如公司全名不得删减或改写）；职位/行业等枚举字段仍按规则 2 从取值约束列表精确选择，列表内无精确匹配则填空字符串 "" 并写入 warnings，禁止用近似词替代。
4d. **期望职位（expectations）类型上限**：若平台期望条目含 jobType 字段——全职（jobType=fulltime）最多 3 条、兼职（jobType=parttime）最多 1 条。平台现有值已有条目时必须原样保留（保持 jobType、条目内容与顺序不变，禁止把兼职条目转成全职或反之、禁止增减条目数）；现有值为空且主简历有明确求职意向线索时，在上限内按线索构造；无明确线索则放入 unfilled 并说明原因，禁止凭空猜测。严禁输出超过上限的条目。
5. 主简历没有对应信息的字段：放入 unfilled 并给 reason，不要硬填。
   **证书字段（certificates）特殊规则**：优先从主简历的经历/技能/教育推断资格证书（如语言证书、计算机证书、从业资格）；主简历确实没有证书线索时，若平台现有值非空则原样沿用现有值（confidence=low），现有值也为空则输出 []。该字段不放入 unfilled。
6. 每个填入字段给 confidence：high=主简历有直接明确对应；medium=需要轻度推断或选了最接近取值；low=不确定、需人工重点核对。
7. 现有值已经和主简历一致的字段也要输出（confidence=high），便于整体核对。
8. **覆盖语义（硬约束）**：主简历是用户为本次映射选定的唯一权威来源。主简历对应板块有值且与平台现有值不一致时，必须输出主简历内容覆盖现有值（映射的意义就是把主简历内容同步到平台）；严禁以「内容不同/沿用现有值」为由自作主张输出现有值。仅当主简历确实没有对应信息时才按规则 5/7 沿用现有值或放 unfilled。
{platform_extra_block}
===== 输出格式（只输出一个纯 JSON 对象，无任何其他文字） =====
{{
  "platform": "{platform}",
  "fields": [
    {{"path": "字段path", "value": "填入值(数组字段为数组)", "confidence": "high|medium|low", "source": "主简历来源板块", "note": "可选备注"}}
  ],
  "unfilled": [
    {{"path": "字段path", "label": "字段名", "reason": "为何无法填入"}}
  ],
  "warnings": ["全局提醒，如编码字段无参照需人工确认"]
}}"""


def validate_mapping_result(parsed: dict, fields_data: dict) -> dict:
    """
    校验并规范化 LLM 输出：
      - 丢弃 schema 中不存在的 path（防幻觉字段）
      - confidence 非法值降级为 low
      - 数组字段 value 必须是 list
    返回规范化后的报告 dict。
    """
    valid_paths = {f["path"] for f in flatten_schema(fields_data)}
    # object/array 顶层节点本身也允许
    for k, v in (fields_data or {}).items():
        if not k.endswith("Translation"):
            valid_paths.add(k)

    fields_out = []
    for item in parsed.get("fields", []) or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if not path or path not in valid_paths:
            continue
        if path.endswith("Translation"):
            continue
        conf = item.get("confidence", "low")
        if conf not in CONFIDENCE_LEVELS:
            conf = "low"
        value = item.get("value")
        node = fields_data.get(path.split(".")[0])
        is_array = isinstance(node, dict) and (node.get("type") == "array" or isinstance(node.get("current_value"), list)) and "." not in path
        if is_array and not isinstance(value, list):
            continue  # 数组字段必须给数组，否则丢弃
        f_type = "array" if is_array else (node.get("type", "") if isinstance(node, dict) else "")
        fields_out.append({
            "path": path,
            "value": value,
            "confidence": conf,
            "source": str(item.get("source", "")),
            "note": str(item.get("note", "") or ""),
            "type": f_type,
        })

    unfilled_out = []
    # 幽灵路径过滤：LLM 编造的、schema 中不存在的 unfilled 路径不进报告
    # （apply 时 set_path 才拦会导致前端先展示出幽灵字段）
    schema_paths = {f["path"] for f in flatten_schema(fields_data)} if fields_data else set()
    object_roots = {p.split(".")[0] for p in schema_paths if "." in p}
    for item in parsed.get("unfilled", []) or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if not path:
            continue
        if schema_paths and path not in schema_paths and path not in object_roots:
            continue
        unfilled_out.append({
            "path": path,
            "label": str(item.get("label", path)),
            "reason": str(item.get("reason", "") or ""),
        })

    warnings = [str(w) for w in (parsed.get("warnings", []) or []) if isinstance(w, (str, int))]

    report = {
        "platform": str(parsed.get("platform", "")),
        "fields": fields_out,
        "unfilled": unfilled_out,
        "warnings": warnings,
    }
    # 用户规则：主简历未提供的字段也必须出现在字段列表（可主动新增/修改），
    # 「待人工补充」保留说明，两处联动
    return _ensure_unfilled_fields(report, fields_data)


def _ensure_unfilled_fields(report: dict, fields_data: dict, selected_modules: list[str] | None = None) -> dict:
    """
    把 unfilled 里的 path 追加为低置信条目，保证字段列表里能看到并直接新增/修改：
      - 标量/数组字段：直接追加（value 用平台现有值，无则按类型默认：[]/""）
      - 对象字段（如 overseas）：展开为子字段条目（overseas.countries / overseas.allowView 等），
        保证前端渲染对应的选择器控件（国家/语言/布尔 checkbox）
    note 沿用「待人工补充」的原因说明；已映射的 path 不覆盖。
    若传入 selected_modules，仅为选中模块补全 unfilled 字段。
    """
    fields_out = report.get("fields", [])
    existing = {f["path"] for f in fields_out}
    sub_schema = {f["path"]: f for f in flatten_schema(fields_data, selected_modules=selected_modules)} if fields_data else {}
    for u in report.get("unfilled", []) or []:
        path = str(u.get("path", "")).strip()
        if not path or path in existing:
            continue
        if selected_modules and len(selected_modules) > 0 and _field_path_to_module(path) not in selected_modules:
            continue
        reason = str(u.get("reason", "") or "")
        node = fields_data.get(path.split(".")[0]) if fields_data else None
        is_object = (isinstance(node, dict) and "." not in path
                     and (node.get("type") == "object" or isinstance(node.get("current_value"), dict)))
        # 幽灵路径过滤：LLM 编造的、schema 中不存在的路径不进报告
        # （对象 root 除外——其子字段在 sub_schema 中展开，root 本身不在）
        if sub_schema and not is_object and path not in sub_schema:
            continue
        if is_object:
            # 对象字段展开为子字段条目（与 flatten_schema 展开一致）
            for sub_f in sub_schema.values():
                if not sub_f["path"].startswith(path + "."):
                    continue
                if sub_f["path"] in existing:
                    continue
                if selected_modules and len(selected_modules) > 0 and _field_path_to_module(sub_f["path"]) not in selected_modules:
                    continue
                fields_out.append({
                    "path": sub_f["path"],
                    "value": get_path(fields_data, sub_f["path"]),
                    "confidence": "low",
                    "source": "",
                    "note": reason,
                    "type": sub_f.get("type", "object-field"),
                })
                existing.add(sub_f["path"])
            continue
        # 标量/数组：追加（value 用平台现有值，无则按类型默认）
        cv = get_path(fields_data, path)
        is_array = (isinstance(cv, list)
                    or (isinstance(node, dict) and node.get("type") == "array" and "." not in path))
        default = cv if cv not in (None, "") else ([] if is_array else "")
        fields_out.append({
            "path": path,
            "value": default,
            "confidence": "low",
            "source": "",
            "note": reason,
            "type": "array" if is_array else (node.get("type", "") if isinstance(node, dict) else ""),
        })
        existing.add(path)
    return report


def _normalize_month_value(v):
    """月份归一化：'04' → '4'；'1996-04' → '1996-4'；非数字原样返回"""
    if isinstance(v, str):
        s = v.strip()
        if re.fullmatch(r"\d{1,2}", s):
            return str(int(s))
        m = re.fullmatch(r"(\d{4})-(\d{1,2})", s)
        if m:
            return f"{m.group(1)}-{int(m.group(2))}"
    return v


# ============ 描述正文逐字照抄兜底 ============

# 平台数组条目的「描述正文」字段 → 主简历对应板块
_VERBATIM_DESC_FIELD = {
    "boss": {"work_experience": "content", "projects": "project_description", "education": "campus_experience"},
    "zhilian": {"work_experience": "workDesc", "projects": "proExpProjectDesc"},
    "liepin": {"work_experience": "responsibilities", "projects": "description"},
    "51job": {"projects": "describe"},
}
_MASTER_SECTION = {"work_experience": "workExperience", "projects": "personalProjects", "education": "education"}
# 公司名照抄兜底：主简历 company 非空须逐字一致；为空则清空（防 LLM 拿职位名/其他内容顶替）
_VERBATIM_COMPANY_FIELD = {
    "boss": {"work_experience": "company"},
    "zhilian": {"work_experience": "companyName"},
    "liepin": {"work_experience": "company"},
}


def _parse_master_years(years) -> tuple | None:
    """解析主简历条目时间 '2024.04-至今' / '2026.02-06' → (年, 月)；解析失败返回 None"""
    if not years:
        return None
    m = re.match(r"(\d{4})[.\-/](\d{1,2})", str(years))
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)))


def _plat_start_ym(item: dict) -> tuple | None:
    """从平台条目提取起始年月，兼容 startYear/startMonth 与 startDateFormat/start_date 等命名"""
    for yk, mk in (("startYear", "startMonth"), ("start_year", "start_month")):
        y, mo = item.get(yk), item.get(mk)
        if y is not None and mo not in (None, ""):
            try:
                return (int(y), int(mo))
            except (TypeError, ValueError):
                pass
    for k in ("startDateFormat", "start_date", "startTimeString", "startDate"):
        s = item.get(k)
        if s:
            m = re.match(r"(\d{4})[.\-/](\d{1,2})", str(s))
            if m:
                return (int(m.group(1)), int(m.group(2)))
    return None


def _match_master_index(master_items: list, plat_item: dict, idx: int) -> int | None:
    """
    定位平台条目对应的主简历条目：名称唯一命中 → 起始年月 → 顺序，三级匹配。
    （多个主简历条目同名时名称匹配不可靠，退化为时间/顺序，防止错配覆盖）
    """
    if not master_items:
        return None
    pn = None
    for k in ("project_name", "proExpProjectName", "projectName", "name", "company"):
        v = plat_item.get(k)
        if v:
            pn = str(v).strip()
            break
    if pn:
        hits = [i for i, mi in enumerate(master_items)
                if any(mi.get(k) and str(mi[k]).strip() == pn
                       for k in ("name", "company", "title"))]
        if len(hits) == 1:
            return hits[0]
    ps = _plat_start_ym(plat_item)
    if ps:
        for i, mi in enumerate(master_items):
            if _parse_master_years(mi.get("years")) == ps:
                return i
    # 顺序兜底：仅当无名称冲突时允许——两边名称都存在且完全不同，说明此位置
    # 对齐不可信（LLM 输出顺序常与平台现值不同），宁可放弃逐字覆盖（返回 None，
    # 上层跳过该条目）也不把 A 条目的正文错配覆盖到 B 条目上
    if idx < len(master_items):
        m_entry = master_items[idx]
        m_names = {str(m_entry.get(k) or "").strip() for k in ("name", "company", "title")} - {""}
        p_names = {str(plat_item.get(k) or "").strip()
                   for k in ("project_name", "proExpProjectName", "projectName", "name", "company", "title")} - {""}
        if m_names and p_names and m_names.isdisjoint(p_names):
            return None
        return idx
    return None


def _master_desc_text(entry: dict) -> str:
    """主简历条目描述 → 标准纯文本（多段数组按换行拼接，剥离 Markdown 符号）"""
    d = entry.get("description")
    if d is None:
        return ""
    if isinstance(d, list):
        text = "\n".join(str(x) for x in d)
    else:
        text = str(d)
    return md_to_plain_text(text)


# ============ Markdown 剥离 ============

_MD_INLINE_PATTERNS = (
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),            # **加粗** → 加粗
    (re.compile(r"~~(.+?)~~"), r"\1"),                # ~~删除线~~ → 内容
    (re.compile(r"`([^`]+)`"), r"\1"),                # `代码` → 代码
    (re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)"), r"\1"),  # ![alt](url) → alt
    (re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)"), r"\1"),   # [text](url) → text（URL 不保留）
    (re.compile(r"\*([^*\n]+?)\*"), r"\1"),           # *斜体* → 斜体（不成对 * 不误伤）
)


def md_to_plain_text(s) -> str:
    """
    剥离 Markdown 格式符号转为普通文本：
      - 行级：标题 #、无序列表 - /*/+、引用 > 删除符号；分隔线整行删除
      - 行内：**加粗**、*斜体*、`代码`、[文字](链接)、![alt](url)、~~删除线~~ → 仅保留文字内容
      - 空行：连续空行合并为至多一个空行；首尾空白去除
    对纯文本幂等（不含 Markdown 符号的文本原样返回），可安全用于 restore 路径。
    """
    if not isinstance(s, str):
        return s
    s = s.replace("\r\n", "\n")
    lines = []
    for raw in s.split("\n"):
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if re.fullmatch(r"[-*_]{3,}", line):
            continue  # 分隔线整行删除
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            line = m.group(2)
        else:
            m = re.match(r"^([-*+])\s+(.*)$", line)
            if m:
                line = m.group(2)
            elif line.startswith(">"):
                line = line.lstrip(">").strip()
        for pat, rep in _MD_INLINE_PATTERNS:
            line = pat.sub(rep, line)
        lines.append(line)
    merged = []
    prev_blank = False
    for line in lines:
        if not line:
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False
        merged.append(line)
    return "\n".join(merged).strip()


# 数组条目中除「正文」外的其他描述类自由文本 key（成果/职责等），同样剥离 Markdown
_EXTRA_STRIP_ITEM_KEYS = ("achievement", "achievements", "responsibilities", "proExpProjectDuty", "functionDescribe")


def _split_project_sections(text_or_lines) -> tuple[str, str, str]:
    """
    将主简历的项目经历 Markdown 文本/数组智能分流为三段（严格互斥、零重复）：
      1) description: 技术栈、项目链接、项目背景/介绍
      2) responsibilities: 核心贡献、项目职责、技术攻坚
      3) achievements: 业务成果、量化指标、项目业绩
    若文本无明确分段标记，则整体作为 description，其余为空。
    """
    if isinstance(text_or_lines, list):
        raw_text = "\n".join(str(x) for x in text_or_lines)
    else:
        raw_text = str(text_or_lines or "")

    clean_text = raw_text.replace("**", "").replace("__", "")
    lines = [ln.strip() for ln in clean_text.split("\n")]

    DUTY_KEYWORDS = (
        # 通用标题词
        "核心贡献", "核心架构", "架构设计", "架构与落地", "核心职责", "项目职责", "工作职责",
        "主要职责", "负责内容", "核心工作", "技术攻坚", "工作内容", "主要工作", "工作要点",
        "主要贡献", "个人职责", "主要负责",
        # ⚠️ 以下为当前用户简历的定制短语（换人/换简历后不再命中，退化为整体 description，
        # 不影响正确性——只是三段分流退化为单段；新简历出现新标题词时在此追加即可）
        "分析诊断与商业策略", "分析链路与核心动作",
        "核心架构与落地", "核心职责与技术亮点", "分析诊断与策略赋能"
    )
    ACH_KEYWORDS = (
        "业务成果", "项目业绩", "项目成果", "工作业绩", "价值产出", "关键指标", "成果亮点",
        "商业应用潜力", "收益", "项目收获", "MVP 验证成果", "MVP验证成果", "MVP 测试与价值推演",
        "MVP测试与价值推演", "项目价值沉淀", "项目价值", "成果与价值", "项目产出", "价值推演",
        "验证成果", "业务成果与项目价值"
    )
    DESC_KEYWORDS = (
        "项目背景", "项目简介", "项目介绍", "系统介绍", "技术栈", "核心技术栈", "项目描述",
        "背景", "关于项目", "项目概况", "项目目标", "项目链接", "核心工具", "GitHub"
    )

    current_sec = "desc"
    sections = {"desc": [], "resp": [], "ach": []}

    for ln in lines:
        if not ln:
            continue
        header_candidate = re.sub(r"^[#\-\*•\s:]+", "", ln).rstrip("：:").strip()
        matched_sec = None
        for kw in ACH_KEYWORDS:
            if header_candidate.startswith(kw) or header_candidate == kw:
                matched_sec = "ach"
                break
        if not matched_sec:
            for kw in DUTY_KEYWORDS:
                if header_candidate.startswith(kw) or header_candidate == kw:
                    matched_sec = "resp"
                    break
        if not matched_sec:
            for kw in DESC_KEYWORDS:
                if header_candidate.startswith(kw) or header_candidate == kw:
                    matched_sec = "desc"
                    break

        if matched_sec:
            current_sec = matched_sec
            # 用户规则（2026-08-30）：命中标题词的行整行原文保留——不再剥离
            # 「技术栈：/项目链接：」等开头词，也不再丢弃冒号后的短内容。
            # 任何基于关键词的删减都会误伤正文，映射对项目描述只做内容填充。
            sections[current_sec].append(ln)
            continue

        sections[current_sec].append(ln)

    desc_str = md_to_plain_text("\n".join(sections["desc"]).strip())
    resp_str = md_to_plain_text("\n".join(sections["resp"]).strip())
    ach_str = md_to_plain_text("\n".join(sections["ach"]).strip())

    if not resp_str and not ach_str:
        desc_str = md_to_plain_text(clean_text.strip())

    return desc_str, resp_str, ach_str


def _strip_markdown(report: dict, platform: str) -> dict:
    """
    报告字段 Markdown 剥离（生成与 restore 双路径执行，对纯文本幂等）：
      - 数组条目的描述正文（_VERBATIM_DESC_FIELD）+ 成果/职责类自由文本 → 剥离为纯文本
      - 字符串数组元素（certificates/skills 等）→ 逐元素剥离
      - 顶层标量字符串（排除 Translation 派生字段）→ 剥离
    """
    desc_fields = _VERBATIM_DESC_FIELD.get(platform, {})
    for f in report.get("fields", []):
        value = f.get("value")
        path = f.get("path")
        if f.get("type") == "array" and isinstance(value, list):
            desc_key = desc_fields.get(path)
            strip_keys = {desc_key} if desc_key else set()
            if path in ("work_experience", "projects", "education"):
                strip_keys.update(_EXTRA_STRIP_ITEM_KEYS)
            for it in value:
                if not isinstance(it, dict):
                    continue
                for k in strip_keys:
                    if isinstance(it.get(k), str):
                        it[k] = md_to_plain_text(it[k])
            if path in ("certificates", "skills"):
                for i, x in enumerate(value):
                    if isinstance(x, str):
                        value[i] = md_to_plain_text(x)
            continue
        if isinstance(value, str) and not str(path).endswith("Translation"):
            f["value"] = md_to_plain_text(value)
    return report


def _enforce_verbatim_description(report: dict, platform: str, master: dict) -> dict:
    """
    描述正文逐字照抄兜底（仅生成路径执行，restore 不执行以保护人工编辑）：
      - 主简历对应条目描述非空：平台值必须与原文逐字一致，不一致（LLM 丢段落/改写）→ 覆盖为原文 + warnings
      - 主简历对应条目描述为空：平台值若被 LLM 补写 → 清空 + warnings
    条目定位用 _match_master_index（名称 → 时间 → 顺序）。
    """
    field_map = _VERBATIM_DESC_FIELD.get(platform, {})
    comp_map = _VERBATIM_COMPANY_FIELD.get(platform, {})
    if not field_map and not comp_map:
        return report
    master_data = master.get("data") or {}
    warnings = list(report.get("warnings") or [])
    for f in report.get("fields", []):
        path = f.get("path")
        desc_key = field_map.get(path)
        comp_key = comp_map.get(path)
        if not desc_key and not comp_key:
            continue
        if f.get("type") != "array" or not isinstance(f.get("value"), list):
            continue
        if path == "projects":
            master_items = master_data.get("personalProjects") or master_data.get("projects") or []
        elif path == "work_experience":
            master_items = master_data.get("workExperience") or master_data.get("work_experience") or []
        else:
            master_items = master_data.get(_MASTER_SECTION.get(path, "")) or []
        if not isinstance(master_items, list) or not master_items:
            continue
        for idx, it in enumerate(f["value"]):
            if not isinstance(it, dict):
                continue
            mi = _match_master_index(master_items, it, idx)
            if mi is None:
                continue
            if desc_key:
                if platform == "liepin" and path == "projects":
                    # 猎聘项目经历专属三段分流：项目描述、项目职责、项目业绩严格互斥不重叠
                    desc_s, resp_s, ach_s = _split_project_sections(master_items[mi].get("description"))
                    it["description"] = desc_s
                    # 与 boss/通用分支一致：主简历无对应段时清空，不保留 LLM 补写内容（防幻觉残留）
                    it["responsibilities"] = resp_s if resp_s else ""
                    it["achievements"] = ach_s if ach_s else ""
                elif platform == "boss" and path == "projects":
                    # BOSS直聘项目经历专属两段分流：项目描述（背景+核心贡献）、项目业绩（成果产出）严格互斥不重叠
                    desc_s, resp_s, ach_s = _split_project_sections(master_items[mi].get("description"))
                    boss_desc = "\n\n".join([s for s in (desc_s, resp_s) if s]).strip()
                    it["project_description"] = boss_desc
                    if ach_s:
                        it["achievement"] = ach_s
                    else:
                        it["achievement"] = ""
                else:
                    original = _master_desc_text(master_items[mi])
                    cur = it.get(desc_key)
                    cur_str = cur if isinstance(cur, str) else ("" if cur is None else str(cur))
                    if original:
                        if cur_str != original:
                            it[desc_key] = original
                            warnings.append(f"{path} 第{idx + 1}条描述已按主简历原文完整恢复（LLM 输出与主简历不一致）")
                    else:
                        if cur_str:
                            it[desc_key] = ""
                            warnings.append(f"{path} 第{idx + 1}条主简历无描述，已清空 LLM 补写内容")
            if comp_key:
                mcomp = master_items[mi].get("company")
                mcomp_s = mcomp if isinstance(mcomp, str) else ("" if mcomp is None else str(mcomp))
                mcomp_s = mcomp_s.strip()
                ccur = it.get(comp_key)
                ccur_s = ccur if isinstance(ccur, str) else ("" if ccur is None else str(ccur))
                ccur_s = ccur_s.strip()
                m_start_ym = _parse_master_years(master_items[mi].get("years"))
                p_start_ym = _plat_start_ym(it)
                time_matched = bool(m_start_ym and p_start_ym and m_start_ym == p_start_ym)

                if mcomp_s and ccur_s != mcomp_s:
                    it[comp_key] = mcomp_s
                    warnings.append(f"{path} 第{idx + 1}条公司名已按主简历原文恢复（LLM 输出与主简历不一致）")
                elif not mcomp_s:
                    if time_matched and ccur_s:
                        # 工作时间完全一致且平台/LLM 现有有效公司名（如自由职业者），安全保留
                        pass
                    elif not time_matched and ccur_s:
                        # 时间不一致且主简历无公司名，清空误配内容
                        it[comp_key] = ""
                        warnings.append(f"{path} 第{idx + 1}条主简历无公司名且工作时间不匹配，已清空顶替内容")
    report["warnings"] = warnings
    return report


# 主简历工作经历条目内可能携带技能标签的字段名（飞书简历结构兼容多个命名）
_MASTER_ENTRY_SKILL_KEYS = ("skills", "skillTags", "skill_tags", "skillsList")

_COMMON_SKILL_KEYWORDS = [
    # AI / 大模型 / Agent
    "大模型", "LLM", "Prompt", "Prompt Engineering", "RAG", "Agent", "LangChain", "LangGraph",
    "NLP", "CV", "AIGC", "生成式AI", "智能客服", "客服训练", "意图识别", "向量数据库", "ChromaDB",
    # 编程语言 & 基础框架
    "Python", "Java", "Go", "Golang", "C++", "JavaScript", "TypeScript", "React", "Vue", "Next.js", "Node.js",
    "FastAPI", "Flask", "Django", "Spring Boot", "微服务", "RESTful API",
    # 数据库 & 缓存 & 中间件
    "SQL", "MySQL", "PostgreSQL", "Redis", "MongoDB", "Elasticsearch", "Kafka", "数仓", "数据中台",
    # 数据分析 & 治理 & 主数据
    "数据分析", "Pandas", "NumPy", "PyTorch", "TensorFlow", "数据建模", "数据治理", "主数据", "Master Data",
    # 运维 & AI开发工具
    "Docker", "Kubernetes", "K8s", "CI/CD", "Git", "Linux", "Cursor", "Claude",
    # 业务、运营、供应链与电商
    "产品经理", "项目管理", "电商运营", "多渠道运营", "用户运营", "活动运营", "供应链", "库存管理", "履约调度",
    "营销风控", "风控", "SKU管理", "SKU", "数据产品", "交叉验证", "对账", "跨系统协同", "自动化", "敏捷开发"
]


def _extract_work_skills(desc: str, title: str, max_count: int = 8) -> list:
    """从工作经历的职位与描述中自动提取核心技能关键词"""
    text = f"{title}\n{desc}"
    matched = []
    seen = set()
    for kw in _COMMON_SKILL_KEYWORDS:
        # \b 对词尾非字母数字的关键词（C++/Node.js/.NET）永不成立，改用 lookaround 边界
        pattern = r'(?i)(?<!\w)' + re.escape(kw) + r'(?!\w)' if kw.isascii() else re.escape(kw)
        if re.search(pattern, text):
            k_lower = kw.casefold()
            if k_lower not in seen:
                seen.add(k_lower)
                matched.append(kw)
                if len(matched) >= max_count:
                    break
    return matched


def _infer_work_type(company: str, title: str, desc: str) -> str:
    """
    智能推导 51job 工作经历的工作类型 (workType):
    '0': 全职, '1': 兼职/自由职业, '2': 实习
    """
    t = f"{company} {title} {desc}".lower()
    if "实习" in t or "intern" in t:
        return "2"
    if "兼职" in t or "part-time" in t or "自由职业" in t or "freelance" in t or "顾问" in title:
        return "1"
    return "0"


def _fallback_skills(report: dict, master: dict) -> dict:
    """
    工作经历技能兜底（用户需求：skills 是唯一让 agent 发挥提炼的字段，上限 6~8 个关键词）。
    LLM 未提炼出任何技能（空数组）时，若主简历对应工作经历条目自带技能字段
    （skills/skillTags 等），则沿用该条技能；若主简历也没有，从描述与职位自动提取兜底并写入 warning。
    支持 BOSS (work_experience) 与 51job (works)。
    """
    master_data = master.get("data") if (isinstance(master, dict) and "data" in master) else master
    if not isinstance(master_data, dict):
        master_data = {}
    master_items = master_data.get("workExperience") or master_data.get("work_experience") or []
    if not isinstance(master_items, list) or not master_items:
        return report
    warnings = list(report.get("warnings") or [])
    for f in report.get("fields", []):
        path = f.get("path")
        if path not in ("work_experience", "works") or f.get("type") != "array":
            continue
        if not isinstance(f.get("value"), list):
            continue
        for idx, it in enumerate(f["value"]):
            if not isinstance(it, dict):
                continue
            skills_val = it.get("skills") or it.get("workVocationalSkills")
            if skills_val and isinstance(skills_val, list) and len(skills_val) > 0:
                if not it.get("skills"):
                    it["skills"] = [s if isinstance(s, str) else (s.get("skill") or s.get("value") or "") for s in skills_val if s]
                if not it.get("workVocationalSkills"):
                    it["workVocationalSkills"] = it["skills"]
                continue
            mi = _match_master_index(master_items, it, idx)
            src = master_items[mi] if mi is not None else {}
            tags: list = []
            for k in _MASTER_ENTRY_SKILL_KEYS:
                v = src.get(k)
                if isinstance(v, list):
                    tags.extend(x for x in v if isinstance(x, str))
                elif isinstance(v, str) and v.strip():
                    tags.append(v)
            if not tags:
                desc = _clean_md(it.get("workDescription") or it.get("description") or it.get("content") or (src.get("description") if src else ""))
                pos = _clean_md(it.get("position") or it.get("title") or (src.get("title") if src else ""))
                tags = _extract_work_skills(desc, pos)
            tags = _clean_skill_tags(tags, max_count=6)
            if tags:
                it["skills"] = tags
                it["workVocationalSkills"] = tags
                warnings.append(f"{path} 第{idx + 1}条相关技能已自动提炼补充（{len(tags)}项: {','.join(tags[:4])}）")
    if warnings:
        report["warnings"] = warnings
    return report


# 期望职位分类型上限（用户需求：全职最多 3 组、兼职最多 1 组）
_EXPECTATION_FULLTIME_MAX = 3
_EXPECTATION_PARTTIME_MAX = 1


def _trim_expectations(report: dict) -> dict:
    """
    期望职位分类型裁剪（用户需求的后端兜底，防 LLM/历史数据超限）：
      - 仅对条目含 jobType 字段的平台生效（如 BOSS；猎聘/智联/前程无忧无 jobType，不裁剪）
      - 全职（jobType≠parttime）保留前 3 条、兼职保留前 1 条（按原顺序），超出条目裁剪
      - 有裁剪时写入 warning 提示
    生成与恢复双路径都执行（前端新增/编辑入口另有同规则校验，此处为数据层最后防线）。
    """
    warnings = list(report.get("warnings") or [])
    for f in report.get("fields", []):
        if f.get("path") != "expectations" or not isinstance(f.get("value"), list):
            continue
        items = f["value"]
        # 平台条目无 jobType 字段（非 BOSS 类结构）→ 不适用类型上限，原样保留
        if not any(isinstance(it, dict) and "jobType" in it for it in items):
            continue
        full_n = part_n = dropped = 0
        kept = []
        for it in items:
            if not isinstance(it, dict):
                kept.append(it)
                continue
            if (it.get("jobType") or "fulltime") == "parttime":
                if part_n < _EXPECTATION_PARTTIME_MAX:
                    part_n += 1
                    kept.append(it)
                else:
                    dropped += 1
            else:
                if full_n < _EXPECTATION_FULLTIME_MAX:
                    full_n += 1
                    kept.append(it)
                else:
                    dropped += 1
        if dropped:
            f["value"] = kept
            warnings.append(f"expectations 超出类型上限（全职最多 {_EXPECTATION_FULLTIME_MAX} 组、兼职最多 {_EXPECTATION_PARTTIME_MAX} 组），已裁剪 {dropped} 条超出条目")
    if warnings:
        report["warnings"] = warnings
    return report


def _fallback_expectations(report: dict, fields_data: dict, selected_modules: list[str] | None = None) -> dict:
    """
    期望职位兜底（与 _fallback_certificates 同模式）：LLM 输出空数组时
    （主简历无求职意向线索，违反规则 4d 擅自清空）自动沿用平台现有值
    （*_fields.json 的 expectations.current_value），避免用户已在平台填好
    的期望职位被清空。生成与恢复双路径都执行；回填后同步移除 unfilled 中
    对应条目（字段已有值，不再是待人工）。平台现有值也为空时保持空数组不动。
    """
    if selected_modules is not None and "expectations" not in selected_modules:
        return report
    existing = get_path(fields_data, "expectations")
    existing = [dict(it) for it in existing if isinstance(it, dict)] if isinstance(existing, list) else []
    filled = False
    for f in report.get("fields", []):
        if f.get("path") != "expectations":
            continue
        if isinstance(f.get("value"), list) and f["value"]:
            # 实质空判定（用户案例 2026-08-30）：LLM 输出仅带 jobType 等默认标记、
            # 无职位/城市/薪资的空壳条目时，视为「主简历未提供」，照旧沿用平台现有值，
            # 不让空壳覆盖平台已填的期望
            if not all(_is_item_empty(it, ignore_keys=True) for it in f["value"]):
                return report  # 条目带实质内容，原样保留
            # 全部条目都是空壳：平台有值则沿用；平台也无值则清空空壳（LLM 凭空编造的
            # 「全职」空期望不应新增到官网）
            if not existing:
                f["value"] = []
                return report
        if not existing:
            return report  # 平台也无现有值 → 保持现状，unfilled 留给用户手动新增
        f["value"] = [dict(it) for it in existing]
        f["confidence"] = "low"
        f["source"] = "platform-existing"
        note = "主简历无求职意向线索，沿用平台现有期望职位（未经 LLM 改动）"
        f["note"] = (f.get("note") + "；" + note) if f.get("note") else note
        filled = True
        break
    if not filled:
        # expectations 完全未映射且平台有现有值 → 追加低置信条目
        if not existing:
            return report
        report.setdefault("fields", []).append({
            "path": "expectations",
            "value": [dict(it) for it in existing],
            "confidence": "low",
            "source": "platform-existing",
            "note": "主简历无求职意向线索，沿用平台现有期望职位（未经 LLM 改动）",
            "type": "array",
        })
    # 回填成功：移除 unfilled 中的 expectations（已有值不再是待人工），并加 warning
    report["unfilled"] = [u for u in report.get("unfilled", []) if u.get("path") != "expectations"]
    warnings = list(report.get("warnings") or [])
    warnings.append("expectations：主简历无求职意向线索，已沿用平台现有值（未经 LLM 改动），建议人工核对")
    report["warnings"] = warnings
    return report


def _sort_array_items_by_start_desc(report: dict) -> dict:
    """
    工作经历/项目经历按起始年月倒序稳定排序（最新在前，与平台展示习惯一致）。
    仅生成路径调用；restore 不调用，避免打乱用户手动调整过的顺序。
    无时间信息的条目保持原相对顺序排末尾。
    """
    for f in report.get("fields", []):
        if f.get("type") != "array" or f.get("path") not in ("work_experience", "projects"):
            continue
        if not isinstance(f.get("value"), list):
            continue
        items = [it for it in f["value"] if isinstance(it, dict)]
        rest = [it for it in f["value"] if not isinstance(it, dict)]

        def _key(it: dict):
            return _plat_start_ym(it) or (0, 0)

        items.sort(key=_key, reverse=True)
        f["value"] = items + rest
    return report


def _clean_skill_tags(values, max_count: int = 6) -> list:
    """
    技能标签清洗（用户需求：skills 是唯一让 agent 发挥提炼的字段，上限 6 个关键词）：
      - 元素转字符串、去首尾空白；None/空串/纯标点丢弃
      - 疑似整句（>40 字符）丢弃，保证是关键词
      - 去重（大小写不敏感，保留首个出现的形式）后按原顺序输出
      - 最多保留 max_count 个（默认 6 个）
    """
    out: list = []
    seen: set = set()
    for x in values:
        if x is None:
            continue
        s = str(x).strip()
        if not s or not any(c.isalnum() for c in s):  # 纯标点/符号
            continue
        if len(s) > 40:  # 疑似整句而非关键词
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= max_count:
            break
    return out


def _normalize_array_items(report: dict) -> dict:
    """
    数组条目规范化（生成后与恢复时都执行，保证条目字段类型稳定）：
      - hideResume（布尔）：'' / null → False；'true'/'false' 字符串 → 布尔
      - skills（技能数组，仅 work_experience 拥有）：缺省补空数组；字符串聚合串（"python、sql"）→ 拆数组清洗；
        其他数组字段（projects/education 等）条目内残留的 skills 键一律删除（平台无此字段，含 LLM 输出与旧报告残留）
      - startMonth/endMonth：'04' → '4'（与平台存量数据一致，前端下拉无前导零）
    返回处理后的报告 dict（就地修改 value 条目）。
    """
    for f in report.get("fields", []):
        # 顶层 yearmonth 标量（出生年月/参加工作时间）：'1996-04' → '1996-4'
        if f.get("path") in ("birth_month", "work_start_date"):
            f["value"] = _normalize_month_value(f["value"])
        # certificates（字符串数组）：元素聚合串（"CET-6、普通话"）按顿号/逗号拆分去重
        if f.get("path") == "certificates" and isinstance(f.get("value"), list):
            flat = []
            for x in f["value"]:
                if isinstance(x, str):
                    for p in re.split(r"[、,，;；]", x):
                        p = p.strip()
                        if p and p not in flat:
                            flat.append(p)
                elif x not in (None, "") and str(x) not in flat:
                    flat.append(str(x))
            f["value"] = flat
        # 专业技能/技能标签（字符串数组或对象数组）：过滤掉空项
        if f.get("path") in ("skill_tags", "professionalSkills", "skills") and isinstance(f.get("value"), list):
            clean_skills = []
            for it in f["value"]:
                if isinstance(it, str) and it.strip():
                    clean_skills.append(it.strip())
                elif isinstance(it, dict):
                    name = str(it.get("proskillName") or it.get("name") or it.get("skill") or "").strip()
                    if name:
                        clean_skills.append(it)
            if clean_skills:
                f["value"] = clean_skills
        if f.get("type") != "array" or not isinstance(f.get("value"), list):
            continue
        for it in f["value"]:
            if not isinstance(it, dict):
                continue
            if "hideResume" in it:
                v = it["hideResume"]
                if isinstance(v, str):
                    it["hideResume"] = v.strip().lower() in ("true", "1", "yes")
                elif v is None:
                    it["hideResume"] = False
            if f.get("path") in ("work_experience", "works"):
                # 技能标签处理
                raw_skills = it.get("skills") or it.get("workVocationalSkills") or []
                if isinstance(raw_skills, str):
                    clean_s = _clean_skill_tags(re.split(r"[、,，;；]", raw_skills)) if raw_skills.strip() else []
                elif isinstance(raw_skills, list):
                    clean_s = _clean_skill_tags([
                        (s if isinstance(s, str) else (s.get("skill") or s.get("value") or ""))
                        for s in raw_skills if s
                    ])
                elif raw_skills not in (None, ""):
                    clean_s = _clean_skill_tags([str(raw_skills)])
                else:
                    clean_s = []
                it["skills"] = clean_s
                if f.get("path") == "works":
                    it["workVocationalSkills"] = clean_s
                    # 工作类型规范化
                    wt = str(it.get("workType") or it.get("seekType") or "0").strip()
                    it["workType"] = wt if wt in ("0", "1", "2") else "0"
                    it["seekType"] = it["workType"]
            elif "skills" in it:
                # 非工作经历数组字段（projects/education 等）无技能字段：删除残留（LLM 输出/旧报告）
                del it["skills"]
            # 月份归一化：'04' → '4'（LLM 可能输出带前导零，平台存量数据无前导零）
            for mkey in ("startMonth", "endMonth"):
                if mkey in it:
                    it[mkey] = _normalize_month_value(it[mkey])
    return report


def _normalize_object_fields(report: dict) -> dict:
    """
    object 字段值规范化（生成后与恢复时都执行）：
      - overseas.allowView（布尔）：字符串 "yes"/"no"/"true"/"false" → 布尔；null → False
    返回处理后的报告 dict（就地修改 value）。
    """
    for f in report.get("fields", []):
        if not isinstance(f.get("value"), dict):
            continue
        v = f["value"]
        if "allowView" in v:
            av = v["allowView"]
            if isinstance(av, str):
                v["allowView"] = av.strip().lower() in ("true", "1", "yes")
            elif av is None:
                v["allowView"] = False
        if "hideResume" in v:
            hr = v["hideResume"]
            if isinstance(hr, str):
                v["hideResume"] = hr.strip().lower() in ("true", "1", "yes")
            elif hr is None:
                v["hideResume"] = False
    return report


def _fallback_certificates(report: dict, fields_data: dict, selected_modules: list[str] | None = None) -> dict:
    """
    资格证书兜底（用户需求）：LLM 未能给出证书（未映射/空数组/格式异常）时，
    自动沿用平台现有值，避免丢失用户已填写的证书数据。
    平台也没有证书时仍保留空数组字段（带 options），保证报告里始终有
    「资格证书」模块，用户可手动新增（与期望职位模块逻辑一致）。
    """
    if selected_modules is not None and "certificates" not in selected_modules:
        return report
    cert_keys = ("certificates", "certificate", "certifications")
    has_cert_module = any(k in (fields_data or {}) for k in cert_keys)
    if not has_cert_module:
        return report

    existing = None
    for k in cert_keys:
        if k in (fields_data or {}):
            val = get_path(fields_data, k)
            if val not in (None, "", [], {}):
                existing = val
                break
    if existing is None:
        existing = []

    # 规范化 existing 副本（保证不破坏 dict 结构，也不产生 repr 乱码）
    import copy
    if isinstance(existing, list):
        if existing and isinstance(existing[0], dict):
            existing_copy = copy.deepcopy(existing)
        else:
            existing_copy = [str(x) for x in existing if x not in (None, "")]
    else:
        existing_copy = [str(existing)] if existing not in (None, "") else []

    for f in report.get("fields", []):
        if f.get("path") not in cert_keys:
            continue
        val = f.get("value")
        if isinstance(val, list) and val and not _is_wholly_empty(val):
            # 如果 LLM 给出了有效证书（且不是乱码 repr 字符串），保留映射结果
            if not any(isinstance(x, str) and x.strip().startswith("{") for x in val):
                return report
        f["value"] = copy.deepcopy(existing_copy)
        f["confidence"] = "low"
        f["source"] = f.get("source") or ("platform-existing" if existing_copy else "")
        f["note"] = (f.get("note") or "") + ("；" if f.get("note") else "") + (
            "主简历无证书信息，沿用平台现有值" if existing_copy else "主简历无证书信息，可在报告里手动新增"
        )
        return report

    # certificates 完全没映射 → 追加为低置信条目（平台无证书时也保留空数组，保证模块可手动新增）
    report["fields"].append({
        "path": "certificates",
        "value": copy.deepcopy(existing_copy),
        "confidence": "low",
        "source": "platform-existing" if existing_copy else "",
        "note": "主简历无证书信息，沿用平台现有值" if existing_copy else "主简历无证书信息，可在报告里手动新增",
        "type": "array",
    })
    return report


# ============ 空值保护（主简历未提及 → 保留官网原值 + 警告） ============

# 平台 → 空值保护配置：映射后这些字段为空时自动兜底/警告
#   arrays: {数组path: [条目key...]} —— 条目级字段（work_experience 等）
#   string_arrays: [数组path...] —— 字符串数组整体（certificates）
_PLATFORM_EMPTY_FIELDS = {
    "liepin": {
        "arrays": {
            "work_experience": ["company", "position", "industry", "work_city", "department", "job_category", "start_date", "end_date"],
            "expectations": ["position", "city", "industries", "salary_min", "salary_max"],
            "education": ["school", "degree", "major", "start_date", "end_date"],
        },
        "string_arrays": ["certificates"],
    },
    "zhilian": {
        "arrays": {
            "work_experience": ["companyName", "jobTitle", "startDate", "endDate", "workDesc", "industry"],
            "projects": ["affiliatedCompany", "proExpStartDate", "proExpEndDate", "proExpProjectDesc"],
            "education": ["eduStartDate", "eduEndDate"],
        },
        "string_arrays": [],
    },
    "51job": {
        "arrays": {
            "works": ["companyName", "position", "startTime", "endTime", "workDescription"],
            "projects": ["projectName", "startTime", "endTime", "describe"],
            "educations": ["schoolName", "startTime", "endTime", "major"],
        },
        "string_arrays": [],
    },
    "boss": {
        "arrays": {
            "work_experience": ["company", "position", "startYear", "endYear", "content"],
            "projects": ["project_name", "startYear", "endYear", "project_description"],
            "education": ["school", "degree", "startYear", "endYear", "major"],
            # expectations 曾漏配（用户案例 2026-08-30）：主简历无期望时空壳条目覆盖了
            # 平台已填期望——补齐后数组基底合并同样保护求职期望
            "expectations": ["jobType", "position", "city", "otherCities", "salary", "industries"],
        },
        "string_arrays": [],
    },
}

# 平台 → 意向/选项类保护模块：LLM 整体置空（主简历未提及）时不应覆盖平台原值，
# 而是移除该 field（保留原值）并转入 unfilled 提醒人工核对。
# 键为模块 root 键（path 精确值或 path 的顶层段），匹配逻辑见 _protect_unmentioned_modules。
_UNMENTIONED_PROTECT_MODULES = {
    "zhilian": ["wanna", "job_status", "language", "certificate", "certificates", "training", "skill_tags"],
    "51job": ["intentions", "language", "certifications", "certificates", "personalSkills", "skills"],
    "boss": ["expectations", "certificates", "certificate"],
    "liepin": ["languages", "certificates", "certificate", "skill_tags"],
}


def _is_empty_value(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ""
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def _norm_ym_key(v):
    """日期归一为 'YYYY-MM'：兼容 '2023.09'/'2023/09'/'2023-09'/'202309'/
    '至今'等形态；LLM 映射输出与平台采集格式可能不一致，比对前必须归一。"""
    if not v:
        return ""
    s = str(v).strip()
    if "至今" in s or "现在" in s:
        return "至今"
    s = s.replace("/", "-").replace(".", "-").replace("年", "-").replace("月", "")
    parts = [p for p in s.split("-") if p]
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}-{int(parts[1]):02d}"
    if len(s) == 6 and s.isdigit():
        return f"{s[:4]}-{s[4:]}"
    return s


def _entry_start_ym(item: dict) -> str:
    """提取数组条目的开始年月并归一为可比形态（兼容四平台条目键名/格式）：
    liepin=start_date("2020/01")、boss=startYear/startMonth、51job=startTime("2014.09")、
    zhilian 结构化=startDate 毫秒时间戳 / startDateFormat。"""
    if not isinstance(item, dict):
        return ""
    # 智联结构化：毫秒时间戳
    ts = item.get("startDate")
    if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.strip().isdigit() and len(ts.strip()) >= 12):
        try:
            from datetime import datetime
            dt = datetime.fromtimestamp(float(ts) / 1000)
            return f"{dt.year}-{dt.month:02d}"
        except Exception:
            pass
    for k in ("start_date", "startDateFormat", "startDate", "startTime"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return _norm_ym_key(v)
    sy, sm = item.get("startYear"), item.get("startMonth")
    if sy:
        return _norm_ym_key(f"{sy}-{sm}" if sm else str(sy))
    return ""


def _match_platform_entry(platform_items: list, item: dict, idx: int) -> dict | None:
    """
    匹配平台现有条目：
    - 条目可提取开始时间（四平台键名均兼容，见 _entry_start_ym）→ 只按开始时间精确匹配
      （归一后比较，容忍分隔符差异），不匹配视为新条目（返回 None，避免把平台已有
      条目的值错配给主简历新增条目）
    - 无法提取时间字段的数组（如 expectations）→ 退化为索引顺序
    """
    sd_n = _entry_start_ym(item)
    if sd_n:
        for p in platform_items:
            if _entry_start_ym(p) == sd_n:
                return p
        return None
    return platform_items[idx] if 0 <= idx < len(platform_items) else None


def _preserve_empty_platform_values(report: dict, fields_data: dict, platform: str) -> dict:
    """
    空值保护（用户需求）：主简历未详细提及的字段保留平台官网采集的原始值。
    - 数组条目：按 start_date 匹配平台现有条目后整条合并 —— 平台条目为基底
      （主简历未提及的字段，含平台独有 key，全部保留官网原值），映射值非空则覆盖。
      保护列表内 key 映射后为空：平台该 key 非空 → 回填官网原值 + 警告「已保留官网原值」；
      平台原值也为空 → 留空 + 警告「需人工填写」。
    - 字符串数组（certificates）映射后为空：平台非空 → 回填 + 警告；平台空 → 警告人工确认。
    仅对 _PLATFORM_EMPTY_FIELDS 配置的平台生效（四平台均已配置启用）。
    生成与恢复双路径都执行（值已回填后幂等，不重复生成警告）。
    """
    cfg = _PLATFORM_EMPTY_FIELDS.get(platform)
    if not cfg:
        return report
    warnings = list(report.get("warnings") or [])
    arrays_cfg = cfg.get("arrays") or {}
    for f in report.get("fields", []):
        path = f.get("path")
        if path in arrays_cfg:
            keys = arrays_cfg[path]
            items = f.get("value")
            if not isinstance(items, list):
                continue
            platform_items = get_path(fields_data, path)
            platform_items = [it for it in (platform_items or []) if isinstance(it, dict)]
            kept_items = []
            dropped_shells = 0
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    kept_items.append(item)
                    continue
                # 实质空壳条目剔除（用户案例 2026-08-30）：仅带 jobType 等默认标记、
                # 无任何实质内容的条目不作为「新增」推上官网
                if _is_item_empty(item, ignore_keys=True):
                    dropped_shells += 1
                    continue
                label = item.get("company") or item.get("position") or item.get("school") or f"第{i + 1}条"
                pm = _match_platform_entry(platform_items, item, i)
                raw = dict(item)  # 合并前的映射原始值（用于空值判断）
                if pm is not None:
                    # 整条合并：平台条目为基底（未提及字段保留官网原值），映射非空值覆盖
                    merged = dict(pm)
                    for k, v in raw.items():
                        if not _is_empty_value(v):
                            merged[k] = v
                    item.clear()
                    item.update(merged)
                for key in keys:
                    v = raw.get(key)
                    if not _is_empty_value(v):
                        continue
                    pv = pm.get(key) if pm else None
                    if not _is_empty_value(pv):
                        warnings.append(
                            f"{path}第{i + 1}条（{label}）{key}字段主简历未提供，已保留官网原值「{pv}」，建议人工核对"
                        )
                    else:
                        # 幂等：平台无值且该 key 已存在于条目中（保护合并过的旧条目，恢复路径重跑）
                        # → 不重复生成「需人工填写」警告（同一条目第二次执行不新增）
                        if pm is not None and key in item:
                            continue
                        warnings.append(
                            f"{path}第{i + 1}条（{label}）{key}字段为空（主简历未提供），需人工填写"
                        )
                kept_items.append(item)
            if dropped_shells:
                f["value"] = kept_items
                warnings.append(
                    f"{path}：{dropped_shells} 个仅含默认标记的空壳条目已移除（主简历未提供实质内容，不写入官网）"
                )
        elif path in (cfg.get("string_arrays") or []):
            if _is_empty_value(f.get("value")):
                existing = get_path(fields_data, path)
                existing = [str(x) for x in (existing or []) if str(x)]
                if existing:
                    f["value"] = existing
                    f["confidence"] = "low"
                    f["source"] = "platform-existing"
                    warnings.append(f"{path}：主简历未明确提及，已保留官网现有值，需人工确认")
                else:
                    warnings.append(f"{path}：主简历未明确提及，输出空数组需人工确认")
        else:
            # 标量字段空值保护（用户需求 2026-08-30，修复 birth_month/wechat 被清空的缺陷）：
            # 主简历未提供 → LLM 可能输出空串，原守卫只覆盖数组/字符串数组两类，
            # 标量在此兜底：采集原值非空则一律回填原值，绝不因映射丢失平台已有内容。
            if not _is_empty_value(f.get("value")):
                continue
            pv = get_path(fields_data, path)
            if _is_empty_value(pv):
                continue
            f["value"] = pv
            f["confidence"] = "low"
            f["source"] = "platform-existing"
            warnings.append(f"{path}：主简历未提供，已保留平台采集原值「{str(pv)[:40]}」，需人工核对")
    if warnings:
        report["warnings"] = warnings
    return report


# 判断「未提及」时忽略的默认值/派生字段：这些字段非空不代表主简历提供了该模块信息
# （如 LLM 会把求职意向的工作性质默认填「全职」；*Translation 是枚举值自带的翻译派生字段）。
# jobType 同理（用户案例 2026-08-30）：LLM 对主简历无期望时输出 {"jobType": "fulltime", ...}
# 空壳条目，曾骗过「整体全空」检查把平台已填期望覆盖成空壳——jobType 必须视为默认标记。
_PROTECT_IGNORE_KEYS = {"preferredJobNature", "jobType"}


def _is_ignored_key(k) -> bool:
    return k in _PROTECT_IGNORE_KEYS or str(k).endswith("Translation")


def _is_item_empty(item, ignore_keys=False) -> bool:
    """单个数组条目是否全空（dict 所有值空 / 非 dict 则直接判空）
    ignore_keys=True 时忽略默认值/翻译字段，只看主简历真正填写的字段"""
    if not isinstance(item, dict):
        return _is_empty_value(item)
    for k, v in item.items():
        if ignore_keys and _is_ignored_key(k):
            continue
        if not _is_empty_value(v):
            return False
    return True


def _is_wholly_empty(value, ignore_keys=False) -> bool:
    """映射值是否整体全空：空字符串/空列表/空dict，或非空列表但所有条目全空
    ignore_keys=True 时忽略默认值/翻译字段"""
    if _is_empty_value(value):
        return True
    if isinstance(value, list):
        return all(_is_item_empty(it, ignore_keys) for it in value)
    if isinstance(value, dict):
        return all(_is_empty_value(v) for k, v in value.items()
                   if not (ignore_keys and _is_ignored_key(k)))
    return False


def _protect_unmentioned_modules(report: dict, fields_data: dict, platform: str, selected_modules: list[str] | None = None) -> dict:
    """
    未提及模块保护（治本清空问题）：对配置的意向/选项类模块，若 LLM 映射值整体全空
    且平台现有值非空，则移除该 field（不覆盖、保留官网原值），并转入 unfilled + 警告
    提醒人工核对。与 51job 把无意向转 unfilled 的体验对齐。
    生成与恢复双路径都执行（平台原值已被清空时不触发，幂等）。
    """
    mods = _UNMENTIONED_PROTECT_MODULES.get(platform)
    if not mods:
        return report
    warnings = list(report.get("warnings") or [])
    unfilled = list(report.get("unfilled") or [])
    new_fields = []
    for f in report.get("fields", []):
        path = f.get("path")
        if selected_modules is not None and _field_path_to_module(path) not in selected_modules:
            continue
        is_empty = _is_wholly_empty(f.get("value"), ignore_keys=True)
        path_root = str(path or "").split(".")[0]
        in_protected = path in mods or path_root in mods or any(m in path for m in ("certificate", "certification"))
        # 证书低置信不再静默丢弃：仅当映射值整体为空时才移除回填平台原值；
        # low 置信但非空时保留映射结果并追加人工核对警告
        is_low_cert = (path in ("certificates", "certificate", "certifications") and f.get("confidence") == "low")
        if in_protected and is_empty:
            existing = get_path(fields_data, path)
            if existing not in (None, "", [], {}) and not _is_wholly_empty(existing):
                # 清理 LLM 对该模块的「留空/需人工补充」旧警告，避免与「已保留」提示矛盾
                warnings = [w for w in warnings if not (path in w and ("需人工补充" in w or "留空" in w))]
                label = "获得证书" if path in ("certificates", "certificate", "certifications") else path
                if not any(u.get("path") in (path, "certificates", "certificate", "certifications") for u in unfilled):
                    unfilled.append({"path": path, "label": label, "reason": "主简历未提供该模块信息，已自动保留平台现有值，请人工核对补充"})
                warnings.append(f"{path}：主简历未提供，已保留平台现有值（不覆盖），请人工核对")
                continue
        elif in_protected and is_low_cert:
            warnings.append(f"{path}：主简历匹配置信度较低，请人工核对证书内容")
        new_fields.append(f)
    report["fields"] = new_fields
    report["unfilled"] = unfilled
    if warnings:
        report["warnings"] = warnings
    return report


# ============ 模块标题语义归一（思考能力） ============

# 标准模块同义词表：用户自定义标题的常见别名 -> 标准 key（确定性快路径，零成本）
_MODULE_TITLE_SYNONYMS = {
    "summary": ["个人总结", "自我评价", "个人优势", "个人陈述", "自我陈述", "自我介绍",
                "个人简介", "自我简介", "总结", "摘要", "summary", "profile", "about"],
    "technicalSkills": ["专业技能", "专业技能与特长", "技能特长", "技术栈", "技能", "skills"],
    "workExperience": ["工作经历", "工作经验", "职业经历", "实习经历", "work experience"],
    "personalProjects": ["项目经历", "项目经验", "个人项目", "projects"],
    "education": ["教育背景", "教育经历", "学历", "education"],
    "languages": ["语言能力", "外语能力", "语言", "languages"],
    "certificates": ["资格证书", "证书", "certificates"],
}

# 经验积累：LLM 语义判定结果持久化，同一标题下次不再询问
_SECTION_ALIAS_CACHE_PATH = os.path.join(DATA_DIR, "section_title_aliases.json")


def _load_section_aliases() -> dict:
    try:
        with open(_SECTION_ALIAS_CACHE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_section_aliases(aliases: dict):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_SECTION_ALIAS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(aliases, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("别名积累表写入失败: %s", e)


def _match_module_title(title, aliases=None):
    """模块标题 -> 标准 key 的确定性匹配：积累经验优先，其次同义词表（双向包含）；未命中返回 None"""
    t = str(title or "").strip().lower()
    if not t:
        return None
    if aliases is None:
        aliases = _load_section_aliases()
    if t in aliases:  # 经验积累（含「不属于任何标准模块」的 null 判定）
        return aliases[t] or None
    for key, syns in _MODULE_TITLE_SYNONYMS.items():
        for s in syns:
            s = s.lower()
            if s and (s == t or s in t or t in s):
                return key
    return None


def _llm_classify_titles(titles: list, cfg: dict = None) -> dict:
    """思考能力：同义词表未命中时，让 LLM 一次性语义判定标题归属哪个标准模块。
    返回 {title_lower: 标准key | None}；LLM 不可用返回 {}（降级为纯同义词表）。"""
    cfg = cfg if cfg is not None else load_env_config()
    if not cfg.get("OPENAI_API_KEY") or not titles:
        return {}
    keys_desc = "\n".join(f"- {k}: 如 {' / '.join(v[:4])} 等" for k, v in _MODULE_TITLE_SYNONYMS.items())
    prompt = f"""你是简历结构分析专家。判断下列简历板块标题语义上属于哪个标准模块。

标准模块：
{keys_desc}

判断标准：按标题语义归类，而非逐字匹配（如「个人陈述」「关于我」都属 summary）；不属于任何标准模块（如 志愿者经历/驻外选项/兴趣爱好）输出 null。

板块标题：{json.dumps(titles, ensure_ascii=False)}

只输出纯 JSON 对象：{{"标题": "标准key或null", ...}}"""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=cfg["OPENAI_API_KEY"], base_url=cfg.get("OPENAI_BASE_URL") or None, timeout=45.0)
        resp = client.chat.completions.create(
            model=cfg.get("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = (resp.choices[0].message.content or "").strip()
        m = re.search(r"\{[\s\S]*\}", content)
        parsed = json.loads(m.group()) if m else {}
        low_titles = {str(t).strip().lower() for t in titles}
        out = {}
        for k, v in parsed.items():
            lk = str(k).strip().lower()
            if lk in low_titles:
                out[lk] = v if v in _MODULE_TITLE_SYNONYMS else None
        return out
    except Exception as e:
        logger.warning("LLM 标题语义判定失败（降级同义词表）: %s", e)
        return {}


def _parse_md_sections(markdown: str) -> list:
    """Markdown 按一级标题（# ）切分为 [(title, content)]"""
    if not markdown:
        return []
    out = []
    for sec in re.split(r"(?m)(?=^#[^#\n])", markdown):
        lines = sec.strip().splitlines()
        if not lines:
            continue
        title = re.sub(r"^#\s*", "", lines[0].strip())
        content = "\n".join(lines[1:]).strip()
        if title and content:
            out.append((title, content))
    return out


def _normalize_master_modules(data: dict, markdown: str, cfg: dict = None) -> dict:
    """模块归一（思考能力）：结构化数据标准模块为空时，按板块标题语义
    （同义词表 → LLM 判定 → 别名积累）从「简历内容」Markdown 回填。
    只填空不覆盖非空值；救用户改名标题的存量记录（如「个人陈述」）。
    """
    if not isinstance(data, dict) or not markdown:
        return data
    sections = _parse_md_sections(markdown)
    if not sections:
        return data
    aliases = _load_section_aliases()
    plan = []   # [(std_key, title, content)]
    unknown = []
    for title, content in sections:
        lt = str(title).strip().lower()
        key = _match_module_title(title, aliases)
        if key:
            plan.append((key, title, content))
        elif lt not in aliases:  # 同义词表未命中且无积累 → 待 LLM 判定
            unknown.append(title)
    if unknown:
        judged = _llm_classify_titles(unknown, cfg)
        if judged:
            aliases.update(judged)
            _save_section_aliases(aliases)
            for title, content in sections:
                lk = str(title).strip().lower()
                if judged.get(lk):
                    plan.append((judged[lk], title, content))

    def _is_empty_module(key):
        if key == "technicalSkills":
            return not ((data.get("additional") or {}).get("technicalSkills") or [])
        v = data.get(key)
        return v is None or v == "" or v == []

    filled = []
    for key, title, content in plan:
        if not _is_empty_module(key):
            continue
        if key == "technicalSkills":
            data.setdefault("additional", {})["technicalSkills"] = [
                ln.strip() for ln in re.split(r"[\n;；]+", content) if ln.strip()
            ]
        else:
            data[key] = content
        data.setdefault("moduleTitles", {}).setdefault(key, title)  # 记录用户实际标题
        filled.append(f"{title}->{key}")
    if filled:
        logger.info("模块语义归一回填: %s", ', '.join(filled))
    return data


# 平台自述文本字段（主简历 summary 应覆盖的目标）
_PLATFORM_SELF_TEXT_PATH = {
    "boss": "personal_advantage",
    "liepin": "self_assessment",
    "zhilian": "self_evaluation",
    "51job": "self_introduction.selfIntroduction",
}

# 全平台文本字段字数上限字典（与各平台官网在线简历 1:1 严格对齐）
PLATFORM_TEXT_LIMITS = {
    "zhilian": {
        "self_evaluation": 500,
        "self_introduction": 500,
        "workDesc": 2000,
        "workDescription": 2000,
        "proExpProjectDesc": 2000,
        "proExpProjectDuty": 2000,
        "trainDesc": 1000,
    },
    "51job": {
        "selfIntroduction": 500,
        "self_introduction.selfIntroduction": 500,
        "workDescription": 2000,
        "describe": 2000,
    },
    "boss": {
        "personal_advantage": 1000,
        "work_description": 3000,
        "performance": 3000,
        "project_description": 3000,
    },
    "liepin": {
        "self_assessment": 1000,
        "responsibilities": 2000,
        "description": 1000,
    }
}


def _check_field_length_limits(report: dict, platform: str) -> dict:
    """
    全平台字段字数上限硬性扫描与多级强预警：
    检查标量文本与数组条目文本是否超出目标平台字数上限。
    超限时绝不静默截断，而是在 report.warnings 和 field 条目中显著标记超限字数与精简警告，
    告知用户必须在表单中删减后方可正常回写。
    """
    limits = PLATFORM_TEXT_LIMITS.get(platform, {})
    if not limits:
        return report

    warnings = report.setdefault("warnings", [])
    module_name_map = {
        "work_experience": "工作经历",
        "works": "工作经历",
        "workExperience": "工作经历",
        "projects": "项目经历",
        "project": "项目经历",
        "projectExperience": "项目经历",
        "education": "教育经历",
        "educations": "教育经历",
        "training": "培训经历",
        "self_evaluation": "自我评价",
        "personal_advantage": "个人优势",
        "self_assessment": "自我评价",
        "self_introduction": "个人优势",
    }
    field_label_map = {
        "proExpProjectDesc": "项目描述",
        "proExpProjectDuty": "项目职责",
        "workDesc": "工作内容/描述",
        "workDescription": "工作内容/描述",
        "describe": "项目描述",
        "project_description": "项目描述",
        "performance": "项目业绩",
        "responsibilities": "工作职责",
        "description": "项目描述",
        "trainDesc": "培训描述",
        "self_evaluation": "自我评价",
        "personal_advantage": "个人优势",
        "self_assessment": "自我评价",
        "selfIntroduction": "自我介绍",
    }

    for f in report.get("fields", []):
        path = f.get("path", "")
        # 1. 标量字段检查 (如 self_evaluation, personal_advantage)
        max_len = limits.get(path)
        if max_len and isinstance(f.get("value"), str):
            cur_len = len(f["value"])
            if cur_len > max_len:
                overflow = cur_len - max_len
                f["over_limit"] = True
                f["current_len"] = cur_len
                f["max_limit"] = max_len
                f["overflow"] = overflow
                lbl = f.get("label") or field_label_map.get(path) or path
                warn_msg = f"⚠️ 【{lbl}】当前字数（{cur_len}字）超出平台 {max_len} 字上限（超出 {overflow} 字）！必须在表单中精简删减后方可正常回写，否则会被官网截断或报错。"
                if warn_msg not in warnings:
                    warnings.insert(0, warn_msg)
                f["note"] = f"⚠️ 字数超限：{cur_len}/{max_len}字（超{overflow}字），需删减精简"

        # 2. 数组条目检查 (如 work_experience, projects)
        if (f.get("type") == "array" or isinstance(f.get("value"), list)) and isinstance(f.get("value"), list):
            has_overflow = False
            mod_title = module_name_map.get(path) or f.get("label") or path
            for idx, item in enumerate(f["value"]):
                if not isinstance(item, dict):
                    continue
                item_title = item.get("proExpProjectName") or item.get("projectName") or item.get("project_name") or item.get("companyName") or item.get("company") or f"第{idx+1}条"
                for k, v in list(item.items()):
                    if isinstance(v, str) and k in limits:
                        k_limit = limits[k]
                        k_len = len(v)
                        if k_len > k_limit:
                            k_overflow = k_len - k_limit
                            has_overflow = True
                            item.setdefault("_over_limit", {})[k] = {
                                "current": k_len,
                                "max": k_limit,
                                "overflow": k_overflow,
                            }
                            k_name = field_label_map.get(k) or k
                            warn_msg = f"⚠️ 【{mod_title}·{item_title}】{k_name}共 {k_len} 字，超出平台 {k_limit} 字上限（超限 {k_overflow} 字）！请在表单中删减精简，否则回写将失败或被官网截断。"
                            if warn_msg not in warnings:
                                warnings.insert(0, warn_msg)
            if has_overflow:
                f["has_over_limit_items"] = True

    return report


def _enforce_self_text_overwrite(report: dict, fields_data: dict, master: dict, platform: str) -> dict:
    """确定性纠正：自述字段必须用主简历 summary 覆盖。
    修 LLM 保守误判——主简历内容与现有值不同时自作主张「沿用现有值」
    （识别特征：输出值 == 平台现有值 且 != 主简历 summary）。
    
    【关键修复】无论平台现有值是否为空都执行：
    - 平台现有值为空 → 肯定要用主简历 summary 填充
    - 平台现有值非空 → 若 LLM 输出等于现有值（违反规则 8），也要纠正为 summary
    """
    path = _PLATFORM_SELF_TEXT_PATH.get(platform)
    summary = _clean_md((master.get("data") or {}).get("summary"))
    if not path or not summary:
        return report
    existing = get_path(fields_data, path)
    for f in report.get("fields", []):
        if f.get("path") != path:
            continue
        val = f.get("value")
        if not isinstance(val, str) or not val.strip():
            continue
        if _clean_md(val) == summary:
            continue  # LLM 已正确覆盖
        # ✅ 关键修复：不管 existing 是否为空，只要 LLM 输出的不等于 summary，都要纠正
        if _eq_value(val, existing):
            f["value"] = summary
            f["confidence"] = "high"
            f["source"] = "master.summary"
            f["note"] = "系统纠正：按映射覆盖语义改用主简历内容"
            report.setdefault("warnings", []).append(
                f"{path}：LLM 保守沿用现有值，系统已按映射覆盖语义纠正为主简历 summary"
            )
        elif _is_empty_value(existing) and not _is_empty_value(val):
            # 平台现有值为空，但 LLM 没有用 summary 填充，而是填了别的内容
            f["value"] = summary
            f["confidence"] = "high"
            f["source"] = "master.summary"
            f["note"] = f"系统纠正：平台现有值已清空，强制填入主简历 summary"
            report.setdefault("warnings", []).append(
                f"{path}：平台现有值为空，系统已填入主简历 summary"
            )
        else:
            # 第三种失败模式：LLM 既没照抄 summary、也不等于现有值（擅自改写了 summary），
            # 同样强制纠正回主简历原文，杜绝自由发挥
            f["value"] = summary
            f["confidence"] = "high"
            f["source"] = "master.summary"
            f["note"] = "系统纠正：LLM 擅自改写了主简历内容，已恢复为主简历 summary 原文"
            report.setdefault("warnings", []).append(
                f"{path}：LLM 输出偏离主简历原文，系统已恢复为主简历 summary"
            )
    return report


def _attach_translations(report: dict, fields_data: dict) -> dict:
    """
    为编码字段附加中文释义：若 {path}Translation 字段存在且有值，
    给报告条目加 translation 字段（纯展示用，不参与写入）。
    """
    for f in report.get("fields", []):
        if "translation" in f:
            continue
        t_node = fields_data.get(f["path"] + "Translation")
        if isinstance(t_node, dict) and t_node.get("current_value") not in (None, ""):
            f["translation"] = str(t_node["current_value"])
    return report


def apply_mapping(fields_data: dict, entries: list) -> dict:
    """
    把人工确认后的映射条目写入 fields_data（就地修改）。
    entries: [{path, value}]
    返回 {"applied": [path...], "skipped": [{path, reason}]}
    """
    applied, skipped = [], []
    for e in entries or []:
        path = (e or {}).get("path", "")
        if not path:
            continue
        if path.endswith("Translation"):
            skipped.append({"path": path, "reason": "派生字段不允许直接写入"})
            continue
        value = e.get("value")
        if isinstance(value, list) and value:
            value = _sanitize_list_value(value)
            if not value and e.get("value"):
                # LLM 输出异常（元素为不可解析字符串）：放弃覆盖，保留平台原值
                skipped.append({"path": path, "reason": "数组元素格式异常，保留平台原值"})
                continue
        if set_path(fields_data, path, value):
            applied.append(path)
        else:
            skipped.append({"path": path, "reason": "字段不存在于该平台 schema"})
    return {"applied": applied, "skipped": skipped}


# 语义澄清（用户拍板 2026-08-31）：回写目标 = 官网在线简历与本地快照完全一致，
# 官网多出的列表条目（旧技能标签/旧语言等）按快照「覆盖删除」是设计内行为——
# 不做列表条目级保留合并。铁律「主简历没有的内容保留采集原值」只作用于字段值层
# （如 boss 期望的空壳保护），不延伸到列表条目级。


def _sanitize_list_value(value: list) -> list:
    """LLM 输出异常防御：数组字段元素应为 dict。
    若元素是 str(dict) repr（如 LLM 把「沿用官网原值」字符串化透传），用 literal_eval 还原；
    纯字符串数组（合法形态，如技能标签）原样返回；解析失败的元素丢弃。"""
    if all(isinstance(x, dict) for x in value):
        return value
    has_repr = any(isinstance(x, str) and x.strip().startswith("{") and x.strip().endswith("}")
                   for x in value)
    if not has_repr:
        return value
    import ast
    out = []
    for x in value:
        if isinstance(x, dict):
            out.append(x)
            continue
        if isinstance(x, str):
            s = x.strip()
            if s.startswith("{") and s.endswith("}"):
                try:
                    d = ast.literal_eval(s)
                except Exception:
                    continue
                if isinstance(d, dict):
                    out.append(d)
    return out


def _eq_value(a, b) -> bool:
    """归一化相等比较：空值互等（''/None/[]）、字符串 strip、数字转字符串比较"""
    if _is_empty_value(a) and _is_empty_value(b):
        return True
    if isinstance(a, str) or isinstance(b, str):
        return ("" if a is None else str(a)).strip() == ("" if b is None else str(b)).strip()
    return a == b


def _attach_changed_flags(report: dict, fields_data: dict) -> dict:
    """
    变更标记（用户需求）：生成报告时对比官网采集原值，标出「因映射而改变」的字段，
    前端在表单字段/条目旁显示橙色「已变更」徽章，一眼可辨。
    - 标量/object 子字段：值不同 → changed=True
    - 数组字段：逐条目匹配（start_date 精确匹配/退化索引），无匹配 = 新增条目，
      匹配但任一 key 值不同 → 该条目变更；字段给出 changed_items=[索引...]
    必须在 _sort_array_items_by_start_desc 之后执行（索引与最终顺序一致）。
    落盘保留标记（_slim_field 不剥离），恢复路径不重算（避免基于已应用数据对比失真）。
    """
    for f in report.get("fields", []):
        path = f.get("path")
        if f.get("type") == "array" or isinstance(f.get("value"), list):
            old_raw = get_path(fields_data, path)
            old_items = [it for it in (old_raw or []) if isinstance(it, dict)]
            items = f.get("value")
            if not isinstance(items, list):
                continue
            # 字符串数组（certificates/skill_tags 等）：无条目结构，整体集合比较
            # （忽略顺序：仅顺序不同不算内容变更，避免误标）
            if items and not isinstance(items[0], dict):
                def _norm_set(arr):
                    return sorted(set(str(x) for x in (arr or [])))
                if not _eq_value(_norm_set(items), _norm_set(old_raw)):
                    f["changed"] = True
                continue
            changed_items = []
            for i, it in enumerate(items):
                if not isinstance(it, dict):
                    continue
                pm = _match_platform_entry(old_items, it, i)
                if pm is None:
                    changed_items.append(i)  # 新增条目（平台无对应 start_date）
                    continue
                for k, v in it.items():
                    if k in ("start_date", "end_date"):
                        # 日期归一后比较，容忍 '2023.09' vs '2023/09' 等格式差异
                        if _norm_ym_key(v) != _norm_ym_key(pm.get(k)):
                            changed_items.append(i)
                            break
                        continue
                    if not _eq_value(v, pm.get(k)):
                        changed_items.append(i)
                        break
            if changed_items:
                f["changed"] = True
                f["changed_items"] = changed_items
        else:
            old = get_path(fields_data, path)
            if not _eq_value(f.get("value"), old):
                f["changed"] = True
    return report


# ============ 项目业绩剥离去重 ============

def _norm_text_compact(s: str) -> str:
    """归一化：去空白/标点/大小写，用于段落相似度比较"""
    return re.sub(r"[\s\W_]+", "", s or "").lower()


def _paras_similarity(a: str, b: str) -> float:
    """段落相似度：归一化后最长公共子序列占比（difflib）"""
    na, nb = _norm_text_compact(a), _norm_text_compact(b)
    if not na or not nb:
        return 0.0
    import difflib
    sm = difflib.SequenceMatcher(None, na, nb)
    return sm.ratio()


def _dedup_achievements_from_description(report: dict, platform: str) -> dict:
    """
    项目业绩剥离去重（用户需求）：LLM 把主简历项目描述中的业绩段落剥离到
    achievement/achievements 字段后，从项目描述中清除对应段落，避免同一内容
    在「项目描述」与「项目业绩」重复展示。
    - 段落级匹配：描述行与业绩行归一化后包含（精确子串）或相似度 ≥ 0.85 即删除。
    - 悬空小标题清理：业绩段被删后，从描述末尾向前，紧贴被删段的短标题行
      （如「业务成果」「MVP 测试与价值推演」等业绩小标题）一并清除；
      仅当该行之后全是已删业绩行/空行时才判定为悬空标题，正文小节标题与
      正常结尾短行不受影响。
    仅生成路径执行（restore 不执行，保护人工编辑；已去重内容幂等无副作用）。
    """
    desc_key = (_VERBATIM_DESC_FIELD.get(platform) or {}).get("projects")
    if not desc_key:
        return report
    warnings = list(report.get("warnings") or [])
    for f in report.get("fields", []):
        if f.get("path") != "projects" or f.get("type") != "array" or not isinstance(f.get("value"), list):
            continue
        for it in f["value"]:
            if not isinstance(it, dict):
                continue
            desc = it.get(desc_key)
            if not isinstance(desc, str) or not desc.strip():
                continue
            # 业绩段落：条目内存在的成果类自由文本 key（achievement/achievements 等）
            ach_lines: list[str] = []
            for k in _EXTRA_STRIP_ITEM_KEYS:
                av = it.get(k)
                if isinstance(av, str) and av.strip():
                    ach_lines.extend(ln.strip() for ln in av.split("\n") if ln.strip())
            if not ach_lines:
                continue
            # 行级匹配：标记与业绩行高度重合的描述行
            lines = desc.split("\n")
            marks = [False] * len(lines)
            for idx, line in enumerate(lines):
                ls = line.strip()
                if not ls:
                    continue
                ln = _norm_text_compact(ls)
                if len(ln) < 12:
                    continue  # 短行不参与相似度删除，避免误删
                for al in ach_lines:
                    an = _norm_text_compact(al)
                    if len(an) < 12:
                        continue
                    if an in ln or ln in an or _paras_similarity(ls, al) >= 0.85:
                        marks[idx] = True
                        break
            if not any(marks):
                continue  # 无业绩内容被删 → 小标题不处理
            # 悬空小标题清理：从末尾向前，紧贴被删业绩段的短标题行
            # （如「业务成果」「MVP 测试与价值推演」，≤50 归一化字符）一并清除。
            # 判定：该行之后第一个非空行必须是「原本就被删的业绩行」（可跨空行），
            # 或「紧贴无空行且同属短标题的连续标题行」——正文长行、隔空行的正文短行、
            # 以及正常结尾短行（如「技术栈：」）都不满足，安全保留。
            orig = list(marks)
            for i in range(len(lines) - 1, -1, -1):
                if not lines[i].strip() or orig[i]:
                    continue
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j >= len(lines):
                    break  # 其后无内容 → 正常结尾，停止
                if marks[j] and (orig[j] or not any(not lines[k].strip() for k in range(i + 1, j))):
                    # 「标签：内容」行是正文，绝不是悬空标题（用户规则 2026-08-30）：
                    # 「技术栈：Python」「项目链接：github.com/x」归一化后常 ≤50 字符，
                    # 紧贴被删业绩行时曾被级联误吞——冒号后带内容的一票否决，停止上溯
                    _hc = re.sub(r"^[#\-\*•\s]+", "", lines[i]).strip()
                    _parts = re.split(r"[：:]", _hc, 1)
                    if len(_parts) == 2 and _parts[1].strip():
                        break
                    # 直接紧贴被删业绩行 → 上限 50（覆盖「业务成果与项目价值 (…)」类长标题）；
                    # 经连续标题行级联 → 上限 20（连续小标题通常很短，防级联误吞正文）
                    limit = 50 if orig[j] else 20
                    if len(_norm_text_compact(lines[i])) <= limit:
                        marks[i] = True  # 悬空业绩小标题
                        continue
                break  # 其后有保留内容 → 停止
            # 清理连续空行后写回
            keep: list[str] = []
            prev_blank = False
            for line, m in zip(lines, marks):
                if m:
                    continue
                blank = not line.strip()
                if blank and prev_blank:
                    continue
                prev_blank = blank
                keep.append(line)
            it[desc_key] = "\n".join(keep).strip()
            name = it.get("project_name") or it.get("name") or "项目"
            warnings.append(
                f"projects 第{f['value'].index(it) + 1}条（{name}）业绩段落及其小标题已从项目描述中移除（剥离后避免重复），如删错请人工核对"
            )
    if warnings:
        report["warnings"] = warnings
    return report


def _rule_map_51job(fields_data: dict, master: dict, llm_error: str = None) -> dict:
    """
    51job 确定性规则映射：主简历最新内容覆盖平台文本/时间字段，
    主简历没有的保留平台原值；选项类字段（求职意向/技能代码/语言/证书）不动。
    作为 LLM 不可用（无 Key/余额不足/调用失败）时的兜底，保证映射闭环可用。
    """
    data = master.get("data") or {}
    fields, unfilled, warnings = [], [], []
    warnings.append(
        "⚠️ 已降级为确定性规则映射（LLM 不可用：%s），字段覆盖范围有限，请重点核对。仅覆盖个人优势/工作经历/项目经历/教育经历的文本与时间字段；求职意向、专业技能、语言能力、资格证书保留官网原值" % (llm_error or "未配置")
    )
    logger.warning("[映射降级] 51job 规则映射触发，原因: %s", llm_error or "未配置 LLM API Key")

    # 1) 个人优势 ← summary / personal_advantage / self_assessment (51job 限500字)
    summary = _clean_md(data.get("summary") or data.get("personal_advantage") or data.get("self_assessment"))
    if summary:
        if len(summary) > 500:
            warnings.append(f"self_introduction.selfIntroduction：主简历 summary 超 51job 500 字上限，已截断至 500 字（原 {len(summary)} 字），请人工核对")
            summary = summary[:500]
        fields.append({"path": "self_introduction.selfIntroduction", "value": summary,
                       "confidence": "high", "source": "master.summary", "note": "规则映射", "type": "textarea"})

    def _emit_array(path, items, note):
        fields.append({"path": path, "value": items, "confidence": "high",
                       "source": "master", "note": note, "type": "array"})

    # 2) 工作经历 (51job 描述限2000字)
    we = data.get("workExperience") or data.get("work_experience") or []
    plat_we = (fields_data.get("works") or {}).get("current_value") or []
    if we:
        new_items = json.loads(json.dumps(plat_we)) if (plat_we and all(isinstance(x, dict) for x in plat_we)) else []
        matched = set()
        for mi, pi in _pair_entries(we, new_items, lambda x: x.get("years"), lambda x: x.get("startTime")):
            mit, pit = we[mi], new_items[pi]
            matched.add(mi)
            if _clean_md(mit.get("company")):
                pit["companyName"] = _clean_md(mit["company"])
            if _clean_md(mit.get("title")):
                pit["position"] = _clean_md(mit["title"])
            desc = _clean_md(mit.get("description"))
            if desc:
                if len(desc) > 2000:
                    desc = desc[:2000]
                pit["workDescription"] = desc
            st, en = _parse_years(mit.get("years"))
            if st:
                pit["startTime"] = st
            if en:
                pit["endTime"] = en
            # 提炼技能与推导工作类型
            cname = pit.get("companyName") or ""
            pos = pit.get("position") or ""
            w_desc = pit.get("workDescription") or ""
            skills = mit.get("skills") or mit.get("skillTags") or _extract_work_skills(w_desc, pos)
            clean_s = _clean_skill_tags(skills)
            pit["workVocationalSkills"] = clean_s
            pit["skills"] = clean_s
            w_type = _infer_work_type(cname, pos, w_desc)
            pit["workType"] = w_type
            pit["seekType"] = w_type

        # 追加主简历多出的工作经历（如自由职业者新增条目）
        for mi, mit in enumerate(we):
            if mi not in matched:
                st, en = _parse_years(mit.get("years"))
                desc = _clean_md(mit.get("description"))
                if desc and len(desc) > 2000:
                    desc = desc[:2000]
                cname = _clean_md(mit.get("company"))
                pos = _clean_md(mit.get("title"))
                skills = mit.get("skills") or mit.get("skillTags") or _extract_work_skills(desc, pos)
                clean_s = _clean_skill_tags(skills)
                w_type = _infer_work_type(cname, pos, desc)
                new_item = {
                    "id": "",
                    "companyName": cname,
                    "position": pos,
                    "workDescription": desc,
                    "startTime": st or "",
                    "endTime": en or "至今",
                    "workType": w_type,
                    "seekType": w_type,
                    "workFunction": "",
                    "workFunctionString": "",
                    "workIndustry": "",
                    "workIndustryString": "",
                    "workVocationalSkills": clean_s,
                    "skills": clean_s,
                }
                new_items.append(new_item)

        _emit_array("works", new_items, "覆盖 companyName/position/workDescription/起止时间/相关技能/工作类型")

    # 3) 项目经历 (51job 描述限2000字)
    pj = data.get("personalProjects") or data.get("projects") or []
    plat_pj = (fields_data.get("projects") or {}).get("current_value") or []
    if pj and plat_pj and all(isinstance(x, dict) for x in plat_pj):
        new_items = json.loads(json.dumps(plat_pj))
        matched = set()
        for mi, pi in _pair_entries(pj, new_items, lambda x: x.get("years"), lambda x: x.get("startTime")):
            mit, pit = pj[mi], new_items[pi]
            matched.add(mi)
            if _clean_md(mit.get("name")):
                pit["projectName"] = _clean_md(mit["name"])
            desc = _clean_md(mit.get("description"))
            if desc:
                if len(desc) > 2000:
                    desc = desc[:2000]
                pit["describe"] = desc
            st, en = _parse_years(mit.get("years"), single_as_end=True)  # 项目经历：单时间默认同月结束
            if st:
                pit["startTime"] = st
            if en:
                pit["endTime"] = en
        _emit_array("projects", new_items, "覆盖 projectName/describe/起止时间")
        for mi, mit in enumerate(pj):
            if mi not in matched:
                unfilled.append({"path": "projects",
                                 "label": "项目·%s" % (_clean_md(mit.get("name")) or mi + 1),
                                 "reason": "51job 无对应条目，请手动添加"})

    # 4) 教育经历（degree 为平台选项代码，不覆盖）
    ed = data.get("education") or data.get("educations") or []
    plat_ed = (fields_data.get("educations") or {}).get("current_value") or []
    if ed and plat_ed and all(isinstance(x, dict) for x in plat_ed):
        new_items = json.loads(json.dumps(plat_ed))
        matched = set()
        for mi, pi in _pair_entries(ed, new_items, lambda x: x.get("years"), lambda x: x.get("startTime")):
            mit, pit = ed[mi], new_items[pi]
            matched.add(mi)
            if _clean_md(mit.get("institution")):
                pit["schoolName"] = _clean_md(mit["institution"])
            if _clean_md(mit.get("major")):
                pit["major"] = _clean_md(mit["major"])
            st, en = _parse_years(mit.get("years"))
            if st:
                pit["startTime"] = st
            if en:
                pit["endTime"] = en
        _emit_array("educations", new_items, "覆盖 schoolName/major/起止时间（degree 代码保留）")
        for mi, mit in enumerate(ed):
            if mi not in matched:
                unfilled.append({"path": "educations",
                                 "label": "教育·%s" % (_clean_md(mit.get("institution")) or mi + 1),
                                 "reason": "51job 无对应条目，请手动添加"})

    report = {"success": True, "platform": "51job", "fields": fields,
              "unfilled": unfilled, "warnings": warnings}
    report = _map_51job_work_function(report, master)  # 职位类目：主简历职位名精确匹配官方职位列表
    report = _map_51job_skills(report, master)  # 专业技能：匹配官方 IT 技能库与熟练度
    # 后处理管线与 LLM/猎聘规则路径对齐：unfilled 补全 + 下拉选项 + 翻译 + 长度扫描
    report = _ensure_unfilled_fields(report, fields_data)
    report = _attach_field_options(report, "51job")
    report = _attach_translations(report, fields_data)
    report = _check_field_length_limits(report, "51job")
    report = _attach_changed_flags(report, fields_data)
    report["message"] = "规则映射完成：%d 项填入，%d 项待人工" % (len(fields), len(unfilled))
    return report

# ============ 报告持久化（刷新/重启不丢，省 LLM token） ============

def _slim_field(f: dict) -> dict:
    """剥离静态附加数据（平台选项/翻译），恢复时重新附加，避免落盘体积膨胀"""
    out = dict(f)
    out.pop("options", None)
    out.pop("item_options", None)
    out.pop("translation", None)
    return out


def _write_reports_file(data: dict) -> None:
    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    tmp = REPORT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, REPORT_FILE)


def save_report(platform: str, report: dict, selected_modules: list[str] | None = None) -> None:
    """
    生成成功后落盘：剥离静态选项（options/item_options）与翻译（translation），
    恢复时由 _attach_field_options / _attach_translations 重新附加，避免重复占用体积。
    同步保存 selected_modules 范围。
    """
    sel = selected_modules if selected_modules is not None else report.get("selected_modules")
    slim = {
        "generated_at": report.get("generated_at") or datetime.now().isoformat(timespec="seconds"),
        "fields": [_slim_field(f) for f in report.get("fields", [])],
        "unfilled": report.get("unfilled", []),
        "warnings": report.get("warnings", []),
    }
    if sel:
        slim["selected_modules"] = list(sel)
    # 「已修改」标识持久化：apply 成功写入的字段 path 列表（重新生成报告时清空，新一轮映射重新累计）
    if report.get("applied_paths"):
        slim["applied_paths"] = report["applied_paths"]
    data = load_reports()
    data[platform] = slim
    _write_reports_file(data)


def set_selected_master_record(record_id: str | None) -> None:
    """记录「主简历来源」当前选择的记录（报告元信息），刷新页面后可恢复"""
    data = load_reports()
    data["selected_master_record_id"] = record_id
    _write_reports_file(data)


def get_selected_master_record() -> str | None:
    """读取「主简历来源」上次选择的记录；None = 默认（启用中的）"""
    return load_reports().get("selected_master_record_id")


def reset_report_change_flags(platform: str) -> None:
    """平台重新采集后重置该平台映射报告的变更标记（动作语义收口）。

    「已变更」(changed/changed_items) 与「已修改」(applied_paths) 的语义是
    "本轮映射相对当时采集原值造成的改变"——采集落地了新的平台原值，上一轮
    映射会话的对比基准随之失效：保留旧标记会让用户在未做映射时看到"已修改"。
    报告本体（映射值）保留供查阅，仅重置标记并提示重新生成。
    """
    data = load_reports()
    slim = data.get(platform)
    if not slim:
        return
    had_flags = bool(slim.get("applied_paths")) or any(
        f.get("changed") or f.get("changed_items") for f in slim.get("fields", [])
    )
    slim.pop("applied_paths", None)
    for f in slim.get("fields", []):
        f.pop("changed", None)
        f.pop("changed_items", None)
    if had_flags:
        slim.setdefault("warnings", []).append(
            "平台数据已重新采集，映射变更标注已重置；旧报告基于采集前原值生成，建议重新生成映射报告以获取最新差异"
        )
    _write_reports_file(data)


def load_reports() -> dict:
    """读取全部平台已落盘报告：{platform: {generated_at, fields, unfilled, warnings}}"""
    if not os.path.exists(REPORT_FILE):
        return {}
    try:
        with open(REPORT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def restore_report(platform: str, fields_data: dict) -> dict | None:
    """
    恢复该平台最近一次生成的报告（不调 LLM）：
    重新附加 translation 与平台选项，保证前端下拉/翻译与生成后完全一致。
    无落盘报告返回 None。
    """
    slim = load_reports().get(platform)
    if not slim:
        return None
    selected_modules = slim.get("selected_modules")
    report = {
        "success": True,
        "platform": platform,
        "restored": True,
        "generated_at": slim.get("generated_at", ""),
        "fields": slim.get("fields", []),
        "unfilled": slim.get("unfilled", []),
        "warnings": slim.get("warnings", []),
        "applied_paths": slim.get("applied_paths", []),  # 「已修改」标识：成功应用映射的字段（刷新不丢）
        "selected_modules": selected_modules,
        "message": "已恢复上次生成报告（未重新调用 Agent）",
    }
    report = _attach_translations(report, fields_data)
    report = _normalize_array_items(report)  # 历史报告条目字段类型统一（hideResume 布尔/skills 数组）
    report = _fallback_expectations(report, fields_data, selected_modules=selected_modules)  # 历史报告空期望 → 沿用平台现有值
    report = _preserve_empty_platform_values(report, fields_data, platform)  # 空值保护：主简历未提及 → 保留官网原值 + 警告
    report = _protect_unmentioned_modules(report, fields_data, platform, selected_modules=selected_modules)  # 未提及模块保护：整体全空 → 保留平台原值 + 转 unfilled
    if platform == "zhilian":
        report = _normalize_zhilian_dates(report)  # 智联日期格式纠正：人话日期 → 官网机器格式
    report = _trim_expectations(report)  # 历史报告超限 expectations 裁剪（全职≤3、兼职≤1）
    report = _normalize_object_fields(report)  # object 字段类型统一（overseas.allowView 布尔）
    report = _strip_markdown(report, platform)  # 历史报告剥离 Markdown 符号（对纯文本幂等，不动人工编辑）
    report = _fallback_certificates(report, fields_data, selected_modules=selected_modules)  # 资格证书兜底：沿用平台现有值
    # 历史报告也补全 unfilled 字段（主简历未提供的字段展示在字段列表，可主动新增/修改）；
    # 必须在 _attach_field_options 之前，让新追加的字段挂上平台选项
    report = _ensure_unfilled_fields(report, fields_data, selected_modules=selected_modules)
    report = _attach_field_options(report, platform)
    # 重跑一致性校验：先剔除旧的「不在平台选项中」告警防重复；选项映射表升级后，
    # 历史报告的非法值（如 jobType 映射成中文）也会得到新鲜告警
    report["warnings"] = [w for w in report.get("warnings", []) if "不在平台选项中" not in w]
    report = _validate_option_consistency(report, platform)
    # 「已变更/已修改」标记保持生成映射那一刻的动作语义（对比当时采集原值，落盘固化），
    # 此处不重算：采集会作为统一入口重置标记（见 reset_report_change_flags），
    # 若在此对比当前文件值，采集后的"旧映射值 vs 新原值"差异会被误标为已修改
    if selected_modules and len(selected_modules) > 0:
        sel_set = set(selected_modules)
        report["fields"] = [f for f in report.get("fields", []) if _field_path_to_module(f.get("path", "")) in sel_set]
        report["unfilled"] = [u for u in report.get("unfilled", []) if _field_path_to_module(u.get("path", "")) in sel_set]
    return report


# ============ LLM 编排 ============

# ============ 确定性规则映射（LLM 不可用兜底） ============

def _clean_md(text) -> str:
    """主简历 Markdown（**加粗**、列表行）→ 平台纯文本"""
    if isinstance(text, list):
        text = "\n".join(str(t) for t in text)
    s = (text or "").replace("**", "")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _parse_years(years, single_as_end: bool = False) -> tuple:
    """'2024.04-至今'/'2024.04 - 至今'/'2026.02-06'/'2026.03' → ('2024-04','至今')/('2026-02','2026-06')/('2026-03','至今')
    single_as_end=True（51job 项目经历）：只有单时间点 '2026.03' 时结束时间默认同月而非至今"""
    if not years:
        return None, None
    s = str(years).strip().replace(".", "-").replace("/", "-")
    m = re.match(r"^(\d{4})[-/](\d{1,2})\s*(?:[-~至到]\s*(.+))?$", s)
    if not m:
        return None, None
    y, mo, rest = m.groups()
    start = f"{y}-{int(mo):02d}"
    rest = (rest or "").strip()
    if not rest:
        return (start, start) if single_as_end else (start, "至今")
    if rest in ("至今", "now", "Now", "目前", "Present", "present"):
        return start, "至今"
    m2 = re.match(r"^(\d{4})[-/](\d{1,2})$", rest)
    if m2:
        return start, f"{m2.group(1)}-{int(m2.group(2)):02d}"
    m3 = re.match(r"^(\d{1,2})$", rest)
    if m3:
        return start, f"{y}-{int(m3.group(1)):02d}"
    return start, "至今"


def _years_is_single(years) -> bool:
    """主简历时间是否仅单个时间点（如 '2026.03'，无结束段也无'至今'）"""
    s = (str(years) if years else "").strip().replace(".", "-").replace("/", "-")
    if not s or "至今" in s or "now" in s.lower():
        return False
    return re.fullmatch(r"\d{4}-\d{1,2}", s) is not None


def _enforce_51job_single_project_end(report: dict, master: dict) -> dict:
    """
    51job 项目经历单时间点规则（用户需求）：主简历项目只写单个时间（如 2026.03）时，
    结束时间默认 = 开始时间同月，禁止默认'至今'。对 LLM 输出强制兜底，
    条目定位用 _match_master_index（名称 → 时间 → 顺序）。仅生成路径执行。
    """
    master_items = (master.get("data") or {}).get("personalProjects") or []
    if not isinstance(master_items, list) or not master_items:
        return report
    warnings = list(report.get("warnings") or [])
    for f in report.get("fields", []):
        if f.get("path") != "projects" or f.get("type") != "array" or not isinstance(f.get("value"), list):
            continue
        for idx, it in enumerate(f["value"]):
            if not isinstance(it, dict):
                continue
            mi = _match_master_index(master_items, it, idx)
            if mi is None:
                continue
            years = master_items[mi].get("years")
            if not _years_is_single(years):
                continue
            st, _ = _parse_years(years)
            if not st:
                continue
            cur_end = str(it.get("endTime") or "").strip()
            if cur_end != st:
                it["endTime"] = st
                if "endTimeString" in it:
                    it["endTimeString"] = st.replace("-", ".")
                warnings.append(
                    f"项目经历第{idx + 1}条主简历仅单个时间（{years}），结束时间已按同月处理（非至今）")
    report["warnings"] = warnings
    return report


# ============ 51job 职位类目映射 ============

def _norm_funtype_name(s) -> str:
    """职位名归一化：去全部空白 + 小写，用于精确匹配比较"""
    return re.sub(r"\s+", "", str(s or "")).lower()


_JOB51_FUNTYPE_INDEX = None


def _load_job51_funtype_index() -> dict:
    """51job 职位类目反查表：归一化职位名 → (code, 官方职位名)，取树形字典全部叶子（带缓存）"""
    global _JOB51_FUNTYPE_INDEX
    if _JOB51_FUNTYPE_INDEX is not None:
        return _JOB51_FUNTYPE_INDEX
    idx = {}

    def _walk(node):
        for it in node.get("items") or []:
            if not isinstance(it, dict):
                continue
            subs = it.get("items") or []
            if subs:
                _walk(it)
                continue
            name = (it.get("value") or "").strip()
            code = it.get("code")
            if name and code:
                key = _norm_funtype_name(name)
                if key not in idx:  # 同名叶子保留首个
                    idx[key] = (code, name)

    try:
        p = os.path.join(DATA_DIR, "51job_dd_funtype.json")
        with open(p, "r", encoding="utf-8") as fp:
            _walk(json.load(fp))
    except Exception:
        idx = {}
    _JOB51_FUNTYPE_INDEX = idx
    return idx


def _map_51job_work_function(report: dict, master: dict) -> dict:
    """
    51job 工作经历职位类目映射（用户需求）：
      - 主简历职位名与 51job 官方职位列表（51job_dd_funtype.json）精确匹配 →
        确定性写入 workFunction(code)/workFunctionString，100% 正确；
      - 找不到一模一样的匹配 → 保留官网原值不动，写 warning 提醒用户在工作经历编辑器手动调整。
    生成路径（LLM/规则引擎）均执行，须在 _attach_changed_flags 之前（变更标记需覆盖职位改动）。
    """
    idx = _load_job51_funtype_index()
    if not idx:
        return report
    master_items = (master.get("data") or {}).get("workExperience") or []
    if not isinstance(master_items, list) or not master_items:
        return report
    warnings = list(report.get("warnings") or [])
    for f in report.get("fields", []):
        if f.get("path") != "works" or f.get("type") != "array" or not isinstance(f.get("value"), list):
            continue
        for i, it in enumerate(f["value"]):
            if not isinstance(it, dict):
                continue
            mi = _match_master_index(master_items, it, i)
            if mi is None:
                continue
            title = md_to_plain_text(str(master_items[mi].get("title") or "")).strip()
            if not title:
                continue
            hit = idx.get(_norm_funtype_name(title))
            wt = str(it.get("workType") or it.get("seekType") or "0")
            wt_name = "全职" if wt == "0" else ("兼职" if wt == "1" else "实习")
            if hit:
                code, name = hit
                if str(it.get("workFunction") or "") != code:
                    it["workFunction"] = code
                    it["workFunctionString"] = name
                    warnings.append(
                        f"工作经历第{i + 1}条职位「{title}」已精确匹配 51job 职位列表 → {name}（工作类型: {wt_name}）")
            else:
                warnings.append(
                    f"⚠ 工作经历第{i + 1}条：主简历职位「{title}」在 51job 职位列表中无一模一样的匹配，"
                    f"已保留官网原职位类目，请在工作经历编辑器中核对职位类目与工作类型（当前: {wt_name}）")
    report["warnings"] = warnings
    return report


# ============ 51job 专业技能 (skills) 映射与官方白名单对齐 ============

_JOB51_IT_SKILLS_INDEX = None

def _load_job51_it_skills_index() -> dict:
    """加载 51job 官方专业技能反查表：归一化技能名 → (code, 官方技能名)"""
    global _JOB51_IT_SKILLS_INDEX
    if _JOB51_IT_SKILLS_INDEX is not None:
        return _JOB51_IT_SKILLS_INDEX
    idx = {}
    try:
        p = os.path.join(DATA_DIR, "51job_it_skills.json")
        with open(p, "r", encoding="utf-8") as fp:
            categories = json.load(fp)
            for cat in categories:
                for item in cat.get("items", []):
                    code = item.get("code")
                    val = item.get("value")
                    eval_ = item.get("eValue")
                    if val:
                        idx[val.strip().lower()] = (code, val)
                    if eval_:
                        idx[eval_.strip().lower()] = (code, val)
        # 常见技术别名归一化映射到 51job 官方技能库
        aliases = {
            "python3": "python", "python 3": "python", "py": "python",
            "fastapi": "python", "flask": "python", "django": "python",
            "sql": "sql", "mysql": "mysql", "sql server": "ms sql server", "mssql": "ms sql server",
            "oracle": "oracle", "db2": "db2", "hive": "hive", "hadoop": "hadoop", "spark": "spark",
            "js": "javascript", "ts": "javascript", "typescript": "javascript", "es6": "javascript",
            "html": "html5", "css": "html5", "css3": "html5", "h5": "html5",
            "web前端": "web前端", "前端开发": "web前端", "前端": "web前端",
            "react": "web前端", "react.js": "web前端", "vue": "web前端", "vue.js": "web前端", "next.js": "web前端",
            "linux": "linux", "ubuntu": "linux", "centos": "linux",
            "shell": "shell", "bash": "shell", "zsh": "shell",
            "excel": "ms excel", "word": "ms word",
            "ppt": "ms powerpoint", "powerpoint": "ms powerpoint",
            "visio": "ms visio", "ps": "photoshop",
            "tensorflow": "tensorflow", "pytorch": "tensorflow", "keras": "tensorflow",
            "深度学习": "tensorflow", "deep learning": "tensorflow",
            "tableau": "数据分析", "powerbi": "数据分析", "power bi": "数据分析", "bi": "数据分析",
            "数据分析": "数据分析", "数据挖掘": "数据挖掘", "数据建模": "数据建模",
            "ui": "ui", "ux": "ui", "ui/ux": "ui", "ui设计": "ui",
            "seo": "seo", "sem": "seo",
            "golang": "golang", "go": "golang",
            "java": "java", "j2ee": "j2ee",
            "c++": "c/c++", "cpp": "c/c++", "c": "c/c++",
            "r": "r语言", "r语言": "r语言",
        }
        for k, target in aliases.items():
            if target.lower() in idx and k.lower() not in idx:
                idx[k.lower()] = idx[target.lower()]
    except Exception as e:
        logger.warning("Load 51job_it_skills.json error: %s", e)
        idx = {}
    _JOB51_IT_SKILLS_INDEX = idx
    return idx


def _map_51job_skills(report: dict, master: dict) -> dict:
    """
    51job 专业技能模块智能化映射与官方白名单对齐：
      1. 严格白名单过滤：只保留能够与 51job 官方标准技能树（51job_it_skills.json）对齐的核心技术词；
      2. 彻底过滤分类大纲大标题（如“大模型与 AI 工程”、“全栈开发与架构”等）；
      3. 熟练程度智能评估：根据主简历项目深度与使用年限，分配 0(精通)/1(熟练)/3(良好)/2(一般)，杜绝空 ability；
      4. 结构标准化：补齐 skillType (4位代码), skillName, skillTypeString, ability, abilityString, isEnglish: False；
      5. 兜底补齐：若条目少于 8 条，从主简历技能/项目/工作经历中智能提取白名单项补足 8～12 条。
    """
    idx = _load_job51_it_skills_index()
    data = master.get("data") or {}
    fields = report.get("fields", [])
    skills_field = next((f for f in fields if f.get("path") == "skills"), None)

    ability_map = {"0": "精通", "1": "熟练", "3": "良好", "2": "一般"}

    # 明显的分类标题过滤模式
    invalid_header_patterns = [
        "与", "大模型与", "开发与架构", "分析与自动化", "辅助与设计",
        "工程与架构", "技能与特长", "专业技能", "技术栈", "工具链"
    ]

    def is_invalid_title(name: str) -> bool:
        if not name or len(name) > 25:
            return True
        for pat in invalid_header_patterns:
            if pat in name and len(name) > 6:
                return True
        return False

    matched_skills = []
    seen_codes = set()

    # 1. 先处理 LLM 已输出的技能列表（白名单过滤 + 码值绑定 + 熟练度归一）
    if skills_field and isinstance(skills_field.get("value"), list) and skills_field["value"]:
        for it in skills_field["value"]:
            if not isinstance(it, dict):
                continue
            s_name = str(it.get("skillName") or it.get("skill") or it.get("skillTypeString") or "").strip()
            s_code = str(it.get("skillType") or "").strip()
            if is_invalid_title(s_name):
                continue

            hit = None
            if s_code:
                # 检查 code 是否合法
                for k, v in idx.items():
                    if v[0] == s_code:
                        hit = v
                        break
            if not hit and s_name:
                hit = idx.get(s_name.lower())

            if hit:
                code, official_name = hit
                if code not in seen_codes:
                    seen_codes.add(code)
                    ab = str(it.get("ability") or it.get("level") or "1").strip()
                    if ab not in ability_map:
                        ab = "1"
                    matched_skills.append({
                        "id": str(it.get("id") or ""),
                        "skillType": code,
                        "skillName": official_name,
                        "skillTypeString": official_name,
                        "ability": ab,
                        "abilityString": ability_map.get(ab, "熟练"),
                        "isEnglish": False
                    })

    # 2. 若匹配条目不足 8 条，从主简历全篇技能、工作经历、项目经历中自动扫描补充官方白名单技能
    if len(matched_skills) < 8:
        extracted_candidates = []
        master_skills = data.get("skills") or data.get("skillTags") or []
        if isinstance(master_skills, str):
            master_skills = [s.strip() for s in re.split(r"[,、|/\n]+", master_skills) if s.strip()]
        extracted_candidates.extend(master_skills)

        for we in (data.get("workExperience") or []):
            extracted_candidates.extend(we.get("skills") or we.get("skillTags") or [])
            # 扫描工作描述中的技术关键词
            w_desc = we.get("description") or we.get("workDescription") or ""
            if isinstance(w_desc, str):
                for tech in ["python", "sql", "mysql", "linux", "shell", "tableau", "excel", "javascript", "html5", "tensorflow"]:
                    if tech in w_desc.lower():
                        extracted_candidates.append(tech)

        for pe in (data.get("personalProjects") or data.get("projects") or []):
            extracted_candidates.extend(pe.get("skills") or pe.get("skillTags") or [])
            p_desc = pe.get("describe") or pe.get("description") or ""
            if isinstance(p_desc, str):
                for tech in ["python", "fastapi", "react", "next.js", "pandas", "sql", "numpy", "tableau", "docker"]:
                    if tech in p_desc.lower():
                        extracted_candidates.append(tech)

        # 扫描主简历全文推导熟练度
        full_text = json.dumps(data, ensure_ascii=False).lower()

        for cand in extracted_candidates:
            if not cand or not isinstance(cand, str):
                continue
            cand_clean = cand.strip()
            if is_invalid_title(cand_clean):
                continue
            hit = idx.get(cand_clean.lower()) if idx else None
            if hit:
                code, official_name = hit
                if code not in seen_codes:
                    seen_codes.add(code)
                    # 智能推导熟练度
                    inferred_ability = "1"
                    if official_name in ["Python", "SQL"] and ("架构" in full_text or "独立负责" in full_text or "从0到1" in full_text):
                        inferred_ability = "0"  # 精通
                    elif official_name in ["数据分析", "数据挖掘", "MySQL"]:
                        inferred_ability = "1"  # 熟练
                    elif official_name in ["MS Excel", "Photoshop", "Shell"]:
                        inferred_ability = "3"  # 良好

                    matched_skills.append({
                        "id": "",
                        "skillType": code,
                        "skillName": official_name,
                        "skillTypeString": official_name,
                        "ability": inferred_ability,
                        "abilityString": ability_map.get(inferred_ability, "熟练"),
                        "isEnglish": False
                    })
            if len(matched_skills) >= 12:
                break

    # 按熟练度排序（精通 0 > 熟练 1 > 良好 3 > 一般 2）
    sort_weight = {"0": 0, "1": 1, "3": 2, "2": 3}
    matched_skills.sort(key=lambda x: sort_weight.get(x.get("ability", "1"), 9))

    if not matched_skills:
        # 空结果绝不写入：apply 会把空数组 set 进快照，回传后官网专业技能被清空。
        # 移除已存在的 skills 字段（如有）并警告，官网原值得以保留。
        report["fields"] = [f for f in report.get("fields", []) if f.get("path") != "skills"]
        report.setdefault("warnings", []).append(
            "skills：主简历技能未命中 51job 官方技能白名单，已跳过该字段（官网原值保留），请人工核对"
        )
        return report

    if skills_field:
        skills_field["value"] = matched_skills
    else:
        fields.append({
            "path": "skills",
            "value": matched_skills,
            "confidence": "high",
            "source": "master.skills",
            "note": "从主简历匹配 51job 官方专业技能库",
            "type": "array"
        })
    return report


def _pair_entries(master_items, plat_items, m_years, p_start):
    """[(master_idx, plat_idx)]：条数相等按序对齐（同源同序，名称冲突对剔除）；否则起始月精确匹配"""
    if len(master_items) == len(plat_items):
        pairs = []
        for mi, pi in zip(range(len(master_items)), range(len(plat_items))):
            mn = {str(master_items[mi].get(k) or "").strip() for k in ("name", "company", "title")} - {""}
            pn = {str(plat_items[pi].get(k) or "").strip() for k in ("name", "company", "title", "compName")} - {""}
            if mn and pn and mn.isdisjoint(pn):
                continue  # 名称完全对不上，按序对齐不可信，宁缺勿错配
            pairs.append((mi, pi))
        return pairs
    pairs, used = [], set()
    for mi, mit in enumerate(master_items):
        ms, _ = _parse_years(m_years(mit))
        if not ms:
            continue
        for pi, pit in enumerate(plat_items):
            if pi in used:
                continue
            if (p_start(pit) or "") == ms:
                pairs.append((mi, pi))
                used.add(pi)
                break
    return pairs


def _rule_map_liepin(fields_data: dict, master: dict, llm_error: str = "", selected_modules: list[str] | None = None) -> dict:
    """
    猎聘确定性规则映射：覆盖优势亮点 + 工作经历/项目经历/教育经历的文本与日期，
    基本信息常用字段同步；求职意向/资格证书/技能标签/语言能力保留官网原值。
    """
    data = master.get("data") or {}
    fields, unfilled, warnings = [], [], []
    warnings.append(
        "⚠️ 已降级为确定性规则映射（LLM 不可用：%s），字段覆盖范围有限，请重点核对。已覆盖优势亮点/工作经历/项目经历/教育经历的文本与起止时间；求职意向、技能标签、语言能力、资格证书保留官网原值" % (llm_error or "未配置")
    )
    logger.warning("[映射降级] 猎聘规则映射触发，原因: %s", llm_error or "未配置 LLM API Key")

    # 1) 优势亮点 ← summary
    summary = _clean_md(data.get("summary"))
    if summary:
        fields.append({
            "path": "self_assessment", "value": summary, "confidence": "high",
            "source": "master.summary", "note": "规则映射", "type": "textarea"
        })

    def _emit_array(path, items, note):
        fields.append({
            "path": path, "value": items, "confidence": "high",
            "source": "master", "note": note, "type": "array"
        })

    def _fmt_ym(val: str) -> str:
        if not val:
            return ""
        if "至今" in val or "现在" in val:
            return "至今"
        s = val.replace(".", "/").replace("-", "/")
        m = re.match(r"(\d{4})[/](\d{1,2})", s)
        if m:
            return f"{m.group(1)}/{int(m.group(2)):02d}"
        return s

    # 2) 工作经历
    we = data.get("workExperience") or data.get("work_experience") or []
    plat_we = (fields_data.get("work_experience") or {}).get("current_value") or []
    if we:
        new_items = []
        if plat_we and all(isinstance(x, dict) for x in plat_we):
            new_items = json.loads(json.dumps(plat_we))
        matched = set()
        pairs = _pair_entries(we, new_items, lambda x: x.get("years"), lambda x: (x.get("start_date") or "").replace("/", "-"))
        for mi, pi in pairs:
            mit, pit = we[mi], new_items[pi]
            matched.add(mi)
            m_comp = _clean_md(mit.get("company"))
            m_start_ym = _parse_master_years(mit.get("years"))
            p_start_ym = _plat_start_ym(pit)
            time_matched = bool(m_start_ym and p_start_ym and m_start_ym == p_start_ym)
            if m_comp:
                pit["company"] = m_comp
            elif time_matched and pit.get("company"):
                # 工作时间一致且平台已有公司名（如自由职业者），安全保留
                pass
            m_title = _clean_md(mit.get("title"))
            if m_title:
                pit["position"] = m_title
            desc = _clean_md(mit.get("description"))
            if desc:
                pit["responsibilities"] = desc
            st, en = _parse_years(mit.get("years"))
            if st:
                pit["start_date"] = _fmt_ym(st)
            if en:
                pit["end_date"] = _fmt_ym(en)

        # 若主简历条目多于平台条目，新增条目
        for mi, mit in enumerate(we):
            if mi not in matched:
                st, en = _parse_years(mit.get("years"))
                new_company = _clean_md(mit.get("company"))
                if not new_company:
                    # 不编造占位公司名（违反"不得编造主简历里没有的内容"红线），留空交人工补充
                    warnings.append("主简历某段工作经历无公司名，新增条目 company 留空，请人工补充")
                new_entry = {
                    "company": new_company,
                    "position": _clean_md(mit.get("title")) or "",
                    "job_category": "",
                    "department": "",
                    "start_date": _fmt_ym(st),
                    "end_date": _fmt_ym(en) or "至今",
                    "responsibilities": _clean_md(mit.get("description")) or "",
                    "industry": "",
                    "work_city": "",
                    "report_to": "",
                    "is_internship": False,
                    "hide_resume": False,
                    "team_size": "",
                    "salary_amount": "",
                    "salary_months": "",
                }
                new_items.append(new_entry)
        _emit_array("work_experience", new_items, "覆盖 company/position/responsibilities/起止时间")

    # 3) 项目经历
    pj = data.get("personalProjects") or data.get("projects") or []
    plat_pj = (fields_data.get("projects") or {}).get("current_value") or []
    if pj:
        new_items = []
        if plat_pj and all(isinstance(x, dict) for x in plat_pj):
            new_items = json.loads(json.dumps(plat_pj))
        matched = set()
        pairs = _pair_entries(pj, new_items, lambda x: x.get("years"), lambda x: (x.get("start_date") or "").replace("/", "-"))
        for mi, pi in pairs:
            mit, pit = pj[mi], new_items[pi]
            matched.add(mi)
            m_name = _clean_md(mit.get("name"))
            if m_name:
                pit["project_name"] = m_name
            m_role = _clean_md(mit.get("role"))
            if m_role:
                pit["role"] = m_role
            desc_s, resp_s, ach_s = _split_project_sections(mit.get("description"))
            if desc_s:
                pit["description"] = desc_s
            if resp_s:
                pit["responsibilities"] = resp_s
            if ach_s:
                pit["achievements"] = ach_s
            st, en = _parse_years(mit.get("years"))
            if st:
                pit["start_date"] = _fmt_ym(st)
            if en:
                pit["end_date"] = _fmt_ym(en)

        for mi, mit in enumerate(pj):
            if mi not in matched:
                st, en = _parse_years(mit.get("years"))
                desc_s, resp_s, ach_s = _split_project_sections(mit.get("description"))
                new_entry = {
                    "project_name": _clean_md(mit.get("name")) or "",
                    "company": "",
                    "role": _clean_md(mit.get("role")) or "",
                    "start_date": _fmt_ym(st),
                    "end_date": _fmt_ym(en) or "至今",
                    "description": desc_s,
                    "responsibilities": resp_s,
                    "achievements": ach_s,
                }
                new_items.append(new_entry)
        _emit_array("projects", new_items, "覆盖 project_name/role/description/responsibilities/achievements/起止时间")

    # 4) 教育经历
    ed = data.get("education") or []
    plat_ed = (fields_data.get("education") or {}).get("current_value") or []
    if ed:
        new_items = []
        if plat_ed and all(isinstance(x, dict) for x in plat_ed):
            new_items = json.loads(json.dumps(plat_ed))
        matched = set()
        pairs = _pair_entries(ed, new_items, lambda x: x.get("years"), lambda x: (x.get("start_date") or "").replace("/", "-"))
        for mi, pi in pairs:
            mit, pit = ed[mi], new_items[pi]
            matched.add(mi)
            if _clean_md(mit.get("institution")):
                pit["school"] = _clean_md(mit["institution"])
            if _clean_md(mit.get("major")):
                pit["major"] = _clean_md(mit["major"])
            if _clean_md(mit.get("degree")):
                pit["degree"] = _clean_md(mit["degree"])
            st, en = _parse_years(mit.get("years"))
            if st:
                pit["start_date"] = _fmt_ym(st)
            if en:
                pit["end_date"] = _fmt_ym(en)

        # 追加主简历多出的教育经历（如新增第二学历/平台为空账号），绝不静默丢弃；
        # 同名学校已在平台条目中（时间格式差异导致未配对）时不重复追加
        for mi, mit in enumerate(ed):
            if mi not in matched:
                m_school = _clean_md(mit.get("institution"))
                if m_school and any(m_school == str(x.get("school") or "").strip() for x in new_items):
                    continue
                st, en = _parse_years(mit.get("years"))
                new_items.append({
                    "school": m_school or "",
                    "major": _clean_md(mit.get("major")) or "",
                    "degree": _clean_md(mit.get("degree")) or "",
                    "start_date": _fmt_ym(st),
                    "end_date": _fmt_ym(en) or "至今",
                })
        _emit_array("education", new_items, "覆盖 school/major/degree/起止时间")

    # 5) 基本信息
    pi_data = data.get("personalInfo") or {}
    if pi_data.get("name"):
        fields.append({"path": "basic_info.name", "value": _clean_md(pi_data["name"]), "confidence": "high", "source": "personalInfo", "note": "规则映射", "type": "object-field"})
    if pi_data.get("phone"):
        fields.append({"path": "basic_info.phone", "value": _clean_md(pi_data["phone"]), "confidence": "high", "source": "personalInfo", "note": "规则映射", "type": "object-field"})
    if pi_data.get("email"):
        fields.append({"path": "basic_info.email", "value": _clean_md(pi_data["email"]), "confidence": "high", "source": "personalInfo", "note": "规则映射", "type": "object-field"})

    report = {"success": True, "platform": "liepin", "fields": fields,
              "unfilled": unfilled, "warnings": warnings}
    report = _attach_changed_flags(report, fields_data)
    report = _attach_translations(report, fields_data)
    report = _ensure_unfilled_fields(report, fields_data)
    report = _attach_field_options(report, "liepin")
    report["message"] = "规则映射完成：%d 项填入，%d 项待人工" % (len(fields), len(unfilled))
    return report


def map_platform_rules(platform: str, fields_data: dict, master: dict, llm_error: str = "", selected_modules: list[str] = None) -> dict:
    """
    确定性规则映射（当前实现 51job/智联/猎聘）：主简历最新内容覆盖平台文本/时间字段，
    主简历没有的保留平台原值；选项类字段（求职意向/技能代码/语言/证书）不动。
    作为 LLM 不可用（无 Key/余额不足/调用失败）时的兜底，保证映射闭环可用。
    """
    if platform == "51job":
        rep = _rule_map_51job(fields_data, master, llm_error)
    elif platform == "zhilian":
        rep = _rule_map_zhilian(fields_data, master, llm_error)
    elif platform == "liepin":
        rep = _rule_map_liepin(fields_data, master, llm_error)
    else:
        # 未知平台/BOSS：不再静默套用 51job 规则产出错误字段形状的报告
        return {"success": False, "platform": platform, "fields": [], "unfilled": [],
                "warnings": [], "message": f"该平台暂无规则映射兜底（LLM 不可用: {llm_error or '未配置'}）"}

    if selected_modules and len(selected_modules) > 0:
        sel_set = set(selected_modules)
        rep["fields"] = [f for f in rep.get("fields", []) if _field_path_to_module(f.get("path", "")) in sel_set]
        rep["unfilled"] = [u for u in rep.get("unfilled", []) if _field_path_to_module(u.get("path", "")) in sel_set]
    return rep


def _zh_ts(ym: str) -> int:
    """'2024-04' → 毫秒时间戳（当月 1 日 00:00，本地时区）"""
    y, mo = ym.split("-")
    return int(datetime(int(y), int(mo), 1).timestamp() * 1000)


def _zh_fmt(ym: str) -> str:
    """'2024-04' → '2024/04/01 00:00:00'（智联官网 DateFormat 格式）"""
    y, mo = ym.split("-")
    return "%s/%02d/01 00:00:00" % (y, int(mo))


_ZH_EPOCH_FMT = "1970/01/01 08:00:00"  # 官网对「至今」条目的结束日期占位值（实测）
_ZH_SELF_EVAL_MAX = 500  # 官网实测超限保存静默失败


def _is_real_zh_fmt(v) -> bool:
    """DateFormat 是否已是真实日期串（'2024/04/01 00:00:00'），而非占位符（'YYYY.MM'）"""
    return bool(v) and re.match(r"^\d{4}/", str(v)) is not None


def _ts_to_ym(ts) -> str:
    """毫秒时间戳 → 'YYYY-MM'"""
    try:
        return datetime.fromtimestamp(int(ts) / 1000).strftime("%Y-%m")
    except Exception:
        return ""


def _zh_date_pairs_for(module: str) -> list:
    """模块 → (日期键, 格式键) 对列表"""
    if module == "work_experience":
        return [("startDate", "startDateFormat"), ("endDate", "endDateFormat")]
    if module == "projects":
        return [("proExpStartDate", "proExpStartDateFormat"), ("proExpEndDate", "proExpEndDateFormat")]
    if module == "education":
        return [("eduStartDate", "eduStartDateFormat"), ("eduEndDate", "eduEndDateFormat")]
    return []


def _normalize_zhilian_dates(report: dict) -> dict:
    """
    智联日期格式纠正（LLM 路径专用）：AI 可能把日期输出为人话格式（'2024.04'/'至今'）
    或占位符（'YYYY.MM'），而官网只认毫秒时间戳 + 真实日期串（'2024/04/01 00:00:00'）。
    此步骤把 work_experience/projects/education 的日期统一转成官网机器格式；
    已是正确时间戳的不动（幂等）。
    """
    for f in report.get("fields", []):
        pairs = _zh_date_pairs_for(f.get("path"))
        if not pairs:
            continue
        items = f.get("value")
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for date_key, fmt_key in pairs:
                v = item.get(date_key)
                if isinstance(v, (int, float)):
                    if v > 0:
                        # 已是有效时间戳：仅确保格式串是真实日期（占位符则补写）
                        if not _is_real_zh_fmt(item.get(fmt_key)):
                            ym = _ts_to_ym(v)
                            if ym:
                                item[fmt_key] = _zh_fmt(ym)
                    elif date_key.startswith("end") or "End" in date_key:
                        # 结束时间戳 0 = 「至今」：格式串补写官网占位串
                        if not _is_real_zh_fmt(item.get(fmt_key)):
                            item[fmt_key] = _ZH_EPOCH_FMT
                    continue
                s = str(v or "").strip()
                if not s:
                    continue
                if s in ("至今", "现在", "present", "now"):
                    if date_key.startswith("end") or "End" in date_key:
                        item[date_key] = 0
                        item[fmt_key] = _ZH_EPOCH_FMT
                    continue
                ym = _norm_ym_key(s)
                if re.match(r"^\d{4}-\d{2}$", ym):
                    item[date_key] = _zh_ts(ym)
                    item[fmt_key] = _zh_fmt(ym)
                # 无法解析的保持原样（交给人工）
    return report


_ZHILIAN_WORK_SKILLS_CACHE = None


def _get_zhilian_job_skills(job_type_id: str) -> list:
    """按职位代码获取智联官方工作技能标签预设字典"""
    global _ZHILIAN_WORK_SKILLS_CACHE
    if _ZHILIAN_WORK_SKILLS_CACHE is None:
        skills_file = os.path.join(DATA_DIR, "zhilian_work_skills_progress.json")
        if os.path.exists(skills_file):
            try:
                with open(skills_file, "r", encoding="utf-8") as f:
                    _ZHILIAN_WORK_SKILLS_CACHE = json.load(f)
            except Exception as e:
                logger.warning(f"加载智联工作技能字典失败: {e}")
                _ZHILIAN_WORK_SKILLS_CACHE = {}
        else:
            _ZHILIAN_WORK_SKILLS_CACHE = {}
    cache = _ZHILIAN_WORK_SKILLS_CACHE or {}
    entry = cache.get(str(job_type_id))
    if entry and isinstance(entry.get("skills"), list):
        return entry["skills"]
    return []


def _normalize_zhilian_work_skills(report: dict) -> dict:
    """
    智联工作经历技能两阶段精准对齐：
    1. 提取大模型/主简历产出的所有候选技能词；
    2. 根据经历职位代码 (wnewJobSubType/jobTypeId/jobSubType) 读取该职位的官方标准技能预设组；
    3. 命中标准预设组的词：挂载真实 skillId 与对应分类 pathId（每组受 maxCount 限制）；
    4. 未命中标准预设组的词：归入「自定义技能」（上限 3 个，分配 9 位安全 ID，pathId: -1）；
    5. 全量同步生成符合智联官网与前端规范的 skillTagList / skillTags / preferenceQuestionAndAnswer / skillTagStandard / skillTagCustomized / skillTagsTranslation。
    """
    for f in report.get("fields", []):
        if f.get("path") != "work_experience" or not isinstance(f.get("value"), list):
            continue
        for idx, it in enumerate(f["value"]):
            if not isinstance(it, dict):
                continue

            # 1. 提取所有候选技能关键词（去重并保序）
            candidate_names = []
            seen_names = set()

            # 来源 A: skillTagList
            raw_list = it.get("skillTagList")
            if isinstance(raw_list, list):
                for s in raw_list:
                    if isinstance(s, dict):
                        name = str(s.get("name") or s.get("tagValue") or "").strip()
                    else:
                        name = str(s or "").strip()
                    if name and name.lower() not in seen_names:
                        seen_names.add(name.lower())
                        candidate_names.append(name)

            # 来源 B: skills
            raw_skills = it.get("skills")
            if isinstance(raw_skills, list):
                for s in raw_skills:
                    name = str(s.get("skill") if isinstance(s, dict) else (s or "")).strip()
                    if name and name.lower() not in seen_names:
                        seen_names.add(name.lower())
                        candidate_names.append(name)

            # 来源 C: skillTags (JSON 字符串或列表)
            raw_tags = it.get("skillTags")
            if isinstance(raw_tags, str) and raw_tags.strip().startswith("["):
                try:
                    parsed_tags = json.loads(raw_tags)
                    if isinstance(parsed_tags, list):
                        for s in parsed_tags:
                            name = str(s.get("tagValue") or s.get("name") or "").strip() if isinstance(s, dict) else str(s).strip()
                            if name and name.lower() not in seen_names:
                                seen_names.add(name.lower())
                                candidate_names.append(name)
                except Exception:
                    pass
            elif isinstance(raw_tags, list):
                for s in raw_tags:
                    name = str(s.get("tagValue") or s.get("name") or "").strip() if isinstance(s, dict) else str(s).strip()
                    if name and name.lower() not in seen_names:
                        seen_names.add(name.lower())
                        candidate_names.append(name)

            # 来源 D: skillTagsTranslation
            raw_trans = str(it.get("skillTagsTranslation") or "").strip()
            if raw_trans:
                for name in re.split(r"[,，、;；]", raw_trans):
                    n = name.strip()
                    if n and n.lower() not in seen_names:
                        seen_names.add(n.lower())
                        candidate_names.append(n)

            if not candidate_names:
                continue

            # 2. 读取该职位预设技能
            job_type_id = str(it.get("wnewJobSubType") or it.get("jobTypeId") or it.get("newJobSubType") or it.get("jobSubType") or "").strip()
            preset_groups = _get_zhilian_job_skills(job_type_id) if job_type_id else []

            group_limits = {}
            group_counts = {}
            standard_map = {}
            for g in preset_groups:
                if g.get("isIndustry") or not g.get("children"):
                    continue
                gid = g.get("id")
                max_c = g.get("maxCount") or 3
                group_limits[gid] = max_c
                group_counts[gid] = 0
                for opt in g.get("children", []):
                    opt_name = str(opt.get("name") or "").strip()
                    if opt_name:
                        standard_map[opt_name.lower()] = {
                            "id": str(opt.get("id")),
                            "name": opt_name,
                            "groupId": gid,
                        }

            matched_standard = []
            custom_candidates = []

            for name in candidate_names:
                low_name = name.lower()
                if low_name in standard_map:
                    info = standard_map[low_name]
                    gid = info["groupId"]
                    if group_counts[gid] < group_limits.get(gid, 3):
                        group_counts[gid] += 1
                        matched_standard.append({
                            "skillId": info["id"],
                            "name": info["name"],
                            "customize": False,
                            "skillParentId": str(gid)
                        })
                    else:
                        custom_candidates.append(name)
                else:
                    custom_candidates.append(name)

            # 3. 自定义技能最多 3 个
            matched_custom = []
            max_custom = 3
            for c_idx, name in enumerate(custom_candidates[:max_custom]):
                new_id = 300000000 + (idx * 100) + c_idx
                matched_custom.append({
                    "skillId": str(new_id),
                    "name": name,
                    "customize": True,
                    "skillParentId": "-1"
                })

            final_tag_list = matched_standard + matched_custom

            # 4. 回写结构化字段
            it["skillTagList"] = final_tag_list
            it["skills"] = [s["name"] for s in final_tag_list]
            it["skillTagsTranslation"] = ",".join(s["name"] for s in final_tag_list)
            it["skillTagStandard"] = ",".join(s["skillId"] for s in matched_standard)
            it["skillTagCustomized"] = ",".join(s["name"] for s in matched_custom)
            it["preferenceQuestionAndAnswer"] = json.dumps([
                {"id": int(s["skillId"]), "pathId": int(s.get("skillParentId", -1))}
                for s in final_tag_list
            ], ensure_ascii=False)
            it["skillTags"] = json.dumps([
                {
                    "intKey": int(s["skillId"]),
                    "standard": not s.get("customize", False),
                    "strKey": s["skillId"],
                    "tagValue": s["name"]
                }
                for s in final_tag_list
            ], ensure_ascii=False)

    return report


def _rule_map_zhilian(fields_data: dict, master: dict, llm_error: str = "") -> dict:
    """
    智联确定性规则映射：覆盖自我评价文本 + 工作/项目/教育的文本与日期；
    求职意向/专业技能/语言/培训/证书为选项类字段不动。
    日期同时写毫秒时间戳 + DateFormat 格式串（官网组件两种形态都有消费）。
    """
    data = master.get("data") or {}
    fields, unfilled, warnings = [], [], []
    warnings.append(
        "⚠️ 已降级为确定性规则映射（LLM 不可用：%s），字段覆盖范围有限，请重点核对。仅覆盖自我评价/工作经历/项目经历/教育经历的文本与日期字段；求职意向、专业技能、语言能力、培训经历、资格证书保留官网原值" % (llm_error or "未配置")
    )
    logger.warning("[映射降级] 智联规则映射触发，原因: %s", llm_error or "未配置 LLM API Key")

    # 1) 自我评价 ← summary（官网上限 500 字，超限静默失败）
    summary = _clean_md(data.get("summary"))
    if summary:
        if len(summary) > _ZH_SELF_EVAL_MAX:
            warnings.append("自我评价超出智联 500 字上限，已截断适配")
            summary = summary[:_ZH_SELF_EVAL_MAX]
        fields.append({"path": "self_evaluation", "value": summary, "confidence": "high",
                       "source": "master.summary", "note": "规则映射", "type": "textarea"})

    def _emit_array(path, items, note):
        fields.append({"path": path, "value": items, "confidence": "high",
                       "source": "master", "note": note, "type": "array"})

    def _fmt_start(key):
        return lambda pit: ((pit.get(key) or "")[:7]).replace("/", "-") or None

    # 2) 工作经历
    we = data.get("workExperience") or []
    plat_we = fields_data.get("workExperience") if isinstance(fields_data.get("workExperience"), list) else ((fields_data.get("work_experience") or {}).get("current_value") or [])
    if we:
        if plat_we and all(isinstance(x, dict) for x in plat_we):
            new_items = json.loads(json.dumps(plat_we))
        else:
            new_items = []
        matched = set()
        for mi, pi in _pair_entries(we, new_items, lambda x: x.get("years"), _fmt_start("startDateFormat")):
            mit, pit = we[mi], new_items[pi]
            matched.add(mi)
            if _clean_md(mit.get("company")):
                pit["companyName"] = _clean_md(mit["company"])
            if _clean_md(mit.get("title")):
                pit["jobTitle"] = _clean_md(mit["title"])
                pit["title"] = _clean_md(mit["title"])
            desc = _master_desc_text(mit) or _clean_md(mit.get("description"))
            if desc:
                pit["workDesc"] = desc
            st, en = _parse_years(mit.get("years"))
            if st:
                pit["startDate"] = _zh_ts(st)
                pit["startDateFormat"] = _zh_fmt(st)
            if en and en != "至今":
                pit["endDate"] = _zh_ts(en)
                pit["endDateFormat"] = _zh_fmt(en)
            elif en == "至今":
                pit["endDate"] = 0
                pit["endDateFormat"] = _ZH_EPOCH_FMT
        _emit_array("work_experience", new_items, "覆盖 companyName/jobTitle/workDesc/起止日期")
        for mi, mit in enumerate(we):
            if mi not in matched:
                unfilled.append({"path": "work_experience",
                                 "label": "工作经历·%s" % (_clean_md(mit.get("company") or mit.get("title")) or mi + 1),
                                 "reason": "智联无对应条目，请手动添加"})

    # 3) 项目经历
    pj = data.get("personalProjects") or []
    plat_pj = (fields_data.get("project") if isinstance(fields_data.get("project"), list)
               else (fields_data.get("projectExperience") if isinstance(fields_data.get("projectExperience"), list)
                     else ((fields_data.get("projects") or {}).get("current_value") or [])))
    if pj:
        if plat_pj and all(isinstance(x, dict) for x in plat_pj):
            new_items = json.loads(json.dumps(plat_pj))
        else:
            new_items = []
        matched = set()
        for mi, pi in _pair_entries(pj, new_items, lambda x: x.get("years"), _fmt_start("proExpStartDateFormat")):
            mit, pit = pj[mi], new_items[pi]
            matched.add(mi)
            if _clean_md(mit.get("name")):
                pit["proExpProjectName"] = _clean_md(mit["name"])
            desc = _master_desc_text(mit) or _clean_md(mit.get("description"))
            if desc:
                pit["proExpProjectDesc"] = desc
            st, en = _parse_years(mit.get("years"))
            if st:
                pit["proExpStartDate"] = _zh_ts(st)
                pit["proExpStartDateFormat"] = _zh_fmt(st)
            if en and en != "至今":
                pit["proExpEndDate"] = _zh_ts(en)
                pit["proExpEndDateFormat"] = _zh_fmt(en)
            elif en == "至今":
                pit["proExpEndDate"] = 0
                pit["proExpEndDateFormat"] = _ZH_EPOCH_FMT
        _emit_array("projects", new_items, "覆盖 proExpProjectName/proExpProjectDesc/起止日期")
        for mi, mit in enumerate(pj):
            if mi not in matched:
                unfilled.append({"path": "projects",
                                 "label": "项目·%s" % (_clean_md(mit.get("name")) or mi + 1),
                                 "reason": "智联无对应条目，请手动添加"})

    # 4) 教育经历（eduBackground 为平台选项代码，不覆盖）
    ed = data.get("education") or []
    plat_ed = fields_data.get("education") if isinstance(fields_data.get("education"), list) else ((fields_data.get("education") or {}).get("current_value") or [])
    if ed:
        if plat_ed and all(isinstance(x, dict) for x in plat_ed):
            new_items = json.loads(json.dumps(plat_ed))
        else:
            new_items = []
        matched = set()
        for mi, pi in _pair_entries(ed, new_items, lambda x: x.get("years"), _fmt_start("eduStartDateFormat")):
            mit, pit = ed[mi], new_items[pi]
            matched.add(mi)
            if _clean_md(mit.get("institution")):
                pit["eduSchoolName"] = _clean_md(mit["institution"])
            if _clean_md(mit.get("major")):
                pit["eduMajorV"] = _clean_md(mit["major"])
            st, en = _parse_years(mit.get("years"))
            if st:
                pit["eduStartDate"] = _zh_ts(st)
                pit["eduStartDateFormat"] = _zh_fmt(st)
            if en and en != "至今":
                pit["eduEndDate"] = _zh_ts(en)
                pit["eduEndDateFormat"] = _zh_fmt(en)
            elif en == "至今":
                pit["eduEndDate"] = 0
                pit["eduEndDateFormat"] = _ZH_EPOCH_FMT
        _emit_array("education", new_items, "覆盖 eduSchoolName/eduMajorV/起止日期（eduBackground 代码保留）")
        for mi, mit in enumerate(ed):
            if mi not in matched:
                unfilled.append({"path": "education",
                                 "label": "教育·%s" % (_clean_md(mit.get("institution")) or mi + 1),
                                 "reason": "智联无对应条目，请手动添加"})

    # 5) 基本信息（姓名/性别等开放字段映射，锁定/敏感字段不覆盖）
    pi_data = data.get("personalInfo") or {}
    if pi_data.get("name"):
        fields.append({"path": "name", "value": _clean_md(pi_data["name"]), "confidence": "high",
                       "source": "master.personalInfo.name", "note": "规则映射", "type": "text"})
    if pi_data.get("gender"):
        g_raw = _clean_md(pi_data["gender"])
        g_val = "1" if g_raw in ("男", "1") else ("2" if g_raw in ("女", "2") else g_raw)
        fields.append({"path": "gender", "value": g_val, "confidence": "high",
                       "source": "master.personalInfo.gender", "note": "规则映射", "type": "select"})

    report = {"success": True, "platform": "zhilian", "fields": fields,
              "unfilled": unfilled, "warnings": warnings}
    # 后处理管线对齐：unfilled 补全 + 下拉选项 + 翻译（长度扫描已有）
    report = _ensure_unfilled_fields(report, fields_data)
    report = _attach_field_options(report, "zhilian")
    report = _attach_translations(report, fields_data)
    report = _check_field_length_limits(report, "zhilian")
    report = _attach_changed_flags(report, fields_data)
    report["message"] = "规则映射完成：%d 项填入，%d 项待人工" % (len(fields), len(unfilled))
    return report


def _repair_llm_json(s: str):
    """尝试解析；失败则修复开源模型常见坏输出（JSON 字符串内嵌入字面换行/制表符）后重试。
    解析成功返回 dict，否则返回 None。"""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    out, in_str, esc = [], False, False
    for ch in s:
        if in_str:
            if esc:
                out.append(ch)
                esc = False
            elif ch == "\\":
                out.append(ch)
                esc = True
            elif ch == '"':
                out.append(ch)
                in_str = False
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
    try:
        return json.loads("".join(out))
    except json.JSONDecodeError:
        return None


def _normalize_unprovided_warnings(report: dict) -> dict:
    """警告文本归一（用户需求）：凡"主简历未提供"的场景，实际行为都是保留平台原值
    （数组合并保护保证空值不覆盖非空原值；原值本为空的字段保留空 = 保留现有值）。
    LLM 自述的"已填空字符串"会误导用户以为清空了数据，统一改写。"""
    warnings = report.get("warnings") or []
    report["warnings"] = [
        w.replace("已填空字符串，需人工从平台类目中选择", "主简历未提供，已保留平台现有值，需人工从平台类目中选择")
         .replace("已填空字符串，需人工选择", "主简历未提供，已保留平台现有值，需人工选择")
         .replace("已填空字符串", "主简历未提供，已保留平台现有值")
        if isinstance(w, str) else w
        for w in warnings
    ]
    return report


# 「待人工补充」告警特征词：命中即视为需要人工介入的条目
_MANUAL_REVIEW_MARKERS = ("需人工", "建议人工核对", "请人工核对")


def _derive_unfilled_from_warnings(report: dict) -> dict:
    """
    「待人工补充」兜底（用户反馈 2026-08-30）：代码侧产生的「需人工…」告警
    （职位枚举无法精确匹配需人工选择、沿用现有值建议人工核对等）此前只进 warnings，
    LLM 本次又没输出 unfilled 时，前端「待人工补充」区块整块缺失（boss 实测）。
    此步把带路径前缀的需人工告警同步为 unfilled 条目（按 path+reason 去重），
    使四平台报告的待人工区块语义一致。全局性告警（无可识别路径前缀）仍留在映射提示。
    """
    unfilled = list(report.get("unfilled") or [])
    seen = {(str(u.get("path", "")), str(u.get("reason", ""))) for u in unfilled}
    for w in report.get("warnings") or []:
        if not isinstance(w, str) or not any(m in w for m in _MANUAL_REVIEW_MARKERS):
            continue
        head = re.split(r"[：:]", w, 1)[0].strip()
        m = re.match(r"^[a-zA-Z_][A-Za-z0-9_]*", head)
        if not m:
            continue
        path = m.group(0)
        key = (path, w)
        if key in seen:
            continue
        seen.add(key)
        unfilled.append({"path": path, "label": path, "reason": w})
    if unfilled:
        report["unfilled"] = unfilled
    return report


def _postprocess_mapping_report(report: dict, fields_data: dict, master: dict, platform: str, selected_modules: list[str] | None = None) -> dict:
    """
    LLM 映射后置处理流水线（生成路径）：逐步对 report 做规范化/兜底/选项附加。

    健壮性红线：每一步变换函数必须返回非 None 的 dict；任何一步返回 None
    立即抛出带步骤名的 RuntimeError（防止类似 _dedup 漏写 return 的缺陷
    把 None 静默传递到下游，被外层 except 误判为 LLM 不可用而静默降级）。
    """
    steps = [
        ("normalize_array_items", lambda r: _normalize_array_items(r)),
        ("normalize_object_fields", lambda r: _normalize_object_fields(r)),
        ("strip_markdown", lambda r: _strip_markdown(r, platform)),
        ("enforce_verbatim_description", lambda r: _enforce_verbatim_description(r, platform, master)),
        # 业绩剥离去重（用户规则 2026-08-30 修订）：字段分流后各段本就严格互斥，本步只兜底
        # 清理 LLM 自行复制导致的「项目描述与项目业绩重复」，满足「跨字段内容不重复」；
        # 开头词标签已改为整行原文保留，不再有任何按关键词的删减。
        ("dedup_achievements_from_description", lambda r: _dedup_achievements_from_description(r, platform)),
        ("fallback_skills", lambda r: _fallback_skills(r, master)),
        # LLM 清空期望时沿用平台现有值
        ("fallback_expectations", lambda r: _fallback_expectations(r, fields_data, selected_modules=selected_modules)),
        # 空值保护：主简历未提及 → 保留官网原值 + 警告
        ("preserve_empty_platform_values", lambda r: _preserve_empty_platform_values(r, fields_data, platform)),
        # 未提及模块保护：意向/选项类整体全空 → 保留平台原值 + 转 unfilled
        ("protect_unmentioned_modules", lambda r: _protect_unmentioned_modules(r, fields_data, platform, selected_modules=selected_modules)),
        # 覆盖语义兜底：自述字段必须用主简历 summary
        ("enforce_self_text_overwrite", lambda r: _enforce_self_text_overwrite(r, fields_data, master, platform)),
        # 期望职位类型上限兜底：全职≤3、兼职≤1（仅含 jobType 的平台）
        ("trim_expectations", lambda r: _trim_expectations(r)),
        ("sort_array_items_by_start_desc", lambda r: _sort_array_items_by_start_desc(r)),
    ]
    if platform == "liepin":
        # 经历字段完整性防御：若 LLM 偶发遗漏数组字段，自动用规则映射引擎补全该模块
        steps.insert(0, ("liepin_rule_fill_experiences", lambda r: _liepin_rule_fill_experiences(r, fields_data, master, selected_modules=selected_modules)))
    if platform == "51job":
        steps.extend([
            # 项目单时间点 → 结束时间默认同月
            ("enforce_51job_single_project_end", lambda r: _enforce_51job_single_project_end(r, master)),
            # 职位类目：主简历职位名精确匹配官方职位列表
            ("map_51job_work_function", lambda r: _map_51job_work_function(r, master)),
            # 专业技能：匹配官方 IT 技能库与熟练度
            ("map_51job_skills", lambda r: _map_51job_skills(r, master)),
        ])
    if platform == "zhilian":
        # 日期格式纠正：AI 可能输出人话日期（'2024.04'/'至今'），转官网机器格式
        steps.append(("normalize_zhilian_dates", lambda r: _normalize_zhilian_dates(r)))
        # 经历技能规范化：双轨制对齐预设标准词 + 自定义上限3个分流
        steps.append(("normalize_zhilian_work_skills", lambda r: _normalize_zhilian_work_skills(r)))
    steps.extend([
        ("fallback_certificates", lambda r: _fallback_certificates(r, fields_data, selected_modules=selected_modules)),
        # 字段字数上限硬性扫描与多级强预警
        ("check_field_length_limits", lambda r: _check_field_length_limits(r, platform)),
        # 变更标记：对比官网原值，前端显示「已变更」徽章（须在所有值定型步骤之后）
        ("attach_changed_flags", lambda r: _attach_changed_flags(r, fields_data)),
        ("attach_translations", lambda r: _attach_translations(r, fields_data)),
        ("attach_field_options", lambda r: _attach_field_options(r, platform)),
        ("validate_option_consistency", lambda r: _validate_option_consistency(r, platform)),
        # 「主简历未提供」警告文本归一：数组合并保护已保证空值不会覆盖平台原值，
        # LLM 自述的"已填空字符串"与实际行为不符，统一改写为"已保留平台现有值"
        ("normalize_unprovided_warnings", lambda r: _normalize_unprovided_warnings(r)),
        # 「待人工补充」兜底：需人工告警同步为 unfilled 条目（LLM 未输出 unfilled 时区块不再缺失）
        ("derive_unfilled_from_warnings", lambda r: _derive_unfilled_from_warnings(r)),
    ])
    for step_name, fn in steps:
        result = fn(report)
        if not isinstance(result, dict):
            raise RuntimeError(f"后置处理步骤 {step_name} 返回了非 dict 值（{type(result).__name__}），请检查该函数是否所有分支都有 return")
        report = result

    if selected_modules and len(selected_modules) > 0:
        sel_set = set(selected_modules)
        report["fields"] = [f for f in report.get("fields", []) if _field_path_to_module(f.get("path", "")) in sel_set]
        report["unfilled"] = [u for u in report.get("unfilled", []) if _field_path_to_module(u.get("path", "")) in sel_set]

    return report


def _liepin_rule_fill_experiences(report: dict, fields_data: dict, master: dict, selected_modules: list[str] | None = None) -> dict:
    """猎聘经历字段完整性防御：LLM 偶发遗漏经历数组时，用规则映射引擎补全该模块"""
    field_paths = {f.get("path") for f in report.get("fields", [])}
    rule_report = _rule_map_liepin(fields_data, master, "大模型未完整返回经历字段", selected_modules=selected_modules)
    for rf in rule_report.get("fields", []):
        if rf.get("path") in ("work_experience", "projects", "education") and rf.get("path") not in field_paths:
            if selected_modules is None or _field_path_to_module(rf.get("path")) in selected_modules:
                report.setdefault("fields", []).append(rf)
                report.setdefault("warnings", []).append(f"{rf.get('path')} 未在 LLM 返回中找到，已自动由规则映射引擎补全对齐")
    return report


def map_platform(platform: str, fields_data: dict, master: dict, cfg: dict = None, selected_modules: list[str] = None) -> dict:
    """
    对单平台执行 LLM 映射，返回执行报告：
      {"success": bool, "platform", "fields", "unfilled", "warnings", "message"}
    """
    cfg = cfg if cfg is not None else load_env_config()
    platform_labels = {"boss": "BOSS直聘", "liepin": "猎聘", "51job": "前程无忧", "zhilian": "智联招聘"}

    api_key = cfg.get("OPENAI_API_KEY", "")
    base_url = cfg.get("OPENAI_BASE_URL", "")
    model = cfg.get("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        if platform in ("51job", "zhilian", "liepin") and master.get("ok"):
            return map_platform_rules(platform, fields_data, master, "未配置 LLM API Key", selected_modules=selected_modules)
        return {"success": False, "platform": platform, "fields": [], "unfilled": [],
                "warnings": [], "message": "未配置 LLM API Key"}
    if not master.get("ok"):
        return {"success": False, "platform": platform, "fields": [], "unfilled": [],
                "warnings": [], "message": master.get("message", "主简历不可用")}

    schema = flatten_schema(fields_data, selected_modules=selected_modules)
    # 数据完整性防御：全量生成时字段异常稀少（正常 10+），多为未采集/数据不完整
    # （如采集失败后残留的单模块文件），明确警告避免用户困惑"为什么只映射了 1 个字段"
    low_data_warning = None
    if len(schema) < 3 and not selected_modules:
        low_data_warning = (
            f"⚠️ 该平台本地数据仅有 {len(schema)} 个字段（正常应有 10+），可能未完成采集或历史数据不完整；"
            "请先在对应平台完成「采集数据」后再重新生成映射，否则映射覆盖范围极其有限"
        )
    options_text = _build_options_prompt_text(platform)
    prompt = build_mapping_prompt(platform, platform_labels.get(platform, platform),
                                 master_payload(master), schema, options_text)
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=45.0)
        parsed = None
        last_content = ""
        last_err = None
        for attempt in range(3):  # JSON 解析失败与网络异常均重试（上限 3 次）
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    max_tokens=32768,  # 映射输出约 5k token，思考型模型会额外消耗输出预算，需留足上限
                )
            except Exception as api_err:
                last_err = api_err
                logger.warning("[映射] %s LLM 调用异常（第 %s 次）: %s", platform, attempt + 1, api_err)
                continue
            # 截断检测：finish_reason=length 时输出被 max_tokens 截断，重试无意义但需明示
            finish = getattr(resp.choices[0], "finish_reason", "") or ""
            content = (resp.choices[0].message.content or "").strip()
            last_content = content
            m = re.search(r"\{[\s\S]*\}", content)
            if m:
                parsed = _repair_llm_json(m.group())  # 兼容字符串内字面换行等坏输出
                if parsed is not None:
                    if finish == "length":
                        logger.warning("[映射] %s LLM 输出被 max_tokens 截断（finish_reason=length），结果可能不完整", platform)
                    break
        if parsed is None:
            reason = f"LLM 调用异常: {last_err}" if last_err else "LLM 返回 JSON 无法解析"
            logger.error("[映射降级] %s %s，降级为确定性规则映射。LLM 输出前 500 字符: %s",
                         platform, reason, last_content[:500])
            if platform in ("51job", "zhilian", "liepin") and master.get("ok"):
                return map_platform_rules(platform, fields_data, master, reason, selected_modules=selected_modules)
            return {"success": False, "platform": platform, "fields": [], "unfilled": [],
                    "warnings": [], "message": f"BOSS 平台映射依赖 AI 模型，当前不可用（{reason}），请稍后重试或检查模型配置", "raw": last_content[:500]}
        report = validate_mapping_result(parsed, fields_data)
        report = _postprocess_mapping_report(report, fields_data, master, platform, selected_modules=selected_modules)
        report["success"] = True
        report["platform"] = platform
        report["selected_modules"] = selected_modules
        if low_data_warning:
            report.setdefault("warnings", []).insert(0, low_data_warning)
        report["message"] = f"映射完成：{len(report['fields'])} 项填入，{len(report['unfilled'])} 项待人工"
        return report
    except Exception as e:
        err_text = str(e)[:200]
        # 错误分类：把需要用户介入的问题明示出来，而不是笼统的"字段覆盖范围有限"
        if any(kw in err_text.lower() for kw in ("insufficient", "quota", "余额", "billing", "402")):
            user_msg = "AI 模型余额不足/配额耗尽，请检查模型服务账户后重试"
        elif any(kw in err_text.lower() for kw in ("auth", "api key", "401", "unauthorized")):
            user_msg = "AI 模型鉴权失败（API Key 无效或过期），请检查 OPENAI_API_KEY 配置"
        elif any(kw in err_text.lower() for kw in ("timeout", "timed out", "connection")):
            user_msg = "AI 模型连接超时，请检查网络后重试"
        else:
            user_msg = f"LLM 映射失败: {err_text}"
        logger.exception("[映射降级] %s LLM 映射流程异常，降级为确定性规则映射", platform)
        if platform in ("51job", "zhilian", "liepin") and master.get("ok"):
            return map_platform_rules(platform, fields_data, master, user_msg, selected_modules=selected_modules)
        return {"success": False, "platform": platform, "fields": [], "unfilled": [],
                "warnings": [], "message": f"BOSS 平台映射依赖 AI 模型，当前不可用（{user_msg}）"}

