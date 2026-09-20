import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.automation import abort as abort_mod
from app.automation import delivery_interrupter
from app.automation import run_snapshot as rs
from app.automation.workflow import delivery_node, _delivery_serial_lock, _DELIVERY_INFLIGHT_RECORD_IDS


client = TestClient(app)


@pytest.fixture(autouse=True)
def cleanup_state():
    """每次测试前后清理单岗取消与在途状态"""
    abort_mod._cancelled_job_deliveries.clear()
    delivery_interrupter._active_targets.clear()
    _DELIVERY_INFLIGHT_RECORD_IDS.clear()
    with rs._lock:
        rs._delivering_jobs.clear()
        rs._retrying_jobs.clear()
    yield
    abort_mod._cancelled_job_deliveries.clear()
    delivery_interrupter._active_targets.clear()
    _DELIVERY_INFLIGHT_RECORD_IDS.clear()
    with rs._lock:
        rs._delivering_jobs.clear()
        rs._retrying_jobs.clear()


def test_cancel_job_delivery_guard_rejects_idle_job():
    """测试状态守卫：对不在投递中的闲置岗位调用取消，必须被严格拦截并返回 400"""
    res = client.post("/api/automation/cancel-job-delivery", json={"record_id": "rec_idle_123"})
    assert res.status_code == 400
    data = res.json()
    assert "未处于自动投递进行状态" in data["detail"]


def test_cancel_job_delivery_guard_accepts_inflight_and_idempotent():
    """测试在途岗位取消成功，且重复调用具备幂等性"""
    record_id = "rec_delivering_456"
    # 模拟该岗位处于在途投递中
    rs.mark_job_delivering(record_id)

    # 首次调用
    res1 = client.post("/api/automation/cancel-job-delivery", json={"record_id": record_id})
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "success"
    assert abort_mod.is_job_delivery_cancelled(record_id) is True

    # 再次重复调用：必须幂等返回成功
    res2 = client.post("/api/automation/cancel-job-delivery", json={"record_id": record_id})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["already_cancelled"] is True


def test_cancel_job_delivery_triggers_interrupter():
    """测试取消接口会联动调用 delivery_interrupter 注册的活跃打断钩子"""
    record_id = "rec_active_browser_789"
    rs.mark_job_delivering(record_id)

    mock_interrupt_fn = MagicMock()
    delivery_interrupter.register_delivery_target(record_id, mock_interrupt_fn)

    res = client.post("/api/automation/cancel-job-delivery", json={"record_id": record_id})
    assert res.status_code == 200
    data = res.json()
    assert data["interrupted"] is True
    mock_interrupt_fn.assert_called_once()


@pytest.mark.asyncio
async def test_workflow_delivery_node_pre_check_cancellation():
    """测试 workflow.py 的 delivery_node 在获取锁前检测到取消标记，直接熔断且不调用平台 Tool"""
    record_id = "rec_cancelled_before_lock"
    # 预先标记取消
    abort_mod.cancel_job_delivery(record_id)

    state = {
        "record_id": record_id,
        "job_url": "https://www.zhipin.com/job_detail/test.html",
        "greeting": "您好，我对该岗位很感兴趣",
        "platform": "boss",
        "job_name": "测试岗位",
        "company_name": "测试公司",
        "feishu_fields": {},
    }


    mock_tool = MagicMock()
    mock_tool.ainvoke = MagicMock()

    with patch("app.automation.workflow.deliver_boss_job", mock_tool):
        result = await delivery_node(state)
        # 验证工具绝未被调用
        mock_tool.ainvoke.assert_not_called()
        assert "error" in result
        assert "[用户主动终止]" in result["error"]
        # 验证标记已在收尾时清理
        assert abort_mod.is_job_delivery_cancelled(record_id) is False
        # 验证串行锁是未被占用的
        assert not _delivery_serial_lock.locked()


@pytest.mark.asyncio
async def test_workflow_delivery_node_cancelling_during_execution():
    """测试在进入投递执行期间下达取消，即使执行器返回普通报错，也能被准确归因为 [用户主动终止]"""
    record_id = "rec_cancel_mid_execution"

    state = {
        "record_id": record_id,
        "job_url": "https://www.zhipin.com/job_detail/test2.html",
        "greeting": "您好，沟通一下",
        "platform": "boss",
        "job_name": "高级研发工程师",
        "company_name": "创新科技",
        "feishu_fields": {},
        # 物料显式随 state 传入：本用例验证的是取消归因，不依赖飞书自愈补料（密闭化）
        "image_items": [{"token": "tok_cancel_mid", "name": "创新科技_高级研发工程师-长图.jpg"}],
    }

    mock_tool = MagicMock()
    async def _mock_tool_run(*args, **kwargs):
        # 模拟在执行器内部运行中，用户点击了取消
        abort_mod.cancel_job_delivery(record_id)
        return "❌ BOSS 投递受阻，请检查相关日志"

    mock_tool.ainvoke = _mock_tool_run

    with patch("app.automation.workflow.deliver_boss_job", mock_tool), \
         patch("app.automation.workflow._emit_node_running") as mock_emit:
        result = await delivery_node(state)
        # 验证 _emit_node_running 确实被正常触发（防止状态丢失回归）
        mock_emit.assert_called_once()
        assert "error" in result
        # 验证成功覆写归因为用户主动终止
        assert "[用户主动终止]" in result["error"]
        assert not _delivery_serial_lock.locked()


