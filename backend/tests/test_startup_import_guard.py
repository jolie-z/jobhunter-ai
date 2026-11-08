"""启动 import 链回归：pandas/numpy 不得在模块加载期被拉起。

背景：Windows 冷启动/杀软扫描下 pandas/numpy 是启动链上最重的二进制依赖，曾把
后端 240s 就绪窗口吃满（0.4.0/0.4.1 启动超时排查）。事故链
app.main → app.api.routes.webhook → app.agent_router → app.db_nl_controller
上的任一环都必须在模块加载期保持轻量，pandas 只允许在导出 Excel 的 worker 线程内导入。
"""
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]

_STARTUP_CHAIN_MODULES = [
    "app.db_nl_controller",
    "app.agent_router",
    "app.api.routes.webhook",
]


@pytest.mark.parametrize("module", _STARTUP_CHAIN_MODULES)
def test_startup_chain_does_not_import_pandas_at_module_load(module):
    code = (
        "import sys; "
        f"import {module}; "
        "assert 'pandas' not in sys.modules, 'pandas 在模块加载期被导入'; "
        "assert 'numpy' not in sys.modules, 'numpy 在模块加载期被导入'"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
