"""
简历解析置信度打分（纯函数）。

AI 结构化结果各模块按保守启发式打 high/medium/low 三档，供前端「待确认」角标：
- 规则宁可少标（false negative 好过满屏狼来了）：只有缺失或内容过短才判 low；
- 用户手动确认/编辑过的模块由前端覆写为 "confirmed"，本函数不感知该状态。
"""

from typing import Any

# 内容少于此字符数视为「过短待确认」
_MIN_CONTENT_CHARS = 20

# 业务模块键（_meta/personalInfo 等非业务键不参与打分）
_MODULE_KEYS = ("summary", "workExperience", "personalProjects", "education", "additional")


def _is_thin(value: Any) -> bool:
    """模块内容是否单薄到需要人工确认（缺失/空/总字符过短）。"""
    if value is None:
        return True
    if isinstance(value, str):
        return len(value.strip()) < _MIN_CONTENT_CHARS
    if isinstance(value, list):
        if not value:
            return True
        # 有条目但全部没有任何实质内容（各字段拼接后仍过短）也视为单薄
        total = 0
        for item in value:
            if isinstance(item, dict):
                total += sum(len(str(v)) for v in item.values() if v)
            else:
                total += len(str(item))
        return total < _MIN_CONTENT_CHARS
    if isinstance(value, dict):
        if not value:
            return True
        total = sum(len(str(v)) for v in value.values() if v)
        return total < _MIN_CONTENT_CHARS
    return False


def score_resume_confidence(structured: dict) -> dict[str, str]:
    """对结构化简历逐模块打置信度，返回 {moduleKey: high|medium|low}。

    保守策略：只有明确的缺失/单薄判 low，其余一律 high（medium 暂无可靠信号源，预留）。
    """
    if not isinstance(structured, dict):
        return {}

    result: dict[str, str] = {}
    for key in _MODULE_KEYS:
        result[key] = "low" if _is_thin(structured.get(key)) else "high"

    # 自定义模块：前端规范为 Record<moduleKey, ExperienceV2[]>，每个自定义模块一个置信度键
    custom = structured.get("customModules")
    if isinstance(custom, dict):
        for key, items in custom.items():
            result[key] = "low" if _is_thin(items) else "high"

    return result
