from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class SessionState(str, Enum):
    HEALTHY = "healthy"       # 登录有效，可正常使用
    EXPIRED = "expired"       # 登录态丢失，需重新认证
    UNKNOWN = "unknown"       # 浏览器未运行，无法验证
    DEGRADED = "degraded"     # 浏览器在运行但会话存疑


class PlatformConfig(BaseModel):
    name: str
    display_name: str
    browser_type: str = "drissionpage"  # "drissionpage" | "playwright_cdp"
    profile_dir: str = ""               # 相对于 backend/data/profiles/
    port: int = 0
    login_check_url: str = ""
    auth_url: str = ""                      # 授权拉起浏览器时自动打开的登录/首页地址
    login_url: str = ""                     # 「去登录」专用的登录页地址；空则回退 auth_url
                                            # （51job 的 auth_url 是 we.51job.com 首页而非登录页，需单独指定）
    login_indicators: list[str] = []        # CSS 选择器或 text: 前缀
    login_page_indicators: list[str] = []   # URL 中包含这些字符串说明在登录页
    requires_real_edge: bool = False
    legacy_cookie_file: str = ""
    requires_login: bool = True             # False=抓取不强制登录，预检豁免 DOM 登录校验


class SessionStatus(BaseModel):
    platform: str
    state: SessionState
    last_checked: datetime | None = None
    last_healthy: datetime | None = None
    message: str = ""
    profile_path: str = ""
    port: int | None = None
    browser_type: str = "drissionpage"
