"""一次性校准脚本：附加 BOSS(19222) / 智联(9250) 浏览器，实测登录态 DOM 选择器。

仅做导航与元素查询，不做任何点击/登录/提交动作。
用途：为 registry 的 boss / zhilian login_check_url / login_indicators 提供实测依据，
排查任务 #12「已登录却被预检判未登录」的根因（indicators 错 vs profile/实例不一致）。

用法：
    cd backend && uv run python scripts/calibrate_boss_zhilian_login_dom.py [boss|zhilian|all]
"""
import sys
import time

from DrissionPage import ChromiumPage, ChromiumOptions

PLATFORMS = {
    "boss": {
        "port": 19222,
        "login_check_url": "https://www.zhipin.com/",
        "registry_indicators": ["css:.user-nav", "text:退出登录"],
    },
    "zhilian": {
        "port": 9250,
        "login_check_url": "https://www.zhaopin.com/",
        "registry_indicators": ["css:.user-nav", "css:.header-user-info", "text:退出"],
    },
}

CANDIDATES = [
    # registry 现有 indicators
    "css:.user-nav", "css:.header-user-info", "text:退出登录", "text:退出",
    # BOSS 常见登录态元素
    "css:.nav-figure", "css:.user-info", "css:.user-pic", "css:.name-text",
    "css:.header-login-btn", "css:.btn-sign-up", "css:.nav-label",
    # 智联常见登录态元素
    "css:.header-user", "css:.user-name", "css:.header-loginout", "css:.loginout",
    "css:.zd-header-user", "css:[class*='userinfo']", "css:[class*='user-name']",
    # 通用
    "css:[class*='avatar']", "css:[class*='user']", "css:[class*='logout']",
    "text:登录", "text:注册", "text:我的简历", "text:消息",
]

def check_platform(name: str):
    cfg = PLATFORMS[name]
    print(f"\n{'='*60}\n=== 平台: {name} (端口 {cfg['port']}) ===\n{'='*60}")
    co = ChromiumOptions()
    co.set_address(f"127.0.0.1:{cfg['port']}")
    co.set_timeouts(20)
    try:
        page = ChromiumPage(co)
    except Exception as e:
        print(f"[FAIL] 附加浏览器失败: {e}")
        return

    print(f"[INFO] 附加后当前标签页 URL: {page.url}")
    try:
        page.get(cfg["login_check_url"], timeout=20)
    except Exception as e:
        print(f"[FAIL] 导航 {cfg['login_check_url']} 失败: {e}")
        return
    print(f"[OK] 已导航，URL: {page.url}")
    print("[..] 等待 JS 渲染 10s …")
    time.sleep(10)
    print(f"[OK] 渲染后 URL: {page.url}")

    hits = []
    for cand in CANDIDATES:
        tag = " [REGISTRY]" if cand in cfg["registry_indicators"] else ""
        try:
            if cand.startswith("css:") and "*" in cand:
                eles = page.eles(cand, timeout=1)
                if eles:
                    cls = []
                    for el in eles[:6]:
                        try:
                            cls.append(el.attr("class") or "")
                        except Exception:
                            pass
                    print(f"[HIT-多]{tag} {cand} -> {len(eles)} 个, class 样例: {cls}")
                    hits.append(cand)
                else:
                    print(f"[MISS]{tag} {cand}")
                continue
            el = page.ele(cand, timeout=1.5)
            if el:
                txt = ""
                try:
                    txt = (el.text or "").strip()[:60]
                except Exception:
                    pass
                print(f"[HIT]{tag} {cand}  text={txt!r}")
                hits.append(cand)
            else:
                print(f"[MISS]{tag} {cand}")
        except Exception as e:
            print(f"[ERR]{tag} {cand}: {e}")

    print(f"\n=== {name} 命中汇总 ===")
    for h in hits:
        print(" ", h)

    # 兜底：扫描 body 内含登录态关键词的 class，便于人工确认
    try:
        body = page.ele("tag:body", timeout=2)
        if body:
            import re
            classes = re.findall(
                r'class="([^"]*(?:user|login|logout|quit|exit|avatar|uname|nick|member)[^"]*)"',
                body.html,
            )
            uniq = sorted(set(classes))
            print(f"\n=== {name} body 内登录态相关 class（去重前 50） ===")
            for c in uniq[:50]:
                print(" ", c)
    except Exception as e:
        print(f"[ERR] body 扫描失败: {e}")


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = ["boss", "zhilian"] if target == "all" else [target]
    for n in names:
        if n not in PLATFORMS:
            print(f"未知平台: {n}（可选 boss/zhilian/all）")
            sys.exit(1)
    for n in names:
        check_platform(n)


if __name__ == "__main__":
    main()
