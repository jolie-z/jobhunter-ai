"""51job 采集数据源 — 页面 DOM sensorsdata 提取（Vue SSR 结构化数据）。

2026-09-24 真机修正（替代原 search-pc 页内 fetch 方案）：
现版搜索页是 Vue SSR——岗位数据由服务端渲染进 DOM，每个卡片挂 sensorsdata
属性（完整结构化 JSON：jobId/jobTitle/jobSalary/jobArea/jobDegree/jobYear/
jobLabel/companyId 等），没有任何公开 JSON 接口（旧 search-pc 已不被现 SPA
识别，请求会返回 200+text/html 首页，曾被 risk_guard 判 L3 终止）。

DOM 提取的优势：零额外请求（暴露面比接口方案更小）、不怕接口改版/签名。
福利标签/关键字/公司信息/行业/规模等字段卡片常缺失（jobLabel 等键留空兜底），
JD 正文卡片上没有——由 collector 对入库条目逐条开详情页补采
（fetch_detail_info 一次开页全采，15-35s 随机间隔）。
"""
import os
import time

from risk_guard import RiskLevel

API_PAGE_SIZE = 20    # 每页卡片数（与页面渲染一致）
HARD_MAX_PAGES = 50   # 51job 搜索结果原生封顶（20×50=1000），非防御值
API_MAX_RPM = int(os.environ.get("51JOB_API_MAX_RPM", "12"))  # 语义保留：页刷新频率上限

# 滑动窗口限流：max_rpm 次/分钟（对"翻页刷新"计时）
_RATE_WINDOW: list[float] = []


def _rate_limit_wait() -> float:
    """返回需要等待的秒数（不阻塞时为 0），并登记本次请求时刻。"""
    global _RATE_WINDOW
    now = time.time()
    _RATE_WINDOW = [t for t in _RATE_WINDOW if now - t < 60]
    if len(_RATE_WINDOW) >= API_MAX_RPM:
        wait = 60 - (now - _RATE_WINDOW[0]) + 0.5
        _RATE_WINDOW.append(now + wait)
        return max(wait, 0.0)
    _RATE_WINDOW.append(now)
    return 0.0


def real_last_page(total_count: int, fallback: int = HARD_MAX_PAGES) -> int:
    """由 totalCount 反推真实末页（ceil(total/20)），与 fallback 取小，不小于 1。"""
    if total_count <= 0:
        return 1
    return min(max(1, fallback), (total_count + API_PAGE_SIZE - 1) // API_PAGE_SIZE)


# DOM 提取 JS：从 sensorsdata 属性拿结构化岗位 + 从分页区拿总数
_EXTRACT_JS = r"""() => {
    const out = [];
    document.querySelectorAll('.joblist-item').forEach(card => {
        const el = card.querySelector('[sensorsdata]');
        if (!el) return;
        try {
            const d = JSON.parse(el.getAttribute('sensorsdata').replace(/&quot;/g, '"'));
            if (d.jobId) {
                d.jobHref = card.querySelector('a[href*="51job.com"]')?.href || '';
                d.companyName = card.querySelector('.cname, [class*="cname"], [class*="company"]')?.innerText?.trim() || '';
                out.push(d);
            }
        } catch (e) {}
    });
    let total = 0;
    const totalEl = document.querySelector('.el-pagination__total, [class*="total"]');
    if (totalEl) { const m = (totalEl.textContent || '').match(/(\d+)/); if (m) total = parseInt(m[1], 10); }
    return { items: out, total, bodyHead: (document.body ? document.body.innerText : '').slice(0, 3000) };
}"""


def fetch_search_page(page, keyword: str, city_code: str, salary_code: str, page_num: int) -> dict:
    """从搜索页 DOM 提取一页岗位。

    返回 {'level': RiskLevel, 'items': [...], 'total': int, 'reason': str}——
    返回结构与旧接口版完全一致，collector 无需改判定逻辑。

    调用约定：page_num==1 时调用方负责先 goto 搜索 URL；page_num>1 由调用方
    点击「下一页」后再次调用本函数（DOM 即最新页数据）。
    """
    wait = _rate_limit_wait()
    if wait > 0:
        time.sleep(wait)

    try:
        # 等卡片渲染（SSR 首屏直出，超时=页面异常/被拦）
        page.wait_for_selector(".joblist-item [sensorsdata]", timeout=15000)
    except Exception:
        body_head = ""
        try:
            body_head = page.inner_text("body", timeout=3000)[:3000]
        except Exception:
            pass
        # 页面文本含验证墙文案 → L3；否则按技术异常 L1（可能网络/渲染慢）
        from risk_guard import classify_page_signal
        sig = classify_page_signal(body_head)
        if sig is not None:
            return {"level": sig, "items": [], "total": 0, "reason": f"页面信号: {sig.name}"}
        return {"level": RiskLevel.L1_SOFT, "items": [], "total": 0,
                "reason": "岗位卡片 15s 未渲染（超时/网络）"}

    r = page.evaluate(_EXTRACT_JS)
    items = r.get("items") or []
    total = int(r.get("total") or 0)
    body_head = r.get("bodyHead") or ""

    # 页面级验证墙检测（L3 优先）
    from risk_guard import classify_page_signal
    sig = classify_page_signal(body_head)
    if sig is not None:
        return {"level": sig, "items": [], "total": 0, "reason": f"页面信号: {sig.name}"}

    if not items:
        # 卡片选择器命中但 sensorsdata 空 → 结构改版（L1 降级 DOM 旧解析路径）
        return {"level": RiskLevel.L1_SOFT, "items": [], "total": total,
                "reason": "sensorsdata 提取为空（页面结构可能改版）"}

    return {"level": RiskLevel.L0_OK, "items": items, "total": total, "reason": ""}
