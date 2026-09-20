"""任务#12 追查脚本（一次性）：智联登录态深挖 —— 区分「真已登录」与「DOM 同时残留登录/未登录块」。

只做导航与元素查询，不做任何点击/登录/提交动作。
"""
import time

from DrissionPage import ChromiumPage, ChromiumOptions

def main():
    co = ChromiumOptions()
    co.set_address("127.0.0.1:9250")
    co.set_timeouts(20)
    page = ChromiumPage(co)
    page.get("https://www.zhaopin.com/", timeout=20)
    print(f"URL: {page.url}")
    time.sleep(10)

    # 1) 「退出」元素上下文：parent 链 + 是否可见
    el = page.ele("text:退出", timeout=2)
    if el:
        print(f"\n[text:退出] tag={el.tag}, class={el.attr('class')!r}")
        try:
            print(f"  可见性 styles.display={el.styles.get('display')}, visibility={el.styles.get('visibility')}")
        except Exception as e:
            print(f"  styles 读取失败: {e}")
        p = el
        for i in range(5):
            try:
                p = p.parent()
                if not p:
                    break
                print(f"  parent[{i}] tag={p.tag} class={(p.attr('class') or '')[:80]!r}")
            except Exception:
                break

    # 2) 「登录/注册」元素上下文
    el2 = page.ele("text:登录/注册", timeout=2)
    if el2:
        print(f"\n[text:登录/注册] tag={el2.tag}, class={el2.attr('class')!r}")
        try:
            print(f"  可见性 display={el2.styles.get('display')}, visibility={el2.styles.get('visibility')}")
        except Exception as e:
            print(f"  styles 读取失败: {e}")

    # 3) 头部区域 HTML 快照（含登录态切换的关键容器）
    for sel in ["css:.home-header", "css:header", "css:[class*='c-login']", "css:[class*='home-login']"]:
        els = page.eles(sel, timeout=1)
        if els:
            print(f"\n[{sel}] {len(els)} 个")
            for e in els[:2]:
                try:
                    html = e.html[:1500]
                    print(html)
                except Exception:
                    pass

    # 4) cookie 侧证据：zhaopin.com 域下有无登录态 cookie（xhs 名称不猜，全列名）
    try:
        cookies = page.cookies(as_dict=False, all_domains=False)
        names = [c.get("name") for c in cookies]
        print(f"\n[cookies] zhaopin 域 cookie 名: {names}")
    except Exception as e:
        print(f"[ERR] cookie 读取失败: {e}")

    # 5) 备选检查页：个人中心 i.zhaopin.com 是否直接跳登录
    try:
        page.get("https://i.zhaopin.com/", timeout=20)
        time.sleep(8)
        print(f"\n[i.zhaopin.com] 最终 URL: {page.url}")
        for cand in ["css:.user-name", "css:[class*='user']", "text:退出", "text:登录", "css:.resume"]:
            hit = page.ele(cand, timeout=1.5)
            if hit:
                print(f"  {cand}: HIT text={(hit.text or '')[:40].strip()!r}")
            else:
                print(f"  {cand}: MISS")
    except Exception as e:
        print(f"[ERR] i.zhaopin.com 导航失败: {e}")


if __name__ == "__main__":
    main()
