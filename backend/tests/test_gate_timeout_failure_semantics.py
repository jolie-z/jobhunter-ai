"""投递闸门超时错误串的失败分诊语义测试（外审 round1 P1 补证）。

关键承诺：delivery_gate 等待抓取清场超时的错误文本以 [环境] 标记，
failure_triage 必须判 transient——保留飞书「待投递」门牌走自愈重试，
而不是把岗位永久置为投递失败。
"""

import sys
from pathlib import Path
from unittest.mock import patch

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.automation.failure_triage import (
    classify_delivery_failure,
    should_retry_delivery,
)
from app.automation import platform_mutex

# 文案统一由 platform_mutex.delivery_gate_timeout_error 产出（workflow 同源引用，防漂移）
GATE_TIMEOUT_ERROR = platform_mutex.delivery_gate_timeout_error(
    platform_mutex.DELIVERY_WAIT_SCRAPE_TIMEOUT_S
)


def test_gate_timeout_error_text_contract():
    """错误串契约：[环境] 标签在、超时秒数格式正确（防文案漂移破坏失败分诊）"""
    assert GATE_TIMEOUT_ERROR.startswith("❌ [环境] ")
    assert "300" in GATE_TIMEOUT_ERROR
    assert "自愈重试" in GATE_TIMEOUT_ERROR


def test_gate_timeout_error_classifies_transient():
    assert classify_delivery_failure(GATE_TIMEOUT_ERROR) == "transient"


def test_gate_timeout_error_keeps_pending_label_for_selfheal():
    """首败（台账无记录，failure_count 视 0）→ 保留「待投递」自动重试；
    连续失败达 MAX_AUTO_RETRIES 后停手防空转（与 51job 滑块同一暂态通道）"""
    with patch("app.automation.run_snapshot.get_delivery_failures", return_value={}):
        assert should_retry_delivery(GATE_TIMEOUT_ERROR, "rec_gate_test") is True

    with patch("app.automation.run_snapshot.get_delivery_failures", return_value={
        "rec_gate_test": {"error": GATE_TIMEOUT_ERROR, "failure_count": 2},
    }):
        assert should_retry_delivery(GATE_TIMEOUT_ERROR, "rec_gate_test") is False


def test_persistent_labels_not_shadowed_by_gate_error():
    """闸门错误串本身不含持久性标签；确认 [环境] 未被误归 persistent"""
    for persistent_case in ("❌ [简历] 简历选择弹窗中未找到目标简历", "❌ 缺少 PDF 简历附件"):
        assert classify_delivery_failure(persistent_case) == "persistent"
