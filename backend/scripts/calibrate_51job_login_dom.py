"""一次性校准脚本：附加 9227 端口的 51job 浏览器，实测登录态 DOM 选择器。

仅做导航与元素查询，不做任何点击/登录/提交动作。
用途：为 registry 的 51job login_check_url / login_indicators 提供实测依据。
"""
import sys
import time

from DrissionPage import ChromiumPage, ChromiumOptions

CANDIDATES = [
    # CSS 候选
    "css:.uname", "css:.user-name", "css:.username", "css:.header-user",
    "css:.user-info", "css:.userInfo", "css:.avatar", "css:.user-avatar",
    "css:.header-user-name", "css:.user-name-box", "css:.nick-name",
    "css:[class*='user']", "css:[class*='avatar']", "css:[class*='uname']",
    "css:[class*='logout']", "css:[class*='quit']",
    # 文本候选
    "text:退出登录", "text:退出", "text:我的简历", "text:个人中心", "text:账号设置",
]

def main():
    co = ChromiumOptions()
    co.set_address("127.0.0.1:9227")
    co.set_timeouts(20)
    try:
        page = ChromiumPage(co)
    except Exception as e:
        print(f"[FAIL] 附加浏览器失败: {e}")
        sys.exit(1)

    try:
        page.get("https://we.51job.com/", timeout=20)
    except Exception as e:
        print(f"[FAIL] 导航 we.51job.com 失败: {e}")
        sys.exit(1)

    print(f"[OK] 已导航，当前 URL: {page.url}")
    print("[..] 等待 JS 渲染…")
    time.sleep(6)
    print(f"[OK] 渲染后 URL: {page.url}")

    hits = []
    for cand in CANDIDATES:
        try:
            if cand.startswith("css:") and ("*" in cand):
                eles = page.eles(cand, timeout=1)
                if eles:
                    cls = []
                    for el in eles[:5]:
                        try:
                            cls.append(el.attr("class") or "")
                        except Exception:
                            pass
                    print(f"[HIT-多] {cand} -> {len(eles)} 个元素, class 样例: {cls}")
                    hits.append(cand)
                continue
            el = page.ele(cand, timeout=1)
            if el:
                txt = ""
                try:
                    txt = (el.text or "").strip()[:50]
                except Exception:
                    pass
                print(f"[HIT] {cand}  text={txt!r}")
                hits.append(cand)
            else:
                print(f"[MISS] {cand}")
        except Exception as e:
            print(f"[ERR] {cand}: {e}")

    print("\n=== 命中汇总 ===")
    for h in hits:
        print(h)

    # 兜底：打印页面内所有含 user/logout/quit/exit 的 class，便于人工确认
    try:
        raw = page.ele("tag:body", timeout=2)
        if raw:
            import re
            classes = re.findall(r'class="([^"]*(?:user|logout|quit|exit|avatar|uname|nick)[^"]*)"', raw.html)
            uniq = sorted(set(classes))
            print("\n=== body 内含 user/logout/avatar 的 class（去重前 40） ===")
            for c in uniq[:40]:
                print(" ", c)
    except Exception as e:
        print(f"[ERR] body 扫描失败: {e}")


if __name__ == "__main__":
    main()
