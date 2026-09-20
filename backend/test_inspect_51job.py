"""探查 51job 岗位详情页的申请按钮结构"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "51job_scraper"))
from playwright.sync_api import sync_playwright

URL = "https://jobs.51job.com/guangzhou/170518784.html"

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9227")
    ctx = browser.contexts[0]
    page = ctx.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(4000)

    print("=== 页面标题 ===")
    print(page.title())

    print("\n=== 所有按钮文本 ===")
    btns = page.evaluate("""() => {
        const els = [...document.querySelectorAll('button, a, input[type=button], input[type=submit], [role=button]')];
        return els.slice(0, 80).map(e => ({
            tag: e.tagName,
            text: (e.innerText||e.value||'').trim().slice(0,40),
            cls: (e.className||'').toString().slice(0,80),
            id: e.id || ''
        })).filter(x => x.text);
    }""")
    for b in btns:
        print(f"  <{b['tag']}> id={b['id']!r} text={b['text']!r} class={b['cls'][:60]!r}")

    print("\n=== 含'申'/'投'/'递'字样的元素 ===")
    matches = page.evaluate("""() => {
        const all = [...document.querySelectorAll('*')];
        const hit = [];
        for (const e of all) {
            const t = (e.innerText||'').trim();
            if ((t.includes('申') || t.includes('投') || t.includes('递')) && t.length < 30) {
                hit.push({tag: e.tagName, text: t, cls: (e.className||'').toString().slice(0,80)});
                if (hit.length >= 20) break;
            }
        }
        return hit;
    }""")
    for m in matches:
        print(f"  <{m['tag']}> text={m['text']!r} class={m['cls'][:60]!r}")

    print("\n=== 当前URL ===")
    print(page.url)

    page.close()
