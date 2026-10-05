"""51job patchright 引擎启动器（唯一实现）— collector 与 delivery 共用。

职责（docs/plans/51job-antibot-patchright-plan.md §3.2，plan-review R2 PASS）：
1. 引擎互斥：抢 .engine_lock（单一持有者模型，Chromium Profile 进程独占）；
2. patchright 直启真实 Edge 持久化上下文（无 CDP 端口，免 Runtime.enable 泄漏）；
3. 登录态双确认：.login_state.json 快速判断 + 页面 DOM 探测（标记可能过期）；
4. 登录态迁移：legacy cookie JSON 一次性灌入新 Profile（首次部署用，幂等）。

启动参数白名单逐条依据见 app/session/browser.py _PATCHRIGHT_LAUNCH_ARGS 注释；
刻意不加 --remote-debugging-port / --no-sandbox / UA 伪造 / 代理。
"""
import os
import sys
import time

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.dirname(_SCRIPT_DIR)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from engine_lock import (  # noqa: E402
    acquire_lock, release_lock, heartbeat, read_login_state, write_login_state, invalidate_login_state,
)

# registry 优先，独立脚本环境 fallback（与 collector :24-30 既有先例同源）
try:
    from app.session.registry import get_profile_path
    PROFILE_DIR = get_profile_path("51job")
except Exception:
    PROFILE_DIR = os.path.join(_BACKEND_ROOT, 'data', 'profiles', '51job')

# 启动参数白名单（唯一定义处；browser.py 延迟导入本常量，无副本）
PATCHRIGHT_LAUNCH_ARGS = [
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-session-crashed-bubble",
    "--hide-crash-restore-bubble",
    "--test-type",
    # 2026-09-25 窗口合成故障免疫：当日下午 15:06~15:52 GPU 合成路径新建窗口仅被
    # 窗口服务器登记、从未上屏（optionOnScreenOnly=false），用户端表现为「唤起后
    # 无窗口」；同期 boss 启动路径带 --disable-gpu（软件渲染）全程免疫。经 WAF
    # 实测（we.51job.com DOM 登录态全命中、无风控挑战）后加入；若后续出现
    # 滑块/验证码概率上升需回退本参数并另行排查。
    "--disable-gpu",
]


def find_edge_path() -> str | None:
    """Edge 可执行文件（Windows + macOS 候选）；找不到返回 None 让 patchright 走 channel 回退。"""
    for path in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ):
        if os.path.exists(path):
            return path
    return None


