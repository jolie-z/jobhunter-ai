"""
测试环境守卫模块。
用于检测当前 Python 进程是否运行在自动化测试上下文（pytest、单测、回归测试等）。
为所有外部出站通信（如向飞书 OpenAPI 发送卡片/消息）提供统一的熔断判断与日志留痕。
"""
import logging
import os
import sys

logger = logging.getLogger("testing_guard")


def is_testing_env() -> bool:
    """
    检测是否处于测试进程中且未显式开启真机 E2E 模式。
    - 触发标记：JOBHUNTER_TESTING=1（由 root conftest 注入）或 PYTEST_CURRENT_TEST 或 sys.modules 含 pytest
    - 逃生门：严格要求 RUN_LIVE_E2E == "1"，任何 "0"/"false"/空值均无法解除熔断，防语义反转
    """
    is_test = (
        os.environ.get("JOBHUNTER_TESTING") == "1"
        or bool(os.environ.get("PYTEST_CURRENT_TEST"))
        or ("pytest" in sys.modules)
    )
    if not is_test:
        return False
    if os.environ.get("RUN_LIVE_E2E") == "1":
        logger.warning("🚨 [RUN_LIVE_E2E=1] 显式开启真机模式，测试环境飞书外发守卫已解除！")
        return False
    return True


def log_feishu_mock_intercept(func_name: str, return_value: object = None) -> None:
    """输出标准化的测试拦截告警日志，暴露漏桩用例并供测试断言。"""
    logger.warning("[FeishuMock] 测试环境熔断拦截外发: %s() -> 返回安全 mock 数据 %r", func_name, return_value)
