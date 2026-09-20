"""
薪资映射模块 — 将用户选择的标准薪资档位翻译为各平台的原生参数。

用户侧标准档位（下拉单选）:
  不限, 3K以下, 3-5K, 5-10K, 10-15K, 15-20K, 20-30K, 30-50K, 50K以上

各平台映射:
  Boss    → SALARY_CODES 字典的 key（直接匹配）
  猎聘    → LIEPIN_SALARY_MAP 的 key（直接匹配）
  51job   → SALARY_CODE_MAP 的 key（直接匹配）
  智联    → 页面上实际显示的薪资文本（DOM 点击匹配）
  小红书  → 不支持薪资筛选
"""

# 标准档位 → 各平台实际参数
# key = 用户选择的标准档位
# value = 传给对应平台 collector 的 salary 字符串
SALARY_MAPPING: dict[str, dict[str, str]] = {
    "不限": {
        "boss": "不限",
        "liepin": "不限",
        "51job": "不限",
        "zhilian": "不限",
        "xiaohongshu": "",  # 不支持
    },
    "3K以下": {
        "boss": "3K以下",
        "liepin": "8千以下",
        "51job": "8千以下",
        "zhilian": "4K以下",
        "xiaohongshu": "",
    },
    "3-5K": {
        "boss": "3-5K",
        "liepin": "8千以下",
        "51job": "8千以下",
        "zhilian": "4K-6K",
        "xiaohongshu": "",
    },
    "5-10K": {
        "boss": "5-10K",
        "liepin": "8-10K",
        "51job": "8-10K",
        "zhilian": "8K-10K",
        "xiaohongshu": "",
    },
    "10-15K": {
        "boss": "10-15K",
        "liepin": "10-15K",
        "51job": "10-15K",
        "zhilian": "10K-15K",
        "xiaohongshu": "",
    },
    "15-20K": {
        "boss": "15-20K",
        "liepin": "15-20K",
        "51job": "15-20K",
        "zhilian": "15K-25K",
        "xiaohongshu": "",
    },
    "20-30K": {
        "boss": "20-30K",
        "liepin": "20-30K",
        "51job": "20-30K",
        "zhilian": "25K-35K",
        "xiaohongshu": "",
    },
    "30-50K": {
        "boss": "30-50K",
        "liepin": "30-50K",
        "51job": "30-40K",
        "zhilian": "35K-50K",
        "xiaohongshu": "",
    },
    "50K以上": {
        "boss": "50K以上",
        "liepin": "50K以上",
        "51job": "40-50K",
        "zhilian": "50K以上",
        "xiaohongshu": "",
    },
}

# 标准档位列表（供前端下拉框使用）
STANDARD_SALARY_TIERS = list(SALARY_MAPPING.keys())


def map_salary(standard_tier: str, platform: str) -> str:
    """
    将标准薪资档位翻译为平台原生参数。
    如果档位不存在，回退到 "不限"。
    """
    tier_map = SALARY_MAPPING.get(standard_tier)
    if not tier_map:
        return "不限"
    return tier_map.get(platform, "不限")


def adapt_keyword(keyword: str, platform: str) -> str:
    """
    关键词适配：小红书需要加"招聘"后缀才能搜到招聘信息。
    其他平台直接透传。
    """
    if platform == "xiaohongshu":
        kw = keyword.strip()
        if not kw.endswith("招聘"):
            return f"{kw}招聘"
        return kw
    return keyword