def _login_dom_confirmed(context) -> bool:
    """DOM 级登录确认（registry 校准过的 indicators；we.51job.com 登录态首页）。

    只检查已打开的 51job 页面（collector/delivery 主流程会自行开页）；若上下文
    还没有任何平台页面，返回 False，由 _verify_login_via_page 主动开页判定。
    """
    indicators_css = [".user-info", ".avatar"]
    indicators_text = ["退出登录"]
    try:
        for page in context.pages:
            host = ""
            try:
                from urllib.parse import urlparse
                host = (urlparse(page.url).hostname or "")
            except Exception:
                host = ""
            if "51job.com" not in host:
                continue
            for sel in indicators_css:
                try:
                    if page.locator(sel).count() > 0:
                        return True
                except Exception:
                    continue
            for text in indicators_text:
                try:
                    if page.get_by_text(text, exact=False).count() > 0:
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def _verify_login_via_page(context) -> bool:
    """主动开 we.51job.com 判定登录态（判定后即关页，不留给调用方多余标签）。

    返回是否 DOM 确认登录；确认时顺带刷新快速标记。
    """
    confirmed = False
    page = None
    try:
        page = context.new_page()
        page.goto("https://we.51job.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2.5)  # SPA 渲染窗口：登录指示器异步出现
        for sel in (".user-info", ".avatar"):
            if page.locator(sel).count() > 0:
                confirmed = True
                break
        if not confirmed and page.get_by_text("退出登录", exact=False).count() > 0:
            confirmed = True
        if confirmed:
            write_login_state(PROFILE_DIR)  # DOM 确认即刷新标记，后续启动走快路径
    except Exception as e:
        print(f"⚠️ 登录态 DOM 校验页打开失败（按未确认处理）: {str(e)[:100]}")
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass  # 页面已随浏览器崩溃失效时 close 会抛，不得逃逸掩盖判定结果
    return confirmed


# 会话 cookie 本地改写的持久时长（服务端仍可能先行失效，deliver 强制实测门兜底）
DEFAULT_SESSION_COOKIE_TTL = 30 * 86400


def persist_session_cookies(context) -> int:
    """把上下文中的会话级 cookie（无过期时间，关窗即死）改写为持久后回注。

    2026-09-25 真机破案：login.51job.com 下发的登录会话 cookie 是 session-scoped，
    登录成功自动关窗时随浏览器内存销毁、从未写进 Profile 磁盘——登录标记写着成功、
    下一次引擎启动却全域裸奔（附件区 Vue 不挂载/简历中心被踢）。Chrome 只把带
    过期时间的 cookie 落盘，故统一改写为 DEFAULT_SESSION_COOKIE_TTL 后回注。
    仅处理 51job 域；批量回注被单个脏 cookie 拖垮时逐条降级。返回改写条数。
    """
    try:
        all_cookies = context.cookies() or []
    except Exception as e:
        print(f"⚠️ [cookie持久化] 读取上下文 cookie 失败（跳过）: {str(e)[:100]}")
        return 0
    persisted_cookies = []
    for cookie in all_cookies:
        try:
            if "51job" in (cookie.get("domain") or "") and cookie.get("expires", -1) in (-1, None):
                persisted_cookies.append({**cookie, "expires": time.time() + DEFAULT_SESSION_COOKIE_TTL})
        except Exception:
            continue
    if not persisted_cookies:
        return 0
    try:
        context.add_cookies(persisted_cookies)
        print(f"🍪 [cookie持久化] 已将会话级 cookie 改写为 30 天持久: "
              f"{[c['name'] for c in persisted_cookies]}")
        return len(persisted_cookies)
    except Exception as e:
        print(f"⚠️ [cookie持久化] 批量回注失败（{str(e)[:80]}），降级逐条回注…")
        ok_names = []
        for cookie in persisted_cookies:
            try:
                context.add_cookies([cookie])
                ok_names.append(cookie.get("name"))
            except Exception as e:
                print(f"⚠️ [cookie持久化] 丢弃单个非法 cookie {cookie.get('name')}: {str(e)[:80]}")
                continue
        print(f"🍪 [cookie持久化] 逐条回注完成: {ok_names}")
        return len(ok_names)


def launch_or_fail(purpose: str = "collect"):
    """统一启动入口：抢锁 → patchright 直启 → 登录态校验。

    返回上下文管理器：`with launch_or_fail(purpose) as ctx` 中 ctx 即
    patchright BrowserContext；退出时自动 context.close()（cookie 落盘）
    + driver 停止 + 引擎锁释放。
    登录失效/被锁拒绝时抛 RuntimeError（调用方打印后退出，绝不硬刚）。
    """
    # 延迟 import：patchright driver 初始化较重，拒绝路径（锁被占）不付出该成本
    from patchright.sync_api import sync_playwright

    ok, reason = acquire_lock(PROFILE_DIR, purpose=purpose)
    if not ok:
        raise RuntimeError(f"51job Profile 被占用，拒绝启动：{reason}")

    manager = sync_playwright().start()
    context = None
    try:
        edge_path = find_edge_path()
        context = manager.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            executable_path=edge_path,
            channel="msedge",
            headless=False,          # 无头必被检测（get_jobs 实战结论）
            no_viewport=True,        # 不锁视口，用窗口实际大小
            args=PATCHRIGHT_LAUNCH_ARGS,
        )
        # legacy cookie 一次性迁移（幂等）：Profile 无 51job cookie 时灌入。
        # 必须在登录态判定之前——新 Profile / 快照回滚后就是靠这一步恢复登录态。
        migrate_legacy_cookies_if_needed(context)

        # 登录态双确认：标记（7 天内）快速判断 → DOM 探测（标记可能过期）。
        # DOM 探测需要真实打开平台页：上下文刚启动时零页面，直接测必然假阴性。
        # 2026-09-25 真机教训：服务端会话可先于客户端 cookie 过期（搜索页匿名可用
        # 会掩盖登录态已死），投递 purpose 强依赖登录（简历中心/附件上传），
        # 7 天快速标记不可作为凭证——deliver 必须跳过标记直接 DOM 实测。
        mark_was_set = read_login_state(PROFILE_DIR)
        # 需要强制登录实测的场景（resume_editor 同样强依赖登录，待真机复现后收编进此集合）
        LOGIN_REQUIRED_PURPOSES = {"deliver"}
        needs_login = purpose in LOGIN_REQUIRED_PURPOSES
        mark_ok = mark_was_set and not needs_login
        dom_confirmed = _login_dom_confirmed(context) if not mark_ok else False
        if not mark_ok and not dom_confirmed:
            dom_confirmed = _verify_login_via_page(context)
        if not (mark_ok or dom_confirmed):
            if needs_login and mark_was_set:
                # 服务端会话实测已死：清掉过期标记，防止后续投递误信快速通道。
                # （collect 快速通道不探测故不会走到这里；本分支当前仅 deliver 可达。）
                invalidate_login_state(PROFILE_DIR)
            if needs_login:
                # 清理统一交给外层 except 兜底（R1 P1 修复：二次 stop/close 会掩盖原始异常）
                raise RuntimeError(
                    "51job 登录态失效（DOM 实测未确认登录）。请在前端点「去登录」重新扫码；"
                    "登录态现由持久化 Profile 承载，成功后无需再注入 cookie。"
                )
            # 2026-09-25 用户裁决：采集匿名也能抓（实测 L0 零滑块、20 卡片字段齐全），
            # 登录死了不再卡采集——警告放行匿名抓，抓取流量不再绑定账号。
            print(
                "⚠️ [51job] 未检测到有效登录态（未登录或会话已失效），本次采集以匿名模式进行"
                "（搜索页无需登录；投递/简历编辑前请在前端「去登录」重新扫码）。"
            )
    except Exception:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        manager.stop()
        release_lock(PROFILE_DIR)
        raise

    class _CtxManager:
        """把 (context, 清理函数) 包装成 with 上下文，调用方 `with launch_or_fail() as ctx`。"""
        def __enter__(self):
            return context

        def __exit__(self, exc_type, exc, tb):
            try:
                # 会话级 cookie 改写持久后再落盘：任务期间服务端轮换的 session cookie
                # 若不处理，关窗即死（与登录 cookie 同一个坑）
                persist_session_cookies(context)
            except Exception as e:
                print(f"⚠️ [cookie持久化] 引擎关闭前持久化失败: {str(e)[:100]}")
            try:
                context.close()   # 优雅关闭：cookie 落盘
            except Exception:
                pass
            manager.stop()
            release_lock(PROFILE_DIR)
            return False

    return _CtxManager()


