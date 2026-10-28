"""可写路径阀门测试（M1 子项② JOBHUNTER_DB_PATH + M2 JOBHUNTER_DATA_DIR 收口）。

契约（与 AUTOPILOT_DB_PATH 先例同款）：
- 未设 env：各模块保持历史锚点原样（业务逻辑零改动）；
- 设单文件 env：全模块统一指向同一文件，类型与原字段一致（str→str / Path→Path）；
- M2 DATA_DIR：JOBHUNTER_DATA_DIR 注入时全部可写路径落用户数据目录；
  优先级 = 单文件 env > JOBHUNTER_DATA_DIR > 历史锚点。
"""
import importlib
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("JOBHUNTER_DB_PATH", raising=False)
    monkeypatch.delenv("ANALYTICS_DB_PATH", raising=False)
    monkeypatch.delenv("MAIN_PROJECT_DB", raising=False)
    monkeypatch.delenv("JOBHUNTER_DATA_DIR", raising=False)
    monkeypatch.delenv("AUTOPILOT_DB_PATH", raising=False)
    yield


def test_helper_default_preserves_str_and_path():
    from app.core.db_paths import job_hunter_db_path

    assert job_hunter_db_path("/tmp/default_str.db") == "/tmp/default_str.db"
    assert job_hunter_db_path(Path("/tmp/default_path.db")) == Path("/tmp/default_path.db")


def test_helper_override_unifies_type(monkeypatch):
    from app.core.db_paths import job_hunter_db_path

    monkeypatch.setenv("JOBHUNTER_DB_PATH", "/tmp/isolated.db")
    assert job_hunter_db_path("/tmp/default_str.db") == "/tmp/isolated.db"
    assert job_hunter_db_path(Path("/tmp/default_path.db")) == Path("/tmp/isolated.db")


def test_resolve_main_db_path_priority(monkeypatch):
    from app.core.db_bootstrap import resolve_main_db_path

    # JOBHUNTER_DB_PATH 优先于 ANALYTICS_DB_PATH
    monkeypatch.setenv("JOBHUNTER_DB_PATH", "/tmp/first.db")
    monkeypatch.setenv("ANALYTICS_DB_PATH", "/tmp/second.db")
    assert resolve_main_db_path() == "/tmp/first.db"

    # 仅 ANALYTICS_DB_PATH 时行为不变
    monkeypatch.delenv("JOBHUNTER_DB_PATH", raising=False)
    assert resolve_main_db_path() == "/tmp/second.db"


def test_wired_module_constant_follows_env(monkeypatch):
    """以 model_pricing（零导入副作用模块）为样本：env 设置后模块常量指向覆盖路径。"""
    import app.core.model_pricing as mp

    monkeypatch.setenv("JOBHUNTER_DB_PATH", "/tmp/isolated_sample.db")
    reloaded = importlib.reload(mp)
    assert reloaded.DB_PATH == "/tmp/isolated_sample.db"

    # 还原：清 env 后 reload，默认锚点必须回到 backend/data/job_hunter.db
    monkeypatch.delenv("JOBHUNTER_DB_PATH", raising=False)
    restored = importlib.reload(mp)
    assert restored.DB_PATH == get_expected_default_db_path()
    importlib.reload(mp)


def get_expected_default_db_path() -> str:
    """model_pricing 的历史默认锚点：backend/data/job_hunter.db（逐字一致）。"""
    import os

    import app.core.model_pricing as mp

    # backend/app/core/model_pricing.py → parents[2] = backend/
    backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(mp.__file__))))
    return os.path.join(backend_root, "data", "job_hunter.db")


# ============ M2：JOBHUNTER_DATA_DIR 收口 ============

def test_data_dir_routes_writable_paths(tmp_path, monkeypatch):
    """DATA_DIR 注入后：默认文件全部路由到用户数据目录，类型同型保持。"""
    from app.core.db_paths import job_hunter_db_path, writable_path

    dd = tmp_path / "userdata"
    monkeypatch.setenv("JOBHUNTER_DATA_DIR", str(dd))

    assert job_hunter_db_path("/tmp/default_str.db") == str(dd / "job_hunter.db")
    assert job_hunter_db_path(Path("/tmp/default_path.db")) == dd / "job_hunter.db"
    assert writable_path("/tmp/settings.json", "settings.json") == str(dd / "settings.json")
    assert writable_path(Path("/tmp/logs"), "logs") == dd / "logs"


def test_data_dir_priority_per_file_env_wins(tmp_path, monkeypatch):
    """单文件 env 优先于 DATA_DIR（侧车/双实例铁律不被收口覆盖）。"""
    from app.core.db_paths import writable_path

    monkeypatch.setenv("JOBHUNTER_DATA_DIR", str(tmp_path / "userdata"))
    monkeypatch.setenv("AUTOPILOT_DB_PATH", "/tmp/explicit_autopilot.db")
    result = writable_path(Path("/tmp/default_autopilot.db"), "autopilot.db", env_var="AUTOPILOT_DB_PATH")
    assert result == Path("/tmp/explicit_autopilot.db")


def test_data_dir_creates_parent_dirs(tmp_path, monkeypatch):
    """DATA_DIR 模式下自动建父目录（打包首启目录不存在）。"""
    from app.core.db_paths import writable_path

    dd = tmp_path / "userdata" / "nested"
    monkeypatch.setenv("JOBHUNTER_DATA_DIR", str(dd))
    result = writable_path("/tmp/x.json", "a/b/x.json")
    assert result == str(dd / "a" / "b" / "x.json")
    assert (dd / "a").is_dir()


def test_no_env_historical_anchor_untouched():
    """未设任何 env：历史锚点逐字原样（业务零改动回归）。"""
    from app.core.db_paths import job_hunter_db_path, writable_path

    assert job_hunter_db_path("/tmp/keep.db") == "/tmp/keep.db"
    assert writable_path("/tmp/keep.json", "x.json") == "/tmp/keep.json"


def test_settings_data_path_follows_data_dir(tmp_path, monkeypatch):
    """接线样本：settings.json 经 DATA_DIR 路由。"""
    import app.core.config as cfg

    monkeypatch.setenv("JOBHUNTER_DATA_DIR", str(tmp_path / "userdata"))
    reloaded = importlib.reload(cfg)
    assert reloaded.SETTINGS_DATA_PATH == tmp_path / "userdata" / "settings.json"
    # 主库也路由（config.py 锚点为仓根 data，收口后统一）
    assert reloaded.DB_PATH == tmp_path / "userdata" / "job_hunter.db"
    monkeypatch.delenv("JOBHUNTER_DATA_DIR", raising=False)
    importlib.reload(cfg)
