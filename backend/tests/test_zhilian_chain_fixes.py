"""智联投递链路 17 项 bug 修复的回归测试。

覆盖 2026-09-12 质检修复的关键行为：
1. 主操作区按钮状态机（全页文本搜索误判「已投递」回归防护）；
2. 投递结果正向断言（按钮找不到时不得假报已投递）；
3. 打招呼语合法性校验（「❌ AI 服务未配置」错误文本严禁当欢迎语）；
4. quick_greeting_node 禁止 LLM 现场编造海投语；
5. 精投/海投统一判定口径 is_custom_record；
6. deliver_approved 批量投递防抖锁；
7. 批量编排预扫描：跳过已投递 + 平台白名单；
8. 失败分诊结构化错误标签。
"""
import asyncio
import sys
from pathlib import Path

import pytest

import app.automation.failure_triage as failure_triage
import app.automation.routes.delivery_router as delivery_router
import app.automation.scheduler as sched
import app.automation.workflow as wf
import app.services.feishu_service as feishu_service
from app.core.feishu_utils import is_custom_record
from app.core.utils import is_valid_greeting

# 引擎模块（含 DrissionPage 依赖），导入失败则跳过引擎相关用例
_ENGINE_DIR = Path(__file__).resolve().parent.parent / "zhilian_scraper"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))
try:
    import zhilian_auto_delivery as zhilian_engine
    HAS_ENGINE = True
except Exception:
    HAS_ENGINE = False


# ---------------- 1. 主操作区按钮状态机（Bug 1/2/13/14） ----------------

@pytest.mark.skipif(not HAS_ENGINE, reason="DrissionPage 不可用")
def test_classify_deliverable_when_apply_button_present():
    assert zhilian_engine._classify_main_buttons(["立即投递"]) == "deliverable"
    assert zhilian_engine._classify_main_buttons(["申请职位", "收藏"]) == "deliverable"


@pytest.mark.skipif(not HAS_ENGINE, reason="DrissionPage 不可用")
def test_classify_delivered_state():
    assert zhilian_engine._classify_main_buttons(["已投递"]) == "delivered"
    assert zhilian_engine._classify_main_buttons(["继续申请"]) == "delivered"
    assert zhilian_engine._classify_main_buttons(["继续沟通"]) == "delivered"
    assert zhilian_engine._classify_main_buttons(["聊一聊", "与TA沟通"]) == "delivered"
    assert zhilian_engine._classify_main_buttons(["先聊聊"]) == "delivered"


@pytest.mark.skipif(not HAS_ENGINE, reason="DrissionPage 不可用")
def test_classify_unknown_when_no_button():
    assert zhilian_engine._classify_main_buttons([]) == "unknown"
    assert zhilian_engine._classify_main_buttons([""]) == "unknown"
    assert zhilian_engine._classify_main_buttons(None) == "unknown"


@pytest.mark.skipif(not HAS_ENGINE, reason="DrissionPage 不可用")
def test_positive_assertion_rejects_empty_button_state():
    """Bug 2 回归防护：投递后按钮定位不到（空列表）必须判失败，不得假报已投递。"""
    assert not zhilian_engine._is_delivered_button_state([])
    assert not zhilian_engine._is_delivered_button_state(None)
    assert not zhilian_engine._is_delivered_button_state(["立即投递"])
    assert zhilian_engine._is_delivered_button_state(["已投递"])
    assert zhilian_engine._is_delivered_button_state(["继续沟通"])


# ---------------- 3. 打招呼语合法性校验（Bug 7） ----------------

def test_is_valid_greeting_rejects_error_text():
    assert not is_valid_greeting("")
    assert not is_valid_greeting(None)
    assert not is_valid_greeting("   ")
    assert not is_valid_greeting("❌ AI 服务未配置 (api_key)")
    assert not is_valid_greeting("❌ 找不到打招呼语重构策略文件: /x.md")
    assert not is_valid_greeting("生成失败：模型超时")


def test_is_valid_greeting_accepts_normal_text():
    assert is_valid_greeting("您好，关注到贵司正在招聘该职位，期待与您沟通！")
    assert is_valid_greeting("HR您好，我有3年相关经验，诚意向您推荐自己")


