import os
import json
import threading
from pathlib import Path
from dotenv import load_dotenv

# 1. 暴力清除进程环境变量（最彻底的防代理方式）
for k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
    os.environ.pop(k, None)

# 2. 动态定位到上一级目录（根目录）的 .env 文件
root_dir = Path(__file__).resolve().parent.parent
env_path = root_dir / '.env'
load_dotenv(dotenv_path=env_path)

# 3. settings.json 路径（图形化配置界面写入此文件）
SETTINGS_JSON_PATH = Path(__file__).resolve().parent / "data" / "settings.json"


def _load_settings_json() -> dict:
    """从 settings.json 动态读取配置，失败时返回空字典。"""
    try:
        if SETTINGS_JSON_PATH.exists():
            with open(SETTINGS_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _cfg(*env_keys: str, json_key: str = None):
    """优先级：settings.json（页面配置） > 环境变量（.env fallback） > None。
    env_keys 按顺序逐一尝试；json_key 默认取第一个 env_key。
    """
    settings = _load_settings_json()
    jk = json_key or env_keys[0]
    val = settings.get(jk)
    if val:
        return val
    for key in env_keys:
        val = os.getenv(key)
        if val:
            return val
    return None


# 3. --- 大模型配置 ---
OPENAI_API_KEY = _cfg("OPENAI_API_KEY", "LLM_API_KEY", "api_key", json_key="OPENAI_API_KEY")
OPENAI_BASE_URL = _cfg("OPENAI_BASE_URL", "LLM_BASE_URL", "base_url", json_key="OPENAI_BASE_URL")
OPENAI_MODEL = _cfg("OPENAI_MODEL", "LLM_MODEL", json_key="OPENAI_MODEL")
VISION_MODEL = _cfg("VISION_MODEL", json_key="VISION_MODEL")

LLM_API_KEY = OPENAI_API_KEY
LLM_BASE_URL = OPENAI_BASE_URL
LLM_MODEL = OPENAI_MODEL

# 4. --- 飞书配置 ---
FEISHU_APP_ID = _cfg("FEISHU_APP_ID", "APP_ID", json_key="FEISHU_APP_ID")
FEISHU_APP_SECRET = _cfg("FEISHU_APP_SECRET", "APP_SECRET", json_key="FEISHU_APP_SECRET")
FEISHU_APP_TOKEN = _cfg("FEISHU_APP_TOKEN", "APP_TOKEN", json_key="FEISHU_APP_TOKEN")

# 数据表 ID 集合
FEISHU_TABLE_ID_JOBS = _cfg("FEISHU_TABLE_ID_JOBS", "TABLE_ID_JOBS", "TABLE_ID", json_key="FEISHU_TABLE_ID_JOBS")

# 🌟 配置中心表 ID（Prompt 策略库已退役：加载器从未命中，prompt 已固化代码内）
FEISHU_TABLE_ID_RESUMES = _cfg("FEISHU_TABLE_ID_RESUMES", json_key="FEISHU_TABLE_ID_RESUMES")

# 会话过期预警接收人 (飞书 open_id)
FEISHU_ALERT_RECEIVE_ID = _cfg("FEISHU_ALERT_RECEIVE_ID", json_key="FEISHU_ALERT_RECEIVE_ID")

# 5. --- 外部情报接口配置 ---
# Serper（Google 搜索管道）为公司情报主引擎；Tavily（LLM 检索管道）降级备用
SERPER_API_KEY = _cfg("SERPER_API_KEY", json_key="SERPER_API_KEY")
TAVILY_API_KEY = _cfg("TAVILY_API_KEY", json_key="TAVILY_API_KEY")


# ==================== 🌟 动态客户端 Getter（每次调用均重读 settings.json）====================

def get_safe_httpx_client():
    import httpx
    return httpx.Client(
        proxy=None,           # 🌟 适配新版 httpx 的单数形式
        trust_env=False,      # 🌟 告诉 httpx 不要去读系统代理环境变量
        timeout=180.0
    )

# 客户端连接复用缓存：指纹 (api_key, base_url, caller, max_retries) -> 包装后的 TrackedClient。
# 原先每次调用新建 OpenAI 客户端，每轮 LLM 调用都重付 TCP+TLS 握手（2026-09-23 慢因修复）。
_openai_client_cache: dict = {}
_openai_client_lock = threading.Lock()
_OPENAI_CLIENT_CACHE_MAX = 32


def get_openai_client(caller: str = "", max_retries: int = 3):
    """返回使用最新配置的 OpenAI 客户端（动态读取，感知 settings.json 变更）。
    自动包装 token 追踪代理，所有调用方的 LLM 消耗均会被记录。

    按 (key, url, caller, max_retries) 指纹缓存复用连接池；配置变更时指纹失配自动重建。
    caller 进指纹是为保留 TrackedClient 的按模块埋点语义（全仓约 18 个 caller 标签，
    容量 32 内 FIFO 淘汰极少触发；每个池为少量 keep-alive 空闲连接，资源开销远小于
    每次调用重付 TCP+TLS 握手）。淘汰不显式 close：避免在锁内做阻塞 I/O，旧连接由 GC 回收。
    max_retries 默认维持全局 3 次（后台批量链路的韧性不变）；交互类调用方
    （grill/排版/联动）显式传 1——SDK 仅对 408/429/5xx 重试，180s 超时 × 3 次重试
    会把单次失败放大到 12 分钟级挂死（实测排版单模块已 59s）。
    """
    from openai import OpenAI
    from app.core.llm_tracker import make_tracked_client

    key = _cfg("OPENAI_API_KEY", "LLM_API_KEY", "api_key", json_key="OPENAI_API_KEY")
    url = _cfg("OPENAI_BASE_URL", "LLM_BASE_URL", "base_url", json_key="OPENAI_BASE_URL")
    fingerprint = (key, url, caller, max_retries)
    with _openai_client_lock:
        cached = _openai_client_cache.get(fingerprint)
        if cached is None:
            raw_client = OpenAI(
                api_key=key,
                base_url=url,
                http_client=get_safe_httpx_client(),
                max_retries=max_retries
            )
            cached = make_tracked_client(raw_client, caller=caller)
            if len(_openai_client_cache) >= _OPENAI_CLIENT_CACHE_MAX:
                # FIFO 淘汰最旧指纹（dict 保序）；不显式 close——避免在锁内做阻塞 I/O，
                # 旧连接由 GC 回收
                _openai_client_cache.pop(next(iter(_openai_client_cache)))
            _openai_client_cache[fingerprint] = cached
        return cached


def get_vision_llm_client(caller: str = "vision"):
    """返回视觉（图片识别）专用 OpenAI 客户端。

    优先读 VISION_API_KEY / VISION_BASE_URL（独立视觉通道，主网关不支持
    图片输入时指向支持 VL 的供应商）；未配置时回落主通道 OPENAI_*。
    """
    from openai import OpenAI
    from app.core.llm_tracker import make_tracked_client

    key = _cfg("VISION_API_KEY", json_key="VISION_API_KEY") or _cfg("OPENAI_API_KEY", "LLM_API_KEY", "api_key", json_key="OPENAI_API_KEY")
    url = _cfg("VISION_BASE_URL", json_key="VISION_BASE_URL") or _cfg("OPENAI_BASE_URL", "LLM_BASE_URL", "base_url", json_key="OPENAI_BASE_URL")
    raw_client = OpenAI(
        api_key=key,
        base_url=url,
        http_client=get_safe_httpx_client(),
        max_retries=3
    )
    return make_tracked_client(raw_client, caller=caller)


# ==================== 最小启动字段判定（配置页必填标注 / readiness / LLM 诊断三处共享） ====================

# 最小启动必填字段（按通道分组）：缺任一项，项目都无法完整启动
MINIMAL_REQUIRED_KEYS: dict[str, list[str]] = {
    "llm": ["OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"],
    "feishu": [
        "FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN",
        "FEISHU_TABLE_ID_JOBS", "FEISHU_TABLE_ID_RESUMES",
    ],
}

# 键 → 运行时取值链（与上方模块级常量的 _cfg 参数保持同一优先级口径）
_RUNTIME_KEY_CHAINS: dict[str, tuple] = {
    "OPENAI_API_KEY": ("OPENAI_API_KEY", "LLM_API_KEY", "api_key"),
    "OPENAI_BASE_URL": ("OPENAI_BASE_URL", "LLM_BASE_URL", "base_url"),
    "OPENAI_MODEL": ("OPENAI_MODEL", "LLM_MODEL"),
    "VISION_MODEL": ("VISION_MODEL",),
    "VISION_API_KEY": ("VISION_API_KEY",),
    "FEISHU_APP_ID": ("FEISHU_APP_ID", "APP_ID"),
    "FEISHU_APP_SECRET": ("FEISHU_APP_SECRET", "APP_SECRET"),
    "FEISHU_APP_TOKEN": ("FEISHU_APP_TOKEN", "APP_TOKEN"),
    "FEISHU_TABLE_ID_JOBS": ("FEISHU_TABLE_ID_JOBS", "TABLE_ID_JOBS", "TABLE_ID"),
    "FEISHU_TABLE_ID_RESUMES": ("FEISHU_TABLE_ID_RESUMES",),
}


def get_configured_value(key: str) -> str:
    """按运行时同源优先级（settings.json > .env）读取配置值并 strip，供判定类场景使用。"""
    chain = _RUNTIME_KEY_CHAINS.get(key, (key,))
    return (_cfg(*chain, json_key=key) or "").strip()


def get_missing_llm_keys() -> list[str]:
    """主推理通道缺失字段列表（空列表 = 就绪）。"""
    return [k for k in MINIMAL_REQUIRED_KEYS["llm"] if not get_configured_value(k)]


def get_missing_feishu_min_keys() -> list[str]:
    """飞书最小字段（凭证 + 岗位总表 + 简历库）缺失列表。"""
    return [k for k in MINIMAL_REQUIRED_KEYS["feishu"] if not get_configured_value(k)]


def get_missing_vision_keys() -> list[str]:
    """视觉通道缺失字段列表。VISION_MODEL 是硬前提；通道 Key 未配置时回落主通道 Key。"""
    missing: list[str] = []
    if not get_configured_value("VISION_MODEL"):
        missing.append("VISION_MODEL")
    if not get_configured_value("VISION_API_KEY") and not get_configured_value("OPENAI_API_KEY"):
        missing.append("VISION_API_KEY")
    return missing


def missing_guide_text(missing: list[str], feature: str) -> str:
    """功能闸门的标准指引文案（后端各拦截点单点复用，防文案漂移）。"""
    return f"{feature}需要配置（缺少 {'、'.join(missing)}）——请前往 配置大盘 → 系统底层配置 填写"


def get_tavily_api_key() -> str | None:
    """动态读取最新 Tavily API Key（感知 settings.json 变更）。"""
    return _cfg("TAVILY_API_KEY", json_key="TAVILY_API_KEY")


def get_serper_api_key() -> str | None:
    """动态读取最新 Serper API Key（感知 settings.json 变更）。"""
    return _cfg("SERPER_API_KEY", json_key="SERPER_API_KEY")

# 6. --- 火山引擎 (豆包) 流式语音大模型 V3 配置 ---
VOLC_ASR_APPID = _cfg("VOLC_ASR_APPID", json_key="VOLC_ASR_APPID")
VOLC_ASR_TOKEN = _cfg("VOLC_ASR_TOKEN", json_key="VOLC_ASR_TOKEN")
# 默认使用小时版的 resource_id
VOLC_ASR_RESOURCE_ID = _cfg("VOLC_ASR_RESOURCE_ID", json_key="VOLC_ASR_RESOURCE_ID")
if not VOLC_ASR_RESOURCE_ID:
    VOLC_ASR_RESOURCE_ID = "volc.bigasr.sauc.duration"


# 7. --- 数据清洗专用大模型配置 (Cleaner LLM) ---
CLEANER_LLM_API_KEY = _cfg("CLEANER_LLM_API_KEY", json_key="CLEANER_LLM_API_KEY")
CLEANER_LLM_BASE_URL = _cfg("CLEANER_LLM_BASE_URL", json_key="CLEANER_LLM_BASE_URL")
CLEANER_LLM_MODEL = _cfg("CLEANER_LLM_MODEL", json_key="CLEANER_LLM_MODEL")
CLEANER_VISION_MODEL = _cfg("CLEANER_VISION_MODEL", json_key="CLEANER_VISION_MODEL") # 🌟 新增视觉模型

def get_cleaner_llm_client(caller: str = ""):
    """返回用于数据清洗的专用大模型客户端（动态读取），自动包装 token 追踪。"""
    from openai import OpenAI
    from app.core.llm_tracker import make_tracked_client

    key = _cfg("CLEANER_LLM_API_KEY", json_key="CLEANER_LLM_API_KEY")
    url = _cfg("CLEANER_LLM_BASE_URL", json_key="CLEANER_LLM_BASE_URL")
    
    # 防止未配置时报错
    if not key or not url:
        raise ValueError("缺少 CLEANER_LLM 的配置，请检查 .env 或 settings.json")
        
    raw_client = OpenAI(
        api_key=key, 
        base_url=url, 
        http_client=get_safe_httpx_client(),
        max_retries=3
    )
    return make_tracked_client(raw_client, caller=caller)

# --- 飞书配置新增 ---
FEISHU_TABLE_ID_INTERVIEW_REPORTS = _cfg("FEISHU_TABLE_ID_INTERVIEW_REPORTS", json_key="FEISHU_TABLE_ID_INTERVIEW_REPORTS")
FEISHU_TABLE_ID_INTERVIEW_SUMMARY = _cfg("FEISHU_TABLE_ID_INTERVIEW_SUMMARY", json_key="FEISHU_TABLE_ID_INTERVIEW_SUMMARY")
FEISHU_TABLE_ID_INTERVIEW_REAL = _cfg("FEISHU_TABLE_ID_INTERVIEW_REAL", json_key="FEISHU_TABLE_ID_INTERVIEW_REAL")

# 高德地图开放平台配置 (Web服务 API)
AMAP_API_KEY = _cfg("AMAP_API_KEY", json_key="AMAP_API_KEY")
AMAP_BASE_URL = _cfg("AMAP_BASE_URL", json_key="AMAP_BASE_URL") or "https://restapi.amap.com/v3/geocode/geo"



# ==========================================
# 🌟 settings.json → 运行时桥接（修复「页面配置后底层读不到」）
# ==========================================
def sync_settings_to_runtime(reset_keys=None) -> int:
    """把 settings.json（图形化配置页写入）注入运行时，解决三套配置源割裂问题：

    1. 逐键写入 os.environ —— pydantic BaseSettings 的环境变量优先级高于 .env，
       因此 app/core/config.py 的 settings.FEISHU_APP_ID 等约 40 处 pydantic 消费方
       （feishu_client / feishu_ws / feishu_service / strategy / jobs / map / volc…）
       立即读到页面配置；step1_rule_filter 等直接 os.getenv 的模块同样受益。
    2. 原地 setattr 更新 app.core.config.settings 单例 —— 所有
       `from app.core.config import settings` 的模块立即看到新值（不能只替换
       app.core.config.settings 属性，旧对象引用不会跟随）。
    3. reset_keys（配置页「清除」用）：这些键已从 settings.json 删除、且注入的
       环境变量已 pop 并由 load_dotenv 从 .env 重新填充——把 pydantic 单例同步
       回落到 .env 值（无则 None），实现「清除后回落 .env」语义。

    优先级保持文档语义：settings.json > .env（load_dotenv 不覆盖已存在的环境变量）。
    返回注入的配置键数量。任何进程入口（main.py / 脚本 / 测试）import common.config
    时都会在模块尾部自动执行一次。
    """
    data = _load_settings_json()
    injected = 0
    for key, value in data.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        os.environ[key] = text
        injected += 1
    try:
        from app.core.config import settings as _pyd_settings
        # 只回写 pydantic 已声明字段：BaseSettings 对未知字段 setattr 会直接 ValueError
        model_fields = getattr(type(_pyd_settings), "model_fields", {}) or {}
        for key, value in data.items():
            if key in model_fields:
                try:
                    setattr(_pyd_settings, key, value)
                except Exception:
                    pass
        for key in (reset_keys or []):
            try:
                if key in model_fields:
                    setattr(_pyd_settings, key, os.environ.get(key))
            except Exception:
                pass
    except Exception:
        pass
    return injected


# 模块导入即同步：保证任何入口启动时 os.environ 与 pydantic settings 都已带上
# settings.json 的值（feishu_ws 等模块在 import 阶段就会读取飞书凭证）
sync_settings_to_runtime()