"""测试环境飞书外发熔断守卫安全自测套件。

Fail-Safe 设计原则：
1. 挂载深层网络陷阱（httpx.AsyncClient.send / httpx.Client.send / requests.Session.send）；
2. 若守卫失效，底层直接抛出 Fatal AssertionError，绝不向外网发起任何实际请求；
3. 覆盖双收敛网关（feishu_messaging 8 个出口 + feishu_service 4 个出口，共 12 个出口）的返回值契约与零网络外发断言。
"""
import logging
from unittest.mock import MagicMock

import pytest

import app.core.feishu_messaging as fm
import app.services.feishu_service as fs
from app.core.testing_guard import is_testing_env


@pytest.fixture(autouse=True)
def _fail_closed_network_trap(monkeypatch):
    """安全网兜：任何动词的底层 HTTP 发送若被触达，立即阻断抛错，防止测试击穿外网。"""
    trap = MagicMock(side_effect=AssertionError("FATAL: Feishu testing guard failed, request reached network client!"))
    monkeypatch.setattr("httpx.AsyncClient.send", trap)
    monkeypatch.setattr("httpx.Client.send", trap)
    monkeypatch.setattr("requests.Session.send", trap)
    return trap


def test_is_testing_env_semantics(monkeypatch):
    """测试环境判定与 RUN_LIVE_E2E 逃生门的严格判定（防语义反转）。"""
    # 正常测试上下文
    monkeypatch.delenv("RUN_LIVE_E2E", raising=False)
    monkeypatch.setenv("JOBHUNTER_TESTING", "1")
    assert is_testing_env() is True

    # 任何非 "1" 字符串（包括 "0", "false", "no"）绝对不能解除熔断
    monkeypatch.setenv("RUN_LIVE_E2E", "0")
    assert is_testing_env() is True
    monkeypatch.setenv("RUN_LIVE_E2E", "false")
    assert is_testing_env() is True

    # 唯有显式设定 RUN_LIVE_E2E="1" 时才放行真机
    monkeypatch.setenv("RUN_LIVE_E2E", "1")
    assert is_testing_env() is False


@pytest.mark.asyncio
async def test_feishu_messaging_all_8_outlets_intercepted(_fail_closed_network_trap, caplog):
    """验证 feishu_messaging 异步网关 8 个出口全量熔断，返回安全 mock 数据且底层网络 0 调用。"""
    with caplog.at_level(logging.WARNING):
        # 1. 文本消息
        msg_ok = await fm.send_feishu_message("oc_test_1", "你好测试")
        assert msg_ok is True

        # 2. 卡片消息
        card_id = await fm.send_feishu_card("oc_test_1", {"header": {}})
        assert card_id == "om_mock_test_card_id"

        # 3. 发送图片
        img_ok = await fm.send_feishu_image("oc_test_1", "img_key_123")
        assert img_ok is True

        # 4. 发送文件
        file_ok = await fm.send_feishu_file("oc_test_1", "file_key_123")
        assert file_ok is True

        # 5. 上传图片
        upload_img_key = await fm.upload_image_to_feishu(b"fake_image_bytes")
        assert upload_img_key == "img_mock_test_key"

        # 6. 下载消息图片
        img_bytes = await fm.download_message_image("om_msg_1", "img_key_123")
        assert img_bytes == b""

        # 7. 上传文件
        upload_file_key = await fm.upload_file_to_feishu(b"fake_file_bytes", "test.pdf")
        assert upload_file_key == "file_mock_test_key"

        # 8. 原地更新卡片
        update_ok = await fm.update_feishu_card("om_msg_1", {"header": {}})
        assert update_ok is True

    # 核心安全断言：底层网络客户端调用次数严格为 0
    assert _fail_closed_network_trap.call_count == 0

    # 核心可观测性断言：caplog 中记录了标准化 [FeishuMock] 拦截日志
    feishu_mock_logs = [rec.message for rec in caplog.records if "[FeishuMock]" in rec.message]
    assert len(feishu_mock_logs) >= 8


def test_feishu_service_all_4_outlets_intercepted(_fail_closed_network_trap, caplog):
    """验证 feishu_service 历史同步网关 4 个出口全量熔断，返回安全契约数据且底层网络 0 调用。"""
    with caplog.at_level(logging.WARNING):
        # 9. 同步发送文本消息
        msg_res = fs.send_feishu_message("oc_test_2", "同步消息测试")
        assert msg_res is None

        # 10. 同步发送卡片消息
        card_res = fs.send_feishu_card("oc_test_2", {"header": {}})
        assert card_res is None

        # 11. 同步上传文件
        upload_res = fs.upload_file_to_feishu(b"fake_sync_bytes", "sync_test.xlsx")
        assert upload_res == ""

        # 12. 同步发送文件
        file_res = fs.send_feishu_file("oc_test_2", "file_key_sync_123")
        assert file_res is None

    # 核心安全断言：底层网络客户端调用次数严格为 0
    assert _fail_closed_network_trap.call_count == 0

    # 核心可观测性断言：caplog 中记录了标准化 [FeishuMock] 拦截日志
    feishu_mock_logs = [rec.message for rec in caplog.records if "[FeishuMock]" in rec.message]
    assert len(feishu_mock_logs) >= 4
