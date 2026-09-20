"""
平台注册表 — 全项目唯一的平台浏览器配置区（端口 / profile / 登录判定规则 / 授权 URL）。

所有消费方（auth 路由、会话检测、简历回写子系统、简历回写脚本、前端端口展示）
一律从这里读取，禁止在其他地方硬编码端口或另建配置副本。

所有 Profile 统一存放在 backend/data/profiles/{platform}/ 下。
"""
import os

from .models import PlatformConfig

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PROFILES_ROOT = os.path.join(_BACKEND_ROOT, "data", "profiles")


def get_profile_path(platform: str) -> str:
    return os.path.join(_PROFILES_ROOT, platform)


PLATFORM_CONFIGS: dict[str, PlatformConfig] = {
    "boss": PlatformConfig(
        name="boss",
        display_name="BOSS直聘",
        browser_type="drissionpage",
        profile_dir=get_profile_path("boss"),
        port=19222,
        login_check_url="https://www.zhipin.com/",
        auth_url="https://www.zhipin.com/web/user/?ka=header-login",
        login_indicators=["css:.user-nav", "text:退出登录"],
        login_page_indicators=["passport.zhipin.com"],
    ),
    "xiaohongshu": PlatformConfig(
        name="xiaohongshu",
        display_name="小红书",
        browser_type="drissionpage",
        profile_dir=get_profile_path("xiaohongshu"),
        port=9224,
        login_check_url="https://www.xiaohongshu.com/",
        auth_url="https://www.xiaohongshu.com/",
        login_indicators=["css:.user-avatar", "css:.side-bar-user"],
        login_page_indicators=["login", "passport"],
    ),
    "liepin": PlatformConfig(
        name="liepin",
        display_name="猎聘",
        browser_type="drissionpage",
        profile_dir=get_profile_path("liepin"),
        port=9226,
        login_check_url="https://c.liepin.com/",
        auth_url="https://www.liepin.com/login?backUrl=https%3A%2F%2Fc.liepin.com%2F",
        login_indicators=["css:.header-user", "css:.user-name", "text:退出", "css:.ant-dropdown-trigger"],
        login_page_indicators=["/login", "loginBackUrl", "passport"],
        requires_login=False,
        legacy_cookie_file=os.path.join(_BACKEND_ROOT, "liepin_scraper", "liepin_cookies.json"),
    ),
    "zhilian": PlatformConfig(
        name="zhilian",
        display_name="智联招聘",
        browser_type="drissionpage",
        profile_dir=get_profile_path("zhilian"),
        port=9250,
        login_check_url="https://www.zhaopin.com/",
        auth_url="https://passport.zhaopin.com/",
        # 以下 indicators 为 2026-08-10 附加 9250 实测命中（scripts/calibrate_boss_zhilian_login_dom.py）：
        #   .c-login__top__name 为头部用户名（如「张三」）；.c-login__top__img 为头像；
        #   「退出」入口仅登录态渲染（在头部 hover 下拉内）。旧值 .user-nav / .header-user-info
        #   在智联首页不存在（猜测值），不得回流。
        login_indicators=["css:.c-login__top__name", "css:.c-login__top__img", "text:退出"],
        login_page_indicators=["passport.zhaopin.com"],
    ),
    "51job": PlatformConfig(
        name="51job",
        display_name="前程无忧",
        browser_type="playwright_cdp",
        profile_dir=get_profile_path("51job"),
        port=9227,
        # 登录态体现在 we.51job.com（www.51job.com 首页无登录元素）。
        # 以下 indicators 为 2026-08 附加 9227 实测命中（scripts/calibrate_51job_login_dom.py）：
        #   .user-info 文本为用户名；.avatar 为头像；「退出登录」入口仅在登录态渲染
        login_check_url="https://we.51job.com/",
        auth_url="https://we.51job.com/",
        # 「去登录」专用：we.51job.com 是登录态首页而非登录页，跳转需用登录域
        # （login.51job.com 已由 login_page_indicators 实测校准）
        login_url="https://login.51job.com/",
        login_indicators=["css:.user-info", "css:.avatar", "text:退出登录"],
        login_page_indicators=["login.51job.com", "passport.51job.com"],
        requires_real_edge=True,
        legacy_cookie_file=os.path.join(_BACKEND_ROOT, "51job_scraper", "51job_cookies.json"),
    ),
}

# 历史路由/前端使用的短名 → 注册表规范名
PLATFORM_ALIASES: dict[str, str] = {
    "xhs": "xiaohongshu",
}


def resolve_platform(name: str):
    """按规范名或别名取平台配置；不存在返回 None。"""
    return PLATFORM_CONFIGS.get(PLATFORM_ALIASES.get(name, name))


def get_platform_port(name: str) -> int:
    """取平台浏览器调试端口（全项目唯一取数口径）。"""
    config = resolve_platform(name)
    if not config:
        raise KeyError(f"未知平台: {name}")
    return config.port


# ==========================================
# 招聘平台识别（极速录入/采集共用的单一事实源）
# ==========================================
# 岗位链接域名 → 平台规范键；顺序即匹配优先级。
PLATFORM_URL_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("boss", ("zhipin.com",)),
    ("xiaohongshu", ("xiaohongshu.com", "xhslink.com")),
    ("liepin", ("liepin.com",)),
    ("zhilian", ("zhaopin.com",)),
    ("51job", ("51job.com",)),
]


def detect_platform_by_url(url: str) -> str:
    """从岗位链接识别招聘平台，返回注册表规范显示名；无法识别返回 "未知"。"""
    u = (url or "").lower()
    for key, domains in PLATFORM_URL_RULES:
        if any(domain in u for domain in domains):
            return PLATFORM_CONFIGS[key].display_name
    return "未知"


# 录入侧历史脏值/LLM 视觉解析输出写法 → 注册表规范显示名。
# 认不出的值（如"微信朋友圈"）原样保留：真实来源信息，投递白名单自然不匹配。
_PLATFORM_DISPLAY_ALIASES: dict[str, str] = {
    "boss直聘": "BOSS直聘",
    "boss": "BOSS直聘",
    "boos直聘": "BOSS直聘",
    "智联": "智联招聘",
    "智联招聘": "智联招聘",
    "zhilian": "智联招聘",
    "zhaopin": "智联招聘",
    "前程无忧": "前程无忧",
    "51job": "前程无忧",
    "前程无忧51job": "前程无忧",
    "猎聘": "猎聘",
    "liepin": "猎聘",
    "小红书": "小红书",
    "xhs": "小红书",
    "xiaohongshu": "小红书",
    "截图解析": "未知",
    "未知": "未知",
    "-": "未知",
}


def canonicalize_platform_name(name: str) -> str:
    """把录入侧各种平台写法归一到注册表规范显示名；空值归一为 "未知"。"""
    raw = (name or "").strip()
    return _PLATFORM_DISPLAY_ALIASES.get(raw.lower(), raw or "未知")
