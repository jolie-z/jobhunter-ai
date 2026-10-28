"""智联失效页检测与链接预检（2026-10-11 泰索斯事故回归锁）。

事故：岗位已被智联下架，失效横幅「该职位已失效」是图片（ic-offline.png）而非 DOM
文本，引擎的文本关键词匹配从原理上不可能命中，落进笼统 [状态] 兜底——错误语义误导
排查（"页面改版"），且死岗位走完了附件删旧传新（用户最旧的在线附件被无用腾挪）。

覆盖：
- _detect_dead_job_page：DOM 签名优先（ic-offline / summary-planes__info.invalid）+
  文本关键词兜底；活页零误判
- link_precheck 智联扩展：平台门控 / check_zhilian_link_sync 三态契约（True/False/None
  不误杀）/ build_checked_batch 双平台门控流转
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.automation.link_precheck import (
    _ensure_zhilian_path,
    build_checked_batch,
    check_zhilian_link_sync,
    is_zhilian_platform,
    precheck_zhilian_link,
)

# 生产同款：link_precheck 懒注入 zhilian_scraper 到 sys.path，测试须先行注入
_ensure_zhilian_path()
from zhilian_scraper.zhilian_auto_delivery import _detect_dead_job_page  # noqa: E402


def _tab(css_hits=(), text_hits=(), nothing=False):
    """智联页面桩：按查询串命中；nothing=True 时全部查询返回 None（活页）。"""
    tab = MagicMock()
    css, text = set(css_hits), set(text_hits)

    def ele(query, timeout=1):
        if nothing:
            return None
        if query.startswith("css:") and query[4:] in css:
            return object()
        if query.startswith("text:") and query[5:] in text:
            return object()
        return None

    tab.ele.side_effect = ele
    return tab


# ---------- _detect_dead_job_page ----------

def test_detect_dead_job_page_by_dom_signature():
    """泰索斯事故核心：失效横幅是图片（ic-offline），DOM 签名必须能命中"""
    tab = _tab(css_hits=[".summary-planes__invalid-text"])
    hint = _detect_dead_job_page(tab)
    assert "ic-offline" in hint

    tab2 = _tab(css_hits=[".summary-planes__info.invalid"])
    hint2 = _detect_dead_job_page(tab2)
    assert "失效态容器" in hint2


def test_detect_dead_job_page_text_fallback():
    """文本关键词兜底（对文本型失效页仍有效）"""
    hint = _detect_dead_job_page(_tab(text_hits=["职位已下架"]))
    assert "职位已下架" in hint


def test_detect_dead_job_page_alive_returns_empty():
    """活页（无失效签名无失效文本）返回空串，不得误判"""
    assert _detect_dead_job_page(_tab(nothing=True)) == ""


def test_detect_dead_job_page_never_raises():
    """ele 异常时静默返回空串（探测绝不阻断投递主流程）"""
    tab = MagicMock()
    tab.ele.side_effect = RuntimeError("element invalid")
    assert _detect_dead_job_page(tab) == ""


# ---------- link_precheck 智联扩展 ----------

def test_platform_gate():
    assert is_zhilian_platform("智联招聘")
    assert is_zhilian_platform("zhilian")
    assert not is_zhilian_platform("BOSS直聘")


def test_check_zhilian_link_sync_dead_link():
    """失效签名命中 → False（确定死链）"""
    with patch("zhilian_auto_delivery._get_shared_browser") as m_browser, \
         patch("zhilian_auto_delivery._is_logged_in", return_value=True), \
         patch("zhilian_auto_delivery._detect_dead_job_page", return_value="失效页横幅图片（ic-offline）"):
        assert check_zhilian_link_sync("https://www.zhaopin.com/x.htm") is False


def test_check_zhilian_link_sync_alive():
    """有主操作区按钮且无失效签名 → True（活链）"""
    page = MagicMock()
    page.eles.return_value = [object()]
    with patch("zhilian_auto_delivery._get_shared_browser", return_value=page), \
         patch("zhilian_auto_delivery._is_logged_in", return_value=True), \
         patch("zhilian_auto_delivery._detect_dead_job_page", return_value=""):
        assert check_zhilian_link_sync("https://www.zhaopin.com/x.htm") is True


def test_check_zhilian_link_sync_undetermined_never_kills():
    """登录态不可用 / 无按钮无签名 / 浏览器不可用 → None（保留岗位，不误杀）"""
    with patch("zhilian_auto_delivery._get_shared_browser") as m_browser, \
         patch("zhilian_auto_delivery._is_logged_in", return_value=False):
        assert check_zhilian_link_sync("https://x") is None

    page = MagicMock()
    page.eles.return_value = []
    with patch("zhilian_auto_delivery._get_shared_browser", return_value=page), \
         patch("zhilian_auto_delivery._is_logged_in", return_value=True), \
         patch("zhilian_auto_delivery._detect_dead_job_page", return_value=""):
        assert check_zhilian_link_sync("https://x") is None

    with patch("zhilian_auto_delivery._get_shared_browser", side_effect=RuntimeError("no browser")), \
         patch("zhilian_auto_delivery._is_logged_in", return_value=True):
        assert check_zhilian_link_sync("https://x") is None


def test_build_checked_batch_gates_zhilian():
    """build_checked_batch 门控流转：智联死链被剔除并标「已下架」，活链进批次"""
    jobs = [
        {"record_id": "recDead", "platform": "智联招聘", "feishu_fields": {"岗位链接": {"link": "https://z/dead"}}, "_created_time": 2, "company_name": "死岗位", "job_name": "x"},
        {"record_id": "recAlive", "platform": "智联招聘", "feishu_fields": {"岗位链接": {"link": "https://z/alive"}}, "_created_time": 1, "company_name": "活岗位", "job_name": "y"},
    ]

    async def fake_precheck(url):
        return False if "dead" in url else True

    updated = []

    import app.services.feishu_service as _fs
    with patch("app.automation.link_precheck.precheck_zhilian_link", side_effect=fake_precheck), \
         patch.object(_fs, "update_feishu_record", side_effect=lambda rid, fields: updated.append((rid, fields))), \
         patch("app.automation.pipeline_broadcast.emit_log", side_effect=lambda *a, **k: asyncio.sleep(0)):
        batch = asyncio.run(build_checked_batch(jobs, batch_limit=5, pipeline_task_id="t1"))

    ids = [j["record_id"] for j in batch]
    assert "recDead" not in ids, "死链必须被剔除"
    assert "recAlive" in ids
    assert ("recDead", {"跟进状态": "已下架"}) in updated, "死链必须同步标已下架"
