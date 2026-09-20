import logging
import os
import threading
import time
from typing import Any

import requests
from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

# 🌟 保持缓存的全局变量 (在模块级别)；token 与签发凭证绑定，配置页热换凭证后立即失效重取
_MAIN_TOKEN_CACHE = {"token": None, "expires_at": 0, "app_id": None}
_TOKEN_LOCK = threading.Lock()

def safe_feishu_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    json: Any | None = None,
    data: Any | None = None,
    params: dict[str, Any] | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    proxies: dict[str, Any] | None = None,
    **kwargs
) -> requests.Response:
    """
    针对飞书 API 的强健网络请求封装：
    1. 默认禁用系统/环境变量代理干扰（proxies={"http": None, "https": None}）
    2. 针对 SSL: UNEXPECTED_EOF_WHILE_READING、ConnectionReset、Read timed out 等网络层异常实现指数退避自愈重试
    3. 支持状态码 502/503/504 自动重试
    """
    if proxies is None:
        proxies = {"http": None, "https": None}

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        cur_timeout = timeout + (attempt - 1) * 10
        try:
            resp = requests.request(
                method=method.upper(),
                url=url,
                headers=headers,
                json=json,
                data=data,
                params=params,
                timeout=cur_timeout,
                proxies=proxies,
                **kwargs
            )
            # 若飞书服务端返回 502/503/504 网关抖动，进行退避重试
            if resp.status_code in (502, 503, 504) and attempt < max_retries:
                logger.warning(f"⚠️ 飞书服务端响应 HTTP {resp.status_code}，将在 {backoff_factor * attempt:.1f}s 后触发第 {attempt}/{max_retries} 次自愈重试... URL: {url}")
                time.sleep(backoff_factor * attempt)
                continue
            return resp
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError) as net_err:
            last_err = net_err
            if attempt < max_retries:
                wait_s = backoff_factor * (2 ** (attempt - 1))
                logger.warning(f"⚠️ 飞书 API 瞬时网络抖动/响应较慢 ({net_err})，自愈机制将在 {wait_s:.1f}s 后自动发起第 {attempt}/{max_retries} 次重试...")
                time.sleep(wait_s)
            else:
                logger.error(f"❌ 飞书 API 重试 {max_retries} 次后仍然失败: {net_err}, URL: {url}")
                raise last_err
        except Exception as e:
            logger.error(f"❌ 飞书 API 发生未知请求异常: {e}, URL: {url}")
            raise e

    if last_err:
        raise last_err
    raise RuntimeError(f"飞书请求未能完成: {url}")

def _token_fresh() -> bool:
    return bool(_MAIN_TOKEN_CACHE["token"]
                and _MAIN_TOKEN_CACHE["app_id"] == settings.FEISHU_APP_ID
                and time.time() < _MAIN_TOKEN_CACHE["expires_at"] - 300)


def get_tenant_access_token() -> str:

    # 🌟 命中缓存，直接秒回 (提前300秒刷新，防止过期)
    if _token_fresh():
        return _MAIN_TOKEN_CACHE["token"]

    # 到期/换凭证瞬间并发线程会同时 POST 刷新，锁内二次检查收敛为一次
    with _TOKEN_LOCK:
        if _token_fresh():
            return _MAIN_TOKEN_CACHE["token"]

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        try:
            # 使用安全请求封装 + 配置项中的 ID 和 Secret
            resp = safe_feishu_request(
                "POST",
                url,
                json={"app_id": settings.FEISHU_APP_ID, "app_secret": settings.FEISHU_APP_SECRET},
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"飞书鉴权通信失败: {str(e)}")

        if data.get("code") != 0:
            raise HTTPException(status_code=502, detail=f"飞书鉴权失败: {data.get('msg', 'unknown')}")

        # 更新缓存
        _MAIN_TOKEN_CACHE["token"] = data["tenant_access_token"]
        _MAIN_TOKEN_CACHE["expires_at"] = time.time() + data.get("expire", 7200)
        _MAIN_TOKEN_CACHE["app_id"] = settings.FEISHU_APP_ID
        return _MAIN_TOKEN_CACHE["token"]

def feishu_field_to_plain_str(val: Any, default: str = "") -> str:
    """完美移植旧版逻辑，确保数据格式解析完全兼容"""
    if val is None:
        return default
    if isinstance(val, str):
        return val or default
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        chunks = []
        for item in val:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                text = item.get("link") if (item.get("link") and str(item.get("link")).startswith("http")) else (item.get("text") or item.get("name") or item.get("value"))
                if text is not None:
                    chunks.append(str(text))
            elif item is not None:
                chunks.append(str(item))
        return "".join([c for c in chunks if c]) or default
    if isinstance(val, dict):
        text = val.get("link") if (val.get("link") and str(val.get("link")).startswith("http")) else (val.get("text") or val.get("name") or val.get("value"))
        return str(text) if text is not None else str(val)
    return str(val) or default

