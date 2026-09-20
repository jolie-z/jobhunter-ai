"""
字段映射配置 - 统一值 → 各平台翻译
用户只需选择一个"统一值"，系统自动翻译为各平台的对应选项。
"""

# ============ 求职状态映射 ============
# 统一值 → 各平台的具体选项文本
JOB_STATUS_MAPPING = {
    "离职-随时到岗": {
        "boss": "离职-随时到岗",
        "liepin": "离职，正在找工作",
        "51job": "离职-随时到岗",
        "zhilian": "离职",
    },
    "离职-考虑机会": {
        "boss": "离职-考虑机会",
        "liepin": "离职，考虑机会",
        "51job": "离职-周内到岗",
        "zhilian": "离职",
    },
    "在职-考虑机会": {
        "boss": "在职-考虑机会",
        "liepin": "在职，考虑机会",
        "51job": "在职-考虑机会",
        "zhilian": "在职，考虑机会",
    },
    "在职-暂不考虑": {
        "boss": "在职-暂不考虑",
        "liepin": "在职，暂不考虑",
        "51job": "在职-暂不考虑",
        "zhilian": "在职，暂不考虑",
    },
    "应届生": {
        "boss": "应届生",
        "liepin": "应届毕业生",
        "51job": "应届毕业生",
        "zhilian": "应届毕业生",
    },
}

# 反向映射：平台值 → 统一值（用于从平台数据反推统一值）
JOB_STATUS_REVERSE = {}
for unified_val, platform_vals in JOB_STATUS_MAPPING.items():
    for pid, pval in platform_vals.items():
        JOB_STATUS_REVERSE.setdefault(pid, {})[pval] = unified_val


# ============ 政治面貌映射 ============
POLITICAL_STATUS_MAPPING = {
    "共青团员": {
        "boss": "",  # BOSS无此字段
        "liepin": "共青团员",
        "51job": "共青团员",
        "zhilian": "团员",
    },
    "中共党员": {
        "boss": "",
        "liepin": "中共党员",
        "51job": "中共党员",
        "zhilian": "党员",
    },
    "中共预备党员": {
        "boss": "",
        "liepin": "中共预备党员",
        "51job": "中共预备党员",
        "zhilian": "预备党员",
    },
    "群众": {
        "boss": "",
        "liepin": "群众",
        "51job": "群众",
        "zhilian": "群众",
    },
    "民主党派": {
        "boss": "",
        "liepin": "民主党派",
        "51job": "民主党派",
        "zhilian": "民主党派",
    },
    "无党派人士": {
        "boss": "",
        "liepin": "无党派人士",
        "51job": "无党派人士",
        "zhilian": "无党派人士",
    },
}

POLITICAL_STATUS_REVERSE = {}
for unified_val, platform_vals in POLITICAL_STATUS_MAPPING.items():
    for pid, pval in platform_vals.items():
        if pval:
            POLITICAL_STATUS_REVERSE.setdefault(pid, {})[pval] = unified_val


# ============ 身份映射 ============
IDENTITY_MAPPING = {
    "职场人": {
        "boss": "职场人",  # 牛人身份，APP修改
        "liepin": "职场人",
        "51job": "职场人",
        "zhilian": "职场人",
    },
    "学生": {
        "boss": "学生",
        "liepin": "学生",
        "51job": "学生",
        "zhilian": "学生",
    },
}

IDENTITY_REVERSE = {}
for unified_val, platform_vals in IDENTITY_MAPPING.items():
    for pid, pval in platform_vals.items():
        if pval:
            IDENTITY_REVERSE.setdefault(pid, {})[pval] = unified_val


# ============ 日期格式转换 ============
def date_to_platform(date_str: str, platform: str) -> str:
    """统一日期 'YYYY-MM' → 各平台格式"""
    if not date_str:
        return ""
    parts = date_str.replace("年", "-").replace("月", "").split("-")
    if len(parts) < 2:
        return date_str
    year, month = parts[0], parts[1].zfill(2)

    if platform == "liepin":
        return f"{year}年{month}月"
    # BOSS, 51job, 智联 都用 YYYY-MM
    return f"{year}-{month}"


def date_to_unified(date_str: str) -> str:
    """各平台日期 → 统一格式 'YYYY-MM'"""
    if not date_str:
        return ""
    import re
    m = re.match(r"(\d{4})\D+(\d{1,2})", date_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    return date_str


# ============ 城市格式转换 ============
def city_to_platform(city: str, platform: str) -> str:
    """
    统一城市格式: '广东-广州-海珠区' (最具体)
    → 各平台格式:
      boss: 无此字段
      liepin: '广东·广州' (省·市)
      51job: '广东-广州-海珠区' (三级)
      zhilian: '广东-广州-海珠区' (三级)
    """
    if not city:
        return ""
    parts = city.replace("·", "-").split("-")

    if platform == "liepin":
        # 猎聘只要 省·市
        if len(parts) >= 2:
            return f"{parts[0]}·{parts[1]}"
        return city
    # 51job, 智联 用完整三级
    return "-".join(parts)


def city_to_unified(*city_values) -> str:
    """取最具体的城市值作为统一值"""
    best = ""
    for c in city_values:
        if c and len(c) > len(best):
            best = c
    return best


# ============ 字段元数据：哪些字段需要映射翻译 ============
MAPPED_FIELDS = {
    "jobStatus": {
        "label": "求职状态",
        "mapping": JOB_STATUS_MAPPING,
        "reverse": JOB_STATUS_REVERSE,
        "options": list(JOB_STATUS_MAPPING.keys()),
    },
    "politicalStatus": {
        "label": "政治面貌",
        "mapping": POLITICAL_STATUS_MAPPING,
        "reverse": POLITICAL_STATUS_REVERSE,
        "options": list(POLITICAL_STATUS_MAPPING.keys()),
    },
    "identity": {
        "label": "身份",
        "mapping": IDENTITY_MAPPING,
        "reverse": IDENTITY_REVERSE,
        "options": list(IDENTITY_MAPPING.keys()),
    },
}

# 需要格式转换的字段（不是选项映射，而是格式差异）
FORMAT_FIELDS = {
    "birth": {
        "label": "出生年月",
        "type": "date",
    },
    "workStartDate": {
        "label": "参加工作时间",
        "type": "date",
    },
    "city": {
        "label": "当前城市",
        "type": "city",
    },
}
