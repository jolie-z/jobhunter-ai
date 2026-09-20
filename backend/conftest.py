import os
os.environ["JOBHUNTER_TESTING"] = "1"

"""backend 根级测试配置：对 resume_editor/data/ 平台数据文件做会话级备份/还原。

事故背景（2026-08-31 / 2026-09-02）：多个目录下的测试（tests/、resume_editor/、
tests_pipeline/）会经由真实 API 或 healer 直写 boss_fields.json 等生产数据文件，
曾把完整采集数据覆盖成一行测试残留文字。本守卫在会话开始前备份、结束后原样还原；
测试期间的读写行为不受影响，所有子目录的测试统一被覆盖。
"""
import os
import shutil
import threading
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parent


@pytest.fixture(scope="session", autouse=True)
def _protect_real_resume_data(tmp_path_factory):
    data_dir = _BACKEND_ROOT / "resume_editor" / "data"
    if not data_dir.exists():
        yield
        return
    patterns = ("*_fields.json", "*_writeback.json", "unified_resume.json", "total_fields.json")
    protected = [p for pat in patterns for p in data_dir.glob(pat)]
    backup_dir = tmp_path_factory.mktemp("real_data_backup")
    for f in protected:
        shutil.copy2(f, backup_dir / f.name)
    yield
    for f in protected:
        bak = backup_dir / f.name
        if bak.exists():
            shutil.copy2(bak, f)


_EXIT_STATUS = {"code": 0}


def pytest_sessionfinish(session, exitstatus):
    _EXIT_STATUS["code"] = int(exitstatus)


def pytest_unconfigure(config):
    if os.environ.get("RUN_LIVE_E2E"):
        return  # 真机调试场景保持正常退出语义，便于交互式排查

    lingering = [
        t
        for t in threading.enumerate()
        if t is not threading.main_thread() and not t.daemon and t.is_alive()
    ]
    if not lingering:
        return
    names = ", ".join(f"{t.name}(ident={t.ident})" for t in lingering)
    print(
        f"\n⚠️ [root conftest] 检测到 {len(lingering)} 个残留非 daemon 线程会阻塞解释器退出: {names}\n"
        f"⚠️ [root conftest] 携带真实退出码 {_EXIT_STATUS['code']} 强制结束进程，避免全量回归假死（CI 超时）"
    )
    os._exit(_EXIT_STATUS["code"])
