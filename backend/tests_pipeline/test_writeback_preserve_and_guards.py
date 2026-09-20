"""
回写「保留口径」与守卫逻辑单测（2026-08-31 智联白纸事故修复包）。

背景：智联官网 Vuex store 对象先于业务数据填充，读取方（采集/回写）在冷加载窗口
会拿到「resumeId 在、内容全空」的假壳——规划层误判官网为空简历全量新增，复核层
误报大面积不一致。同时历史映射产出过非法求职状态值 0，官网永远不生效却回执成功。

覆盖（纯函数 / 注入假对象，绝不真调浏览器与官网接口）：
1. browser_common.wait_resume_filled：内容填充轮询（yes / empty / timeout）
2. zhilian _is_unfilled_shell：空壳判定
3. zhilian verify_results 覆盖语义：官网未清干净的快照外条目=删除未生效=异常；
   名字比对容忍官网自动插入的中英文间空格
4. job51 求职状态守卫：非法值 0（含数字形态）→ 保留官网原值并告警；复核豁免非法值
5. mapper apply 数组整组替换语义（用户拍板 2026-08-31：官网=快照，不做条目级保留）
6. 预检免导航：同根域不导航（未命中按存疑放行）、跨域仍导航照旧判 EXPIRED
"""
import importlib
import os
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLATFORMS_DIR = os.path.join(BACKEND_DIR, "resume_editor", "platforms")

sys.path.insert(0, PLATFORMS_DIR)