@pytest.mark.asyncio
async def test_delivery_node_blocks_illegal_greeting():
    """delivery_node 终检：非法打招呼语（含历史脏数据）在投递前被拦截。"""
    state = {
        "record_id": "recG",
        "job_id": "recG",
        "platform": "zhilian",
        "company_name": "测试公司",
        "job_name": "测试岗",
        "grade": "A",
        "greeting": "❌ AI 服务未配置 (api_key)",
        "feishu_fields": {},
    }
    res = await wf.delivery_node(state)
    assert "error" in res and "打招呼语" in res["error"]


# ---------------- 4. quick_greeting_node 禁止 LLM 现场生成（Bug 7） ----------------

class _FakeFeishuTool:
    def __init__(self, captured: dict):
        self._captured = captured

    async def ainvoke(self, inp: dict):
        self._captured.update(inp["updates"])


async def _boom_generate(*a, **k):  # pragma: no cover
    raise AssertionError("禁止现场 LLM 生成海投打招呼语！")


@pytest.mark.asyncio
async def test_quick_greeting_no_llm_when_config_empty(monkeypatch):
    monkeypatch.setattr(wf, "get_autopilot_config", lambda: {"mass_apply_greeting": ""})
    monkeypatch.setattr(wf, "process_greeting_generation", _boom_generate)
    monkeypatch.setattr(wf, "_emit_node_running", _noop_emit)
    captured: dict = {}
    monkeypatch.setattr(wf, "update_feishu_status", _FakeFeishuTool(captured))

    state = {"record_id": "rec1", "job_name": "岗", "grade": "C", "platform": "boss",
             "feishu_fields": {"PDF备份": [{"file_token": "x"}]}}
    res = await wf.quick_greeting_node(state)
    assert res["status"] == "海投人工复核"
    assert captured["跟进状态"] == "海投人工复核"


@pytest.mark.asyncio
async def test_quick_greeting_rejects_error_text_config(monkeypatch):
    """配置里存了错误文本（历史脏数据）同样按未配置处理，挂回人工复核。"""
    monkeypatch.setattr(wf, "get_autopilot_config", lambda: {"mass_apply_greeting": "❌ AI 服务未配置"})
    monkeypatch.setattr(wf, "process_greeting_generation", _boom_generate)
    monkeypatch.setattr(wf, "_emit_node_running", _noop_emit)
    captured: dict = {}
    monkeypatch.setattr(wf, "update_feishu_status", _FakeFeishuTool(captured))

    state = {"record_id": "rec2", "job_name": "岗", "grade": "C", "platform": "boss",
             "feishu_fields": {"PDF备份": [{"file_token": "x"}]}}
    res = await wf.quick_greeting_node(state)
    assert res["status"] == "海投人工复核"


async def _noop_emit(state, node_name, sub_status):
    return None


# ---------------- 5. 统一精投判定口径（Bug 8） ----------------

def test_is_custom_record_ai_rewrite_json():
    """只有 AI改写JSON（评级 C）也判精投 —— 与 delivery_node 口径对齐。"""
    assert is_custom_record({"AI改写JSON": '{"v":2}', "综合评级 (A-F)": "C"}) is True


def test_is_custom_record_grade_ab():
    assert is_custom_record({"综合评级 (A-F)": "B"}) is True
    assert is_custom_record({"综合评级 (A-F)": "a"}) is True


def test_is_custom_record_mass_by_default():
    assert is_custom_record({}) is False
    assert is_custom_record({"综合评级 (A-F)": "C"}) is False
    assert is_custom_record({"综合评级 (A-F)": "D"}) is False


# ---------------- 6. deliver_approved 防抖锁（Bug 9） ----------------

@pytest.mark.asyncio
async def test_deliver_approved_busy_guard():
    """上一轮批量投递未结束时再次触发必须返回 busy，不得并发第二轮。"""
    from app.automation.routes.delivery_router import DeliverApprovedRequest

    await delivery_router._deliver_worker_lock.acquire()
    try:
        res = await delivery_router.deliver_approved_jobs(
            DeliverApprovedRequest(thread_ids=["recX"])
        )
        assert res["status"] == "busy"
        assert res["data"]["count"] == 0
    finally:
        delivery_router._deliver_worker_lock.release()


