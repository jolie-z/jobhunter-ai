"""任务#12 追查脚本（一次性）：复刻 check_login_via_dom 的时序，验证「渲染等待不足 → 假阴性」。

流程与 health_checker.check_login_via_dom 完全一致（附加端口 → page.get → 立即按 indicators 查询），
随后每 1s 复测一次各 indicator，观察登录元素出现的时间线。
只做导航与元素查询，不做任何点击/登录/提交动作。
"""
import time

from DrissionPage import ChromiumPage, ChromiumOptions

PLATFORMS = {
    "boss": ("127.0.0.1:19222", "https://www.zhipin.com/", ["css:.user-nav", "text:退出登录"]),
    "zhilian": ("127.0.0.1:9250", "https://www.zhaopin.com/", ["css:.user-nav", "css:.header-user-info", "text:退出"]),
}


def main():
    for name, (addr, url, indicators) in PLATFORMS.items():
        print(f"\n=== {name}：复刻 check_login_via_dom 时序 ===")
        co = ChromiumOptions()
        co.set_address(addr)
        co.set_timeouts(15)
        page = ChromiumPage(co)
        t0 = time.time()
        page.get(url, timeout=15)
        print(f"page.get 返回耗时 {time.time()-t0:.1f}s，URL: {page.url}")

        prev = 0
        for sec in [0, 1, 2, 3, 5, 8]:
            if sec:
                time.sleep(sec - prev)
            prev = sec
            line = []
            for ind in indicators:
                hit = page.ele(ind, timeout=2)  # 与 INDICATOR_WAIT_S=2 一致
                line.append(f"{ind}={'HIT' if hit else 'MISS'}")
            print(f"  t=+{sec}s: {' | '.join(line)}")

        # 补测实测可用的候选
        extras = {"boss": ["css:.nav-figure", "css:.user-photo"],
                  "zhilian": ["css:.c-login__top__name", "css:.c-login__top__img", "css:.basic-info__name"]}
        for ind in extras[name]:
            hit = page.ele(ind, timeout=1)
            txt = ""
            if hit:
                try:
                    txt = (hit.text or "").strip()[:30]
                except Exception:
                    pass
            print(f"  [候选] {ind}: {'HIT %r' % txt if hit else 'MISS'}")


if __name__ == "__main__":
    main()