import browser_common as bc  # noqa: E402


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(PLATFORMS_DIR, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


zw = _load("zhilian_wb_under_test", "zhilian_write_back.py")
j51 = _load("job51_wb_under_test", "job51_write_back.py")


# ---------- 1. wait_resume_filled（填充轮询） ----------

class _FakeStorePage:
    """按注入序列依次应答 run_js 的假页面。"""

    def __init__(self, states):
        self._states = list(states)
        self._i = 0

    def run_js(self, js, timeout=None):
        self._i += 1
        return self._states[min(self._i - 1, len(self._states) - 1)]


def test_wait_resume_filled_yes_on_first_poll():
    assert bc.wait_resume_filled(_FakeStorePage(["yes"]), tries=3, interval=0) == "yes"


def test_wait_resume_filled_waits_until_filled():
    assert bc.wait_resume_filled(_FakeStorePage(["no", "no", "yes"]), tries=5, interval=0) == "yes"


def test_wait_resume_filled_timeout_on_persistent_no():
    assert bc.wait_resume_filled(_FakeStorePage(["no"]), tries=3, interval=0) == "timeout"


def test_wait_resume_filled_js_exception_counts_as_not_ready():
    page = _FakeStorePage(["yes"])
    page.run_js = lambda js, timeout=None: (_ for _ in ()).throw(RuntimeError("js fail"))
    assert bc.wait_resume_filled(page, tries=2, interval=0) == "timeout"


# ---------- 2. 空壳判定 ----------

_SHELL_NODES = ("Profile", "WorkExperience", "EducationExperience", "ProjectExperience",
                "TrainExperience", "LanguageSkill", "ProfessionalSkill", "Certificate",
                "SelfEvaluate", "UnifiedPurpose")


def test_is_unfilled_shell_true_when_resumeid_but_all_empty():
    data = {"resumeId": 338953037, **{k: [] for k in _SHELL_NODES}}
    assert zw._is_unfilled_shell(data) is True


def test_is_unfilled_shell_false_when_any_node_has_content():
    data = {"resumeId": 338953037, "Profile": [{"name": "x"}], "WorkExperience": []}
    assert zw._is_unfilled_shell(data) is False


def test_is_unfilled_shell_true_without_resumeid():
    assert zw._is_unfilled_shell({k: [] for k in _SHELL_NODES}) is True


# ---------- 3. zhilian 复核口径（用户拍板：官网=快照，覆盖删除是设计内行为） ----------

def _zskill(name, path):
    # proskillUseTime 用纯数字月数：官网 NaN月 修正逻辑对「N年」形态恒判异（设计如此）
    return {"path": path, "proskillName": name, "proskillType": "12",
            "proskillLevel": "3", "proskillUseTime": "12"}


def test_zhilian_verify_site_extras_mean_delete_failed():
    """官网仍留着快照未含的条目 = 删除未生效 = 异常"""
    local = {"skill_tags": [_zskill("Python", "p1")]}
    off = {"ProfessionalSkill": [_zskill("Python", "p1"), _zskill("Java", "p2"), _zskill("Go", "p3")]}
    out = zw.verify_results(off, local, {"actions": [{"module": "skill_tags"}]})
    assert out[0]["match"] is False
    assert "官网仍有 2 条" in out[0]["note"] and "删除未生效" in out[0]["note"]


def test_zhilian_verify_conformed_module_passes():
    local = {"skill_tags": [_zskill("Python", "p1"), _zskill("Go", "p3")]}
    off = {"ProfessionalSkill": [_zskill("Python", "p1"), _zskill("Go", "p3")]}
    out = zw.verify_results(off, local, {"actions": [{"module": "skill_tags"}]})
    assert out[0]["match"] is True


def test_zhilian_verify_missing_local_item_still_anomaly():
    local = {"skill_tags": [_zskill("Python", "p1"), _zskill("Rust", "p9")]}
    off = {"ProfessionalSkill": [_zskill("Python", "p1")]}
    out = zw.verify_results(off, local, {"actions": [{"module": "skill_tags"}]})
    assert out[0]["match"] is False
    assert "Rust" in out[0]["note"]


def test_zhilian_verify_name_match_ignores_cjk_latin_spaces():
    """官网自动在中英文间插空格（'AI驱动的' 存为 'AI 驱动的'），名字比对必须容忍"""
    local = {"skill_tags": [_zskill("AI驱动的自动化系统", "p1")]}
    off = {"ProfessionalSkill": [{"path": "p1", "proskillName": "AI 驱动的自动化系统",
                                  "proskillType": "12", "proskillLevel": "3", "proskillUseTime": "12"}]}
    out = zw.verify_results(off, local, {"actions": [{"module": "skill_tags"}]})
    assert out[0]["match"] is True


def test_zhilian_verify_certs_extra_means_delete_failed():
    local = {"certificates": [{"certUserdefName": "CET-6"}]}
    off = {"Certificate": [{"certUserdefName": "CET-6"}, {"certUserdefName": "驾照"}]}
    out = zw.verify_results(off, local, {"actions": [{"module": "certificates"}]})
    assert out[0]["match"] is False
    assert "删除未生效" in out[0]["note"]


# ---------- 4. job51 求职状态守卫 ----------

def test_j51_resolve_situation_illegal_int_zero_keeps_official():
    # 数字 0（falsy）是历史映射的真实产出形态，必须被识别为非法而不是「本地为空」
    val, warn = j51._resolve_current_situation({"currentSituation": 0}, {"currentSituation": "1"})
    assert val == "1"
    assert warn and "'0'" in warn and "合法" in warn


def test_j51_resolve_situation_legal_value_wins():
    val, warn = j51._resolve_current_situation({"currentSituation": "3"}, {"currentSituation": "1"})
    assert val == "3"
    assert warn == ""


def test_j51_resolve_situation_empty_local_falls_back_to_official():
    val, warn = j51._resolve_current_situation({}, {"currentSituation": "2"})
    assert val == "2"
    assert warn == ""


def test_j51_verify_exempts_illegal_situation_value():
    local = {"basic_info": {"currentSituation": 0, "area": {"id": "1"}, "household": ""}}
    off = {"basic_info": {"currentSituation": "1", "area": {"id": "1"}, "household": ""}}
    out = j51.verify_results(off, local, {"actions": [{"module": "basic_info"}]})
    assert out[0]["match"] is True


def test_j51_verify_flags_legal_situation_mismatch():
    local = {"basic_info": {"currentSituation": "2", "area": "", "household": ""}}
    off = {"basic_info": {"currentSituation": "1", "area": "", "household": ""}}
    out = j51.verify_results(off, local, {"actions": [{"module": "basic_info"}]})
    assert out[0]["match"] is False
    assert "求职状态" in out[0]["note"]


# ---------- 5. mapper 数组语义（用户拍板：整组替换，不做条目级保留） ----------

def _am():
    return importlib.import_module("resume_editor.agent_mapper")


def test_mapper_apply_replaces_array_wholesale():
    """apply 对数组字段是整组替换——快照未含的旧条目随之删除，属设计内行为"""
    am = _am()
    fields = {"projects": {"current_value": [{"proExpProjectName": "旧项目"}]}}
    entries = [{"path": "projects", "value": [{"proExpProjectName": "新项目"}]}]
    result = am.apply_mapping(fields, entries)
    assert result["applied"] == ["projects"]
    items = fields["projects"]["current_value"]
    assert [i["proExpProjectName"] for i in items] == ["新项目"]


# ---------- 6. 预检免导航 ----------

from app.session import health_checker as hc  # noqa: E402
from app.session.models import PlatformConfig, SessionState  # noqa: E402


class _PrecheckPage:
    """模拟 DrissionPage page：可选 url 属性（旧调用方假对象可能没有）。"""

    def __init__(self, url=None, present=()):
        if url is not None:
            self.url = url
        self.present = set(present)
        self.navigated_to = []

    def get(self, url, timeout=None):
        self.navigated_to.append(url)

    def ele(self, locator, index=1, timeout=None):
        if index != 1:
            return None
        return object() if locator in self.present else None


def _cfg(platform="boss", url="https://www.zhipin.com/", indicators=("css:.user-nav",)):
    return PlatformConfig(name=platform, display_name=platform, port=1,
                          login_check_url=url, login_indicators=list(indicators))


@pytest.fixture(autouse=True)
def _port_open(monkeypatch):
    monkeypatch.setattr(hc, "probe_port", lambda *a, **k: True)


def test_precheck_same_site_hits_indicator_no_navigate():
    page = _PrecheckPage(url="https://www.zhipin.com/job_detail/1.html", present={"css:.user-nav"})
    st = hc.check_login_via_dom(_cfg(), page_factory=lambda p: page)
    assert st.state == SessionState.HEALTHY
    assert page.navigated_to == []


def test_precheck_same_site_miss_indicators_unknown_release():
    page = _PrecheckPage(url="https://www.zhipin.com/job_detail/1.html", present=())
    st = hc.check_login_via_dom(_cfg(), page_factory=lambda p: page)
    assert st.state == SessionState.UNKNOWN
    assert page.navigated_to == []


def test_precheck_subdomain_counts_as_same_site():
    page = _PrecheckPage(url="https://i.zhaopin.com/resume", present=())
    st = hc.check_login_via_dom(
        _cfg("zhilian", "https://www.zhaopin.com/", ("css:.c-login__top__name",)),
        page_factory=lambda p: page)
    assert st.state == SessionState.UNKNOWN
    assert page.navigated_to == []


def test_precheck_off_site_still_navigates_and_expired():
    page = _PrecheckPage(url="https://example.com/x", present=())
    st = hc.check_login_via_dom(_cfg(), page_factory=lambda p: page)
    assert st.state == SessionState.EXPIRED
    assert page.navigated_to == ["https://www.zhipin.com/"]


def test_precheck_page_without_url_attr_keeps_legacy_behavior():
    page = _PrecheckPage(present=())  # 旧假对象无 url 属性 → getattr 兜底走原导航路径
    st = hc.check_login_via_dom(_cfg(), page_factory=lambda p: page)
    assert st.state == SessionState.EXPIRED
    assert page.navigated_to == ["https://www.zhipin.com/"]