@pytest.mark.asyncio
async def test_workflow_delivery_node_cancelling_late_retains_success():
    """测试边界修复：若 Tool 执行已成功送达（返回 ✅），即便命中了取消标记，也必须保留真实成功状态，严禁篡改为失败"""
    record_id = "rec_cancel_late_success"

    state = {
        "record_id": record_id,
        "job_url": "https://www.zhipin.com/job_detail/test3.html",
        "greeting": "您好，沟通一下",
        "platform": "boss",
        "job_name": "高级研发工程师",
        "company_name": "创新科技",
        "feishu_fields": {},
        # 物料显式随 state 传入：本用例验证的是"成功不被取消篡改"，不依赖飞书自愈补料（密闭化）
        "image_items": [{"token": "tok_cancel_late", "name": "创新科技_高级研发工程师-长图.jpg"}],
    }

    mock_tool = MagicMock()
    async def _mock_tool_run(*args, **kwargs):
        # 模拟在执行即将收尾阶段用户点了取消，但此时投递动作已经圆满完成
        abort_mod.cancel_job_delivery(record_id)
        return "✅ BOSS 沟通已发起，投递成功"

    mock_tool.ainvoke = _mock_tool_run

    mock_feishu = MagicMock()
    mock_feishu.ainvoke = AsyncMock(return_value="ok")

    with patch("app.automation.workflow.deliver_boss_job", mock_tool), \
         patch("app.automation.workflow.update_feishu_status", mock_feishu), \
         patch("app.automation.workflow._emit_node_running"):
        result = await delivery_node(state)
        # 验证保留成功，未被篡改为失败
        assert result.get("status") == "已投递"
        assert "error" not in result
        mock_feishu.ainvoke.assert_called_once()
        assert not _delivery_serial_lock.locked()



def test_boss_deliver_job_early_exit_on_cancelled():
    """测试边界修复：boss_auto_delivery 在物料准备前检测到已取消，提前退出，不调用浏览器"""
    from boss_scraper.boss_auto_delivery import deliver_job
    record_id = "rec_boss_material_cancel"
    abort_mod.cancel_job_delivery(record_id)

    job_data = {
        "record_id": record_id,
        "job_url": "https://www.zhipin.com/job_detail/test4.html",
        "greeting": "您好",
        "image_items": [{"url": "https://example.com/test.png"}],
    }

    with patch("boss_scraper.boss_auto_delivery._ensure_login", return_value=True), \
         patch("boss_scraper.boss_auto_delivery.get_browser_page"), \
         patch("boss_scraper.boss_auto_delivery._download_resume_images") as mock_dl, \
         patch("boss_scraper.boss_auto_delivery._chat_and_send_resume") as mock_chat, \
         patch("boss_scraper.boss_auto_delivery._log_failure"):
        success = deliver_job(job_data)
        assert success is False
        mock_dl.assert_not_called()
        mock_chat.assert_not_called()


def test_liepin_deliver_job_early_exit_on_cancelled():
    """测试边界修复：liepin_auto_delivery 检测到已取消，提前退出，不调用浏览器"""
    from liepin_scraper.liepin_auto_delivery import deliver_job
    record_id = "rec_liepin_cancel"
    abort_mod.cancel_job_delivery(record_id)

    job_data = {
        "record_id": record_id,
        "job_url": "https://www.liepin.com/job/123.shtml",
        "greeting": "您好",
        "file_token": "token123",
    }

    with patch("liepin_scraper.liepin_auto_delivery.ensure_login", return_value=True), \
         patch("liepin_scraper.liepin_auto_delivery.download_feishu_file") as mock_dl, \
         patch("liepin_scraper.liepin_auto_delivery.update_feishu_record"):
        success = deliver_job(job_data)
        assert success is False
        mock_dl.assert_not_called()


def test_51job_deliver_job_early_exit_on_cancelled():
    """测试边界修复：51job_auto_delivery 检测到已取消，提前退出，不调用浏览器"""
    import sys
    from pathlib import Path
    job51_dir = str(Path(__file__).resolve().parents[1] / "51job_scraper")
    if job51_dir not in sys.path:
        sys.path.insert(0, job51_dir)
    import importlib
    mod = importlib.import_module("51job_auto_delivery")
    record_id = "rec_51job_cancel"
    abort_mod.cancel_job_delivery(record_id)


    job_data = {
        "record_id": record_id,
        "job_url": "https://jobs.51job.com/shanghai/123.html",
        "file_token": "token123",
    }

    with patch.object(mod, "_connect_browser") as mock_conn, \
         patch.object(mod, "update_feishu_record"):
        success = mod.deliver_job(job_data)
        assert success is False
        mock_conn.assert_not_called()


