import pytest
from unittest.mock import patch, MagicMock
import subprocess
from boss_scraper import boss_nl_controller

def test_boss_fatal_error_propagation():
    """测试当底层引擎 returncode != 0 且入库数为 0 时，正确抛出 RuntimeError，不再假成功"""
    mock_process = MagicMock()
    mock_process.returncode = 1
    mock_process.stdout.readline.side_effect = [""]

    with patch("subprocess.Popen", return_value=mock_process), \
         patch("boss_scraper.boss_nl_controller._process_crawler_output", return_value=(0, 0, False, 0)), \
         patch("app.session.scrape_sessions.report_condition_round"):
        with pytest.raises(RuntimeError) as exc_info:
            boss_nl_controller.run_task(
                keyword="AI产品",
                city="广州",
                start_page=1,
                target_jobs=10,
                salary="不限"
            )
        assert "底层爬虫遭遇异常拦截中断" in str(exc_info.value)
