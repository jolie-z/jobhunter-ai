import pytest
from unittest.mock import MagicMock, patch
import sys
import os

from app.core.cache import JobCache


def test_boss_job_closed_auto_archive(monkeypatch, tmp_path):
    """测试当 BOSS 页面显示职位已关闭时，正确抛出 JobClosedError 并自动将飞书与缓存流转为「已下架」"""
    monkeypatch.setattr(JobCache, "_snapshot_path", tmp_path / "test_snapshot.json")
    original_data = JobCache._data
    original_ts = JobCache._timestamp

    try:
        JobCache._data = [
            {"record_id": "rec_closed_1", "job_name": "客服", "follow_status": "待投递"}
        ]
        JobCache._timestamp = 10000.0

        from boss_scraper.boss_auto_delivery import deliver_job, JobClosedError

        mock_page = MagicMock()
        # 页面既没有立即沟通也没有继续沟通
        mock_page.ele.side_effect = lambda selector, timeout=None: (
            MagicMock(text="职位已关闭") if "职位已关闭" in selector else None
        )

        with patch("boss_scraper.boss_auto_delivery.get_browser_page", return_value=mock_page), \
             patch("boss_scraper.boss_auto_delivery._ensure_login", return_value=True), \
             patch("boss_scraper.boss_auto_delivery.update_feishu_record") as mock_update:

            job_data = {
                "record_id": "rec_closed_1",
                "job_url": "https://www.zhipin.com/job_detail/closed.html",
                "greeting": "您好！",
                "image_items": []
            }

            success = deliver_job(job_data)
            assert success is False

            # 验证飞书被更新为「已下架」
            mock_update.assert_called_once()
            call_fields = mock_update.call_args[0][1]
            assert call_fields["跟进状态"] == "已下架"

            # 验证本地 JobCache 也被同步为「已下架」
            cached = JobCache.get_stale()
            assert cached[0]["follow_status"] == "已下架"

    finally:
        JobCache._data = original_data
        JobCache._timestamp = original_ts


def test_boss_enter_chat_room_adaptive_new_tab():
    """测试自适应进入聊天室：点击立即沟通后若直接打开聊天新标签页，平滑接管而不会崩溃"""
    from boss_scraper.boss_auto_delivery import _enter_chat_room

    mock_imm_btn = MagicMock()
    mock_main_page = MagicMock()
    mock_chat_tab = MagicMock()
    mock_chat_tab.url = "https://www.zhipin.com/web/geek/chat?id=123"
    mock_chat_tab.ele.return_value = MagicMock()

    mock_main_page.tab_ids = ["tab1", "tab2"]
    mock_main_page.latest_tab = "tab2"
    mock_main_page.get_tab.return_value = mock_chat_tab

    with patch("boss_scraper.boss_auto_delivery._page", mock_main_page), \
         patch("boss_scraper.boss_auto_delivery.page", mock_main_page), \
         patch("boss_scraper.boss_auto_delivery._handle_security_captcha"):

        _enter_chat_room(mock_imm_btn, None)
        mock_imm_btn.click.assert_called_once_with(by_js=True)
        # 验证新标签页加载
        mock_chat_tab.wait.load_start.assert_called_once()
