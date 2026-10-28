"""skill_runs 产物目录 db_paths 阀门回归（2026-10-26，0.3.5 更新清空产物事故）。

事故：SKILLS_RUNS_DIR 曾硬编码 __file__ 相对的 backend/ai_agents/data/skill_runs，
打包形态落在安装目录 resources 内，自动更新整体替换 resources 即清空用户产物
（历史改写产物两次被清，无法恢复）。

回归口径（M2 db_paths 收口先例）：
  1. 开发态（无 env）→ 逐字保持历史锚点 backend/ai_agents/data/skill_runs，业务零改动；
  2. 打包态（壳注入 JOBHUNTER_DATA_DIR）→ <DATA_DIR>/skill_runs，不再落安装目录；
  3. 单文件显式阀门 JOBHUNTER_SKILL_RUNS_DIR 优先（JOBHUNTER_DB_PATH / AUTOPILOT_DB_PATH 同款）。
"""

import importlib
import os
from pathlib import Path

import ai_agents.skills.skill_dirs as sd

_ENV_KEYS = ("JOBHUNTER_DATA_DIR", "JOBHUNTER_SKILL_RUNS_DIR")


def _reload_with(env: dict):
    """在隔离 env 下 reload 模块，返回后恢复原 env（模块常量保持为本次 reload 结果）。"""
    saved = {k: os.environ.get(k) for k in _ENV_KEYS}
    try:
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        os.environ.update(env)
        return importlib.reload(sd)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_skill_runs_dir_follows_db_paths_valve(tmp_path):
    try:
        # ① 开发态：无 env → 历史锚点逐字保持
        mod = _reload_with({})
        assert mod.SKILLS_RUNS_DIR == Path(mod.__file__).parent.parent / "data" / "skill_runs"

        # ② 打包态：DATA_DIR 注入 → 用户数据目录，不再落安装目录
        data_dir = tmp_path / "userData"
        mod = _reload_with({"JOBHUNTER_DATA_DIR": str(data_dir)})
        assert mod.SKILLS_RUNS_DIR == data_dir / "skill_runs"

        # ③ 单文件显式阀门优先于 DATA_DIR
        custom = tmp_path / "custom_runs"
        mod = _reload_with({
            "JOBHUNTER_DATA_DIR": str(data_dir),
            "JOBHUNTER_SKILL_RUNS_DIR": str(custom),
        })
        assert mod.SKILLS_RUNS_DIR == custom

        # ④ 显式阀门下产物读写可用（save → load 闭环）
        result = mod.save_skill_result(
            job_record_id="recVALVE1",
            skill_id="valve_skill",
            files=[{"name": "01_test.md", "content": "# valve test"}],
            token_usage={"total_tokens": 1},
        )
        assert result["success"] is True
        loaded = mod.load_latest_result("recVALVE1", "valve_skill")
        assert loaded is not None
        assert loaded["files"][0]["content"] == "# valve test"
    finally:
        importlib.reload(sd)  # 还原模块常量，避免污染后续用例