def extract_feishu_text(value):
    if not value:
        return ""
    if isinstance(value, str):
        return value.strip()

    text_parts = []
    def _dfs(obj):
        if isinstance(obj, dict):
            # 若包含有效 http 链接，优先提取链接
            link_val = obj.get("link")
            if link_val and isinstance(link_val, str) and link_val.startswith("http"):
                text_parts.append(link_val)
                return
            if 'text' in obj and isinstance(obj['text'], str):
                text_parts.append(obj['text'])
            elif 'value' in obj and isinstance(obj['value'], str):
                text_parts.append(obj['value'])
            for k, v in obj.items():
                if k not in ('text', 'value', 'link'):
                    _dfs(v)
        elif isinstance(obj, list):
            for item in obj:
                _dfs(item)

    _dfs(value)
    if text_parts:
        return "".join(text_parts).strip()
    return str(value).strip()

# 岗位评级字段候选名（按优先级）：评估器写入的是「综合评级 (A-F)」，
# 「综合等级」「评级」为历史字段名，仅老记录可能有值
_GRADE_FIELD_CANDIDATES = ("综合等级", "评级", "综合评级 (A-F)")
_GRADE_THRESHOLDS = {
    "A": {"A"},
    "B": {"A", "B"},
    "C": {"A", "B", "C"},
}


def extract_job_grade(fields: dict[str, Any]) -> str:
    """从飞书岗位记录字段里提取综合评级（A/B/C/D/F，统一大写）。

    按候选字段名依次取第一个非空值；全部缺失时返回空字符串，
    绝不兜底伪造等级（此前兜底 "B" 曾让看板把 C/D 级岗位显示成 B）。
    """
    for name in _GRADE_FIELD_CANDIDATES:
        text = extract_feishu_text(fields.get(name, "")).strip().upper()
        if text:
            return text
    return ""


def grade_meets_threshold(grade: Any, threshold: str) -> bool:
    """判断评级是否达到自动化阈值；分数不参与门禁。"""
    normalized_grade = extract_feishu_text(grade).strip().upper()
    normalized_threshold = extract_feishu_text(threshold).strip().upper()
    allowed_grades = _GRADE_THRESHOLDS.get(normalized_threshold)
    if allowed_grades is None:
        allowed_grades = _GRADE_THRESHOLDS["A"]
    return normalized_grade in allowed_grades


def is_custom_record(fields: dict[str, Any]) -> bool:
    """精投/海投统一判定口径（纯字段版，供批量编排预扫描 / delivery_node / CLI 取数共用）。

    判定依据（满足其一即精投）：
    1. 「AI改写JSON」非空（结构化定制改写产物）；
    2. 综合评级为 A/B。
    三处消费方必须共用本函数，此前各写一套判定曾导致岗位进海投队列却被按精投投递的口径漂移。
    """
    if extract_feishu_text(fields.get("AI改写JSON", "")).strip():
        return True
    return (extract_job_grade(fields) or "").upper() in ("A", "B")


TERMINAL_FOLLOW_STATUSES = {
    "已投递", "已放弃投递", "清洗淘汰", "已拒绝", "已下架",
    "一面", "二面", "三面", "HR面", "面试", "Offer", "录用"
}


def is_terminal_or_post_delivery_status(status: str | None) -> bool:
    """判断岗位跟进状态是否属于已投递或终态/面试态（严禁倒流回简历人工复核）。"""
    if not status:
        return False
    s = str(status).strip()
    if s in TERMINAL_FOLLOW_STATUSES:
        return True
    s_lower = s.lower()
    return any(t in s_lower for t in ("已投递", "已放弃", "清洗淘汰", "已拒绝", "已下架", "面", "offer", "录用"))

def download_feishu_file(file_token: str, save_path: str) -> bool:
    """下载飞书附件到本地路径。

    Args:
        file_token: 飞书文件 token（来自附件字段的 file_token）。
        save_path:  本地保存路径（含文件名）。

    Returns:
        True 表示下载并写入成功，False 表示失败。
    """
    token = get_tenant_access_token()
    if not token:
        print("❌ download_feishu_file：无法获取 Token")
        return False

    url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = safe_feishu_request("GET", url, headers=headers, timeout=60, stream=True)
        if response.status_code != 200:
            print(f"❌ download_feishu_file：HTTP {response.status_code}，file_token={file_token}")
            return False

        dir_name = os.path.dirname(os.path.abspath(save_path))
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        print(f"✅ 文件下载成功：{save_path}")
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ download_feishu_file 网络请求异常：{e}")
        return False
    except OSError as e:
        print(f"❌ download_feishu_file 文件写入异常：{e}")
        return False
