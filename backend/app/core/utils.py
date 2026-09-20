
import re

from fastapi import HTTPException


def _require_env(name: str, value: str | None) -> str:
    """确保必需的环境变量已配置"""
    if not value:
        raise HTTPException(status_code=500, detail=f"缺少环境变量: {name}")
    return value


_FILENAME_FORBIDDEN_RE = re.compile(r'[\/\\:\*\?"<>\|\s]+')


def sanitize_filename(raw: str, fallback: str = "未命名") -> str:
    """清洗文件系统非法字符（/ \\ : * ? " < > | 及空白），动态简历与物料命名共用，避免落盘失败。"""
    cleaned = _FILENAME_FORBIDDEN_RE.sub("_", (raw or "").strip()).strip("_")
    return cleaned or fallback


def is_valid_greeting(greeting: str | None) -> bool:
    """打招呼语合法性校验：空值或疑似生成失败的错误文本均视为非法。

    杜绝把「❌ AI 服务未配置 (api_key)」「找不到打招呼语重构策略文件」这类系统报错
    当欢迎语写进飞书并经微聊发给 HR。判定规则：❌ 开头即非法；正文含
    生成失败 / 服务未配置 / 策略文件 等报错特征词亦非法。
    """
    g = str(greeting or "").strip()
    if not g or g.startswith("❌"):
        return False
    return not any(marker in g for marker in ("生成失败", "服务未配置", "策略文件"))


GREETING_SUPPORTED_PLATFORMS = {"boss", "zhilian", "liepin"}


def normalize_platform_code(plat: str | None) -> str:
    """将中文、中英混合或大小写各异的平台名归一化为标准小写编码：boss / zhilian / liepin / 51job"""
    if not plat or not isinstance(plat, str):
        return ""
    p = plat.strip().lower()
    if "51" in p or "前程" in p:
        return "51job"
    if "智联" in p or "zhilian" in p:
        return "zhilian"
    if "猎聘" in p or "liepin" in p:
        return "liepin"
    if "boss" in p:
        return "boss"
    return p


def is_greeting_supported_platform(plat: str | None) -> bool:
    """判定平台是否具备微聊/IM打招呼外发能力（白名单机制，排除 51job 等纯附件平台）"""
    return normalize_platform_code(plat) in GREETING_SUPPORTED_PLATFORMS
