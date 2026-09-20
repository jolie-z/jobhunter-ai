import os
import sys
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

# 确保 backend 与 zhilian_scraper 路径在 sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENGINE_DIR = _BACKEND_DIR / "zhilian_scraper"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

import zhilian_auto_delivery
from app.core.feishu_utils import download_feishu_file
from DrissionPage._pages.chromium_base import ChromiumBase
from DrissionPage._elements.none_element import NoneElement
from DrissionPage._elements.chromium_element import ChromiumElementsList


def test_resume_name_sanitization_removes_slash_and_illegal_chars():
    """测试特殊字符（斜杠、空格等）在定制物料命名时被严格清洗"""
    import re
    # 模拟包含斜杠的岗位名
    job_title = "地图产品经理/双休"
    company = "深圳市睿服科技有限公司"
    raw_name = f"{company}_{job_title}".replace('.pdf', '')
    cleaned = re.sub(r'[\/\\:\*\?"<>\|\s]+', '_', raw_name).strip('_')
    assert "/" not in cleaned
    assert "\\" not in cleaned
    assert cleaned == "深圳市睿服科技有限公司_地图产品经理_双休"

    # 模拟飞书传参 pdf_name 也包含非法斜杠
    passed_pdf_name = "深圳市睿服科技有限公司_地图产品经理/双.pdf"
    raw_from_passed = passed_pdf_name.replace('.pdf', '')
    cleaned_passed = re.sub(r'[\/\\:\*\?"<>\|\s]+', '_', raw_from_passed).strip('_')
    assert "/" not in cleaned_passed
    assert cleaned_passed == "深圳市睿服科技有限公司_地图产品经理_双"


def test_download_feishu_file_ensures_nested_directory(tmp_path):
    """测试 download_feishu_file 在保存路径目录不存在时会自动创建目录而不会抛出 FileNotFoundError"""
    deep_path = tmp_path / "sub1" / "sub2" / "test_resume.pdf"
    
    with patch("app.core.feishu_utils.get_tenant_access_token", return_value="fake_token"), \
         patch("app.core.feishu_utils.safe_feishu_request") as mock_req:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_content.return_value = [b"%PDF-fake-content"]
        mock_req.return_value = mock_resp

        ok = download_feishu_file("fake_file_token", str(deep_path))
        assert ok is True
        assert deep_path.exists()
        assert deep_path.read_bytes() == b"%PDF-fake-content"


def test_chromium_base_monkey_patch_catches_search_id_key_error():
    """测试 ChromiumBase._find_elements 被 monkey-patch 后，遇 KeyError('searchId') 不崩溃，安全返回 NoneElement / ChromiumElementsList"""
    fake_self = MagicMock(spec=ChromiumBase)
    fake_self._none_ele_value = None

    with patch.object(zhilian_auto_delivery, "_orig_find_elements", side_effect=KeyError("searchId")):
        # index=1 时为 ele() 查询，应返回 NoneElement
        res_ele = ChromiumBase._find_elements(fake_self, "css:button", timeout=0.1, index=1)
        assert isinstance(res_ele, NoneElement)

        # index=None 时为 eles() 查询，应返回 ChromiumElementsList
        res_eles = ChromiumBase._find_elements(fake_self, "css:button", timeout=0.1, index=None)
        assert isinstance(res_eles, ChromiumElementsList)


def test_kill_popups_pure_js_executes_safely():
    """测试 _kill_popups 在纯 JS 异常时不崩溃"""
    fake_tab = MagicMock()
    fake_tab.run_js.side_effect = Exception("Tab crashed or JS evaluation failed")
    # 不应抛出异常
    zhilian_auto_delivery._kill_popups(fake_tab, max_rounds=2)


def test_chat_session_owner_probe_matching():
    """测试微聊会话归属验证：公司名去后缀核心字号、全称或岗位名匹配"""
    import re
    company = "深圳市腾讯计算机系统有限公司"
    job_title = "AI应用产品经理"
    
    core = re.sub(r'股份有限公司|有限公司|有限责任公司|分公司|集团', '', company).strip()
    assert core == "深圳市腾讯计算机系统"
    
    probes = []
    if core and core != company:
        probes.append(core)
    probes.append(company)
    probes.append(job_title)

    assert "深圳市腾讯计算机系统" in probes
    assert "深圳市腾讯计算机系统有限公司" in probes
    assert "AI应用产品经理" in probes

    # 模拟微聊窗口包含公司简称或岗位名
    fake_page_text = "您好！关于 深圳市腾讯计算机系统 的 AI应用产品经理 职位"
    assert any(probe in fake_page_text for probe in probes)


def test_is_logged_in_robust_against_lingering_job_detail_tab():
    """测试 _is_logged_in 面对浏览器残留的岗位详情页时不误判为未登录"""
    fake_page = MagicMock()
    # 模拟最新激活的 tab 是岗位详情页（不含 i.zhaopin.com）
    wrong_tab = MagicMock()
    wrong_tab.url = "https://www.zhaopin.com/jobdetail/CC12345.htm"
    fake_page.latest_tab = wrong_tab

    # 模拟后台存在真正的简历中心 tab
    resume_tab = MagicMock()
    resume_tab.url = "https://i.zhaopin.com/resume"
    resume_tab.ele.return_value = None  # 无扫码登录/手机号登录元素

    fake_page.get_tab.side_effect = lambda url=None: resume_tab if url == "i.zhaopin.com" else None
    fake_page.tab_ids = ["tab_wrong", "tab_resume"]

    logged_in = zhilian_auto_delivery._is_logged_in(fake_page)
    assert logged_in is True


def test_failure_triage_recognizes_wechat_blocked_as_transient():
    """测试 [微聊受阻] 结构化错误被分诊为暂时性故障（支持单独重试自愈）"""
    from app.automation.failure_triage import classify_delivery_failure
    err = "❌ 智联投递引擎执行失败：[微聊受阻] 附件简历已成功送达，打招呼语未成功发送"
    assert classify_delivery_failure(err) == "transient"
    assert classify_delivery_failure("[微聊受阻] 附件简历已投递成功，但微聊打招呼语未成功发送") == "transient"