# ---------------- 7. 批量编排预扫描：跳过已投递 + 平台白名单（Bug 10） ----------------

@pytest.mark.asyncio
async def test_worker_prescan_skips_delivered_and_offlist_platforms(monkeypatch):
    monkeypatch.setattr(
        delivery_router, "_get_autopilot_config",
        lambda: {"auto_deliver_platforms": ["boss", "liepin", "51job", "zhilian"]},
    )

    records = {
        "recA": {"fields": {"招聘平台": "智联招聘", "跟进状态": "已投递", "岗位链接": {"link": "https://a"}}},
        "recB": {"fields": {"招聘平台": "智联招聘", "跟进状态": "待投递", "岗位链接": {"link": "https://b"}}},
        "recC": {"fields": {"招聘平台": "小红书", "跟进状态": "待投递"}},
    }

    def fake_get_record(rid, table):
        return records[rid]

    monkeypatch.setattr(feishu_service, "get_job_record_from_feishu", fake_get_record)
    monkeypatch.setattr(sched, "pipeline_app", None, raising=False)

    calls: list[str] = []

    async def fake_delivery_node(state):
        calls.append(state["record_id"])
        return {"status": "已投递"}

    monkeypatch.setattr(wf, "delivery_node", fake_delivery_node)

    await delivery_router._deliver_approved_worker_inner(["recA", "recB", "recC"])
    # recA：已投递跳过；recC：平台不在白名单跳过；仅 recB 实际执行
    assert calls == ["recB"]


# ---------------- 8. 失败分诊结构化标签（Bug 15） ----------------

def test_triage_structured_persistent_tags():
    for tag in ("[简历]", "[物料]", "[下架]", "[风控]", "[状态]"):
        assert failure_triage.classify_delivery_failure(f"{tag} xxx") == "persistent"


def test_triage_structured_transient_tags():
    for tag in ("[登录]", "[环境]"):
        assert failure_triage.classify_delivery_failure(f"{tag} xxx") == "transient"


def test_triage_engine_error_messages():
    """引擎实际会产出的错误文本必须落到正确的分诊桶。"""
    assert failure_triage.classify_delivery_failure(
        "[简历] 简历选择弹窗中未找到目标简历「x」") == "persistent"
    assert failure_triage.classify_delivery_failure(
        "[物料] 缺少打招呼语：智联投递需随微聊发送打招呼语") == "persistent"
    assert failure_triage.classify_delivery_failure(
        "[登录] 智联登录态失效，请先在 9250 端口浏览器登录后重试") == "transient"
    # 无法确认投递状态的歧义按钮：持久性故障，波次不得盲目重试
    assert failure_triage.classify_delivery_failure(
        "[状态] 主操作区仅有沟通类按钮 ['继续沟通']") == "persistent"


# ---------------- 9. 引擎上传元组协议（Bug 3/16 配套） ----------------

@pytest.mark.skipif(not HAS_ENGINE, reason="DrissionPage 不可用")
def test_upload_resume_returns_3_tuple_signature():
    """_upload_resume 协议回归：必须返回 (ok, batch_flag, backend_resume_count) 三元组。"""
    import inspect
    src = inspect.getsource(zhilian_engine._upload_resume)
    assert "return False, batch_mass_uploaded, 0" in src
    src_once = inspect.getsource(zhilian_engine._upload_resume_once)
    assert "return True, (True if is_mass else batch_mass_uploaded), slot_count" in src_once
    # 精投必须删旧传新，不允许同名直接复用旧附件
    assert "直接复用无需重复上传" not in src_once


@pytest.mark.skipif(not HAS_ENGINE, reason="DrissionPage 不可用")
def test_deliver_to_job_accepts_retry_greeting_only_param():
    """验证 _deliver_to_job 函数签名支持 retry_greeting_only 参数，且默认值为 False。"""
    import inspect
    sig = inspect.signature(zhilian_engine._deliver_to_job)
    assert "retry_greeting_only" in sig.parameters
    assert sig.parameters["retry_greeting_only"].default is False


# ---------------- 10. 质检问题复核与回归测试 ----------------

