from datetime import datetime
from enum import Enum
from typing import Literal

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
    # 登录凭证 cookie 键集合（CDP 内存实证用，2026-11-03 冷启动误判根治）：
    # 空 = 未摸底，回退 DOM 判定；非空 = 预检可零导航实证登录态。
    # 键集合来源（逐平台实测摸底，2026-11-03 CDP Storage.getCookies 全量比对）：
    #   boss    = wt2+zp_at（renewal.py 核心登录双键；boss_cli REQUIRED_COOKIES 另含
    #             __zp_stoken__/wbg，前者 2~3 天即轮换不强制，强制会把正常轮换误判成掉登录）
    #   liepin  = lt_auth+liepin_login_valid（与 health_checker.LIEPIN_LOGIN_COOKIE_KEYS 同源）
    #   zhilian = at（renewal.py 核心）
    #   51job   = "51job"（51job_cookie_harvester.py 关键认证 cookie，session 键落账即有效）
    auth_cookie_keys: tuple[str, ...] = ()
    # 续抓语义：rescan_last=从最后触碰页重扫（该页可能只扫了一部分）；
    # next_page=从最后触碰页 +1 开始（0.4.1 的非 51job 语义）。
    resume_mode: Literal["rescan_last", "next_page"] = "rescan_last"


class SessionStatus(BaseModel):
    platform: str
    state: SessionState
    last_checked: datetime | None = None
    last_healthy: datetime | None = None
    message: str = ""
    profile_path: str = ""
    port: int | None = None
    browser_type: str = "drissionpage"
