"""51job legacy_cookie_file 走 db_paths 阀门（agy plan-review 2026-10-26 round1 P2）：
打包态落 <DATA_DIR>/51job_cookies.json（与 51job_collector 真实写入位置一致，健康检查/预检才看对地方）；
开发态等于安装目录锚点，行为不变。0.3.6 起 bundled cookie 不再进包，旧锚点在打包态恒为不存在。
"""

import importlib
import os

import app.session.registry as registry


def _reload_with(env: dict):
    saved = os.environ.get("JOBHUNTER_DATA_DIR")
    try:
        os.environ.pop("JOBHUNTER_DATA_DIR", None)
        os.environ.update(env)
        return importlib.reload(registry)
    finally:
        if saved is None:
            os.environ.pop("JOBHUNTER_DATA_DIR", None)
        else:
            os.environ["JOBHUNTER_DATA_DIR"] = saved


def test_51job_legacy_cookie_file_follows_data_dir_valve(tmp_path):
    try:
        m = _reload_with({})
        assert m.PLATFORM_CONFIGS["51job"].legacy_cookie_file == os.path.join(
            m._BACKEND_ROOT, "51job_scraper", "51job_cookies.json"
        )
        data_dir = tmp_path / "ud"
        m = _reload_with({"JOBHUNTER_DATA_DIR": str(data_dir)})
        assert m.PLATFORM_CONFIGS["51job"].legacy_cookie_file == str(data_dir / "51job_cookies.json")
    finally:
        importlib.reload(registry)