def test_suzhou_city_code_accuracy():
    """验证苏州城市代码为 639（719 为郑州），防止智联采集跑偏。"""
    import importlib.util
    crawler_path = Path(__file__).resolve().parent.parent / "zhilian_scraper" / "zhilian_collector.py"
    spec = importlib.util.spec_from_file_location("zhilian_collector_scraper_check", crawler_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.CITY_MAP.get("苏州") == "639"
    assert mod.CITY_MAP.get("郑州") == "719"


def test_retry_greeting_only_exact_matching_contract():
    """验证 retry_greeting_only 严格限定于微聊受阻，防止其他投递失败被误认为成功。"""
    def check_is_greeting_only(fail_log: str) -> bool:
        return "[微聊受阻]" in fail_log or "微聊受阻" in fail_log

    # 包含微聊受阻的才应触发补发
    assert check_is_greeting_only("智联投递阶段失败: [微聊受阻] 无法输入打招呼语")
    assert check_is_greeting_only("微聊受阻：无法发送消息")

    # 其他失败绝对不能触发 retry_greeting_only
    assert not check_is_greeting_only("智联投递阶段失败: [简历] 简历选择弹窗中未找到目标简历")
    assert not check_is_greeting_only("智联投递阶段失败: [风控] 检测到风控提示")
    assert not check_is_greeting_only("智联投递阶段失败: [状态] 无法确认投递状态")
    assert not check_is_greeting_only("网络连接超时")


def test_executor_routes_delivery_through_delivery_node():
    """验证 tasks/executor 投递任务已收口至 workflow.delivery_node，受全局串行锁与在途锁保护。"""
    import inspect
    from app.tasks.executor import _dispatch_to_platform
    src = inspect.getsource(_dispatch_to_platform)
    assert "delivery_node" in src
    # 不允许直接调用底层的 zhilian_auto_delivery.deliver_job 绕过锁
    assert "zhilian_auto_delivery.deliver_job(" not in src


@pytest.mark.asyncio
async def test_executor_dispatch_runtime_contract_smoke(monkeypatch):
    """验证 _dispatch_to_platform -> delivery_node 运行时契约健全：
    1. 绝不抛出 KeyError('feishu_fields')
    2. delivery_node 完整接收 material、company_name、job_name 与 feishu_fields
    3. 底层 tool 收到解析后完整的物料入参
    """
    import asyncio
    from unittest.mock import AsyncMock
    from app.tasks.executor import _dispatch_to_platform
    import app.automation.workflow as workflow

    mock_deliver = AsyncMock()
    mock_deliver.ainvoke = AsyncMock(return_value="✅ 智联投递引擎执行成功")
    mock_status = AsyncMock()
    mock_status.ainvoke = AsyncMock(return_value=True)
    monkeypatch.setattr(workflow, "deliver_zhilian_job", mock_deliver)
    monkeypatch.setattr(workflow, "update_feishu_status", mock_status)
    monkeypatch.setattr(workflow, "_emit_node_running", AsyncMock())

    queue = asyncio.Queue()
    job_data = {
        "record_id": "recTest123",
        "job_url": "https://www.zhaopin.com/job/123.htm",
        "file_token": "token_pdf_123",
        "pdf_name": "测试公司_测试岗位.pdf",
        "greeting": "您好，我关注到贵司正在招聘该职位！",
        "image_items": [],
        "feishu_fields": {"岗位名称": "测试岗位", "公司名称": "测试公司"},
        "company_name": "测试公司",
        "job_name": "测试岗位",
    }

    res = await _dispatch_to_platform(queue, "zhilian", job_data)
    assert res == {"followStatus": "已投递"}
    assert mock_deliver.ainvoke.called
    call_args = mock_deliver.ainvoke.call_args[0][0]["job_data"]
    assert call_args["record_id"] == "recTest123"
    assert call_args["company"] == "测试公司"
    assert call_args["job_title"] == "测试岗位"
    assert call_args["file_token"] == "token_pdf_123"
    assert call_args["greeting"] == "您好，我关注到贵司正在招聘该职位！"


@pytest.mark.asyncio
async def test_delivery_node_inner_resilient_without_feishu_fields(monkeypatch):
    """验证 delivery_node 在 feishu_fields 缺失或为空时，依靠 state 字段健壮运行而不发生 KeyError。"""
    from unittest.mock import AsyncMock
    import app.automation.workflow as workflow

    mock_deliver = AsyncMock()
    mock_deliver.ainvoke = AsyncMock(return_value="✅ 智联投递引擎执行成功")
    mock_status = AsyncMock()
    mock_status.ainvoke = AsyncMock(return_value=True)
    monkeypatch.setattr(workflow, "deliver_zhilian_job", mock_deliver)
    monkeypatch.setattr(workflow, "update_feishu_status", mock_status)
    monkeypatch.setattr(workflow, "_emit_node_running", AsyncMock())

    # state 中完全不提供 feishu_fields
    sparse_state = {
        "job_id": "recSparse",
        "record_id": "recSparse",
        "platform": "zhilian",
        "job_url": "https://www.zhaopin.com/job/sparse.htm",
        "file_token": "sparse_token",
        "greeting": "您好，投递简历",
        "company_name": "兜底公司",
        "job_name": "兜底岗位",
        "grade": "C",
        "is_custom": True,
    }

    res = await workflow.delivery_node(sparse_state)
    assert res.get("status") == "已投递"
    assert mock_deliver.ainvoke.called
    call_args = mock_deliver.ainvoke.call_args[0][0]["job_data"]
    assert call_args["record_id"] == "recSparse"
    assert call_args["company"] == "兜底公司"
    assert call_args["job_title"] == "兜底岗位"
    assert call_args["file_token"] == "sparse_token"
    assert call_args["job_url"] == "https://www.zhaopin.com/job/sparse.htm"


@pytest.mark.skipif(not HAS_ENGINE, reason="DrissionPage 不可用")
def test_deliver_to_job_mode_correction_scope_and_loud_failure(monkeypatch, tmp_path):
    """验证 _deliver_to_job 模式校正分支符号作用域健全，绝不抛出 NameError：
    1. 当外部指定 retry_greeting_only=True，但页面呈现【立即投递】（btn_state == 'deliverable'）时触发校正；
    2. 若本地无 PDF 且缺少 file_token，必须响亮报错返回缺少 token，而非抛出 NameError；
    3. 若本地无 PDF 且 download_feishu_file 失败，必须响亮报错返回补下载失败；
    """
    from unittest.mock import MagicMock
    import zhilian_auto_delivery as zd

    mock_btn = MagicMock()
    mock_btn.text = "立即投递"
    mock_btn.states.is_displayed = True

    mock_tab = MagicMock()
    mock_tab.ele.return_value = None

    def mock_eles(selector, **kwargs):
        if "summary-planes__action button" in selector:
            return [mock_btn]
        return []

    mock_tab.eles.side_effect = mock_eles

    mock_page = MagicMock()
    mock_page.new_tab.return_value = mock_tab

    monkeypatch.setattr(zd, "time", MagicMock())

    non_existent_pdf = str(tmp_path / "not_exist_resume.pdf")

    # Case 1: 无 file_token 时响亮报错缺少 file_token，断言无 NameError 且 tab 安全关闭
    deliver_ok, greeting_sent, err = zd._deliver_to_job(
        page=mock_page,
        job_url="https://www.zhaopin.com/job/test1234.htm",
        pdf_name="测试简历",
        retry_greeting_only=True,
        file_token="",
        local_pdf_path=non_existent_pdf,
    )
    assert not deliver_ok
    assert "[物料] 模式校正需重新投递附件，但缺少 PDF file_token 物料" in err
    assert mock_tab.close.called

    # Case 2: 有 file_token 但 download_feishu_file 返回 False 时响亮报错补下载失败
    monkeypatch.setattr(zd, "download_feishu_file", lambda token, path: False)
    mock_tab.close.reset_mock()
    deliver_ok, greeting_sent, err = zd._deliver_to_job(
        page=mock_page,
        job_url="https://www.zhaopin.com/job/test1234.htm",
        pdf_name="测试简历",
        retry_greeting_only=True,
        file_token="valid_token_xyz",
        local_pdf_path=non_existent_pdf,
    )
    assert not deliver_ok
    assert "[物料] 模式校正后补下载简历附件失败，无法执行投递" in err
    assert mock_tab.close.called