def touch_heartbeat():
    """长任务循环中周期刷新引擎锁心跳（collector 每页/delivery 每岗位调用）。"""
    heartbeat(PROFILE_DIR)


def migrate_legacy_cookies_if_needed(context) -> bool:
    """登录态迁移（一次性，幂等）：legacy cookie JSON 灌入新 Profile。

    判定"需要"的依据：Profile 内无任何 51job 域 cookie。成功后由浏览器自然落盘，
    之后 Profile 自持登录态，本函数永远短路。返回是否执行了迁移。
    """
    cookies = context.cookies(["https://we.51job.com", "https://www.51job.com", "https://jobs.51job.com"])
    if cookies:
        return False
    legacy = os.path.join(_SCRIPT_DIR, "51job_cookies.json")
    if not os.path.exists(legacy):
        return False
    import json
    try:
        with open(legacy, "r", encoding="utf-8") as f:
            legacy_cookies = json.load(f)
        if not legacy_cookies:
            return False
        context.add_cookies(legacy_cookies)
        print(f"🍪 [迁移] 已将 legacy 51job_cookies.json 的 {len(legacy_cookies)} 个 cookie 灌入新 Profile（一次性）。")
        return True
    except Exception as e:
        print(f"⚠️ [迁移] legacy cookie 迁移失败（不阻断，可手动扫码重登）: {e}")
        return False
