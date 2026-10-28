"""resume_editor 读/写锚点拆分回归（2026-10-26，0.3.2～0.3.5 个人数据随包泄漏 + 更新清空用户数据事故）。

回归口径：
  ① 开发态（无 env）：DATA_DIR 逐字保持 resume_editor/data，DICT_DIR = resume_editor/dicts；
  ② 打包态（JOBHUNTER_DATA_DIR）：DATA_DIR = <DATA_DIR>/resume_editor，DICT_DIR 不随 env 变；
  ③ 路径助手形态；option_source_path 把唯一的用户数据项 *_fields.json 分到 DATA_DIR，其余到 DICT_DIR；
  ④ ensure_data_dir 幂等预建 DATA_DIR 及三个子目录；
  ⑤ 子进程侧：按真实拉起时的 sys.path 布局（仅 platforms/，剔除 cwd）在设 env 的子进程里导入
     4 个采集 + 4 个写回脚本模块（不执行 main），输出路径必须落用户数据目录——覆盖导入顺序铁律；
  ⑥ 32 个运行时必需字典全部位于 dicts/ 且被 git 跟踪（全新 clone 不再静默缺字典）。
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import resume_editor.paths as paths_mod

BACKEND = Path(paths_mod._BACKEND_DIR)
PLATFORMS_DIR = BACKEND / "resume_editor" / "platforms"

RUNTIME_DICTS = [
    "boss_options.json", "boss_industry_options.json", "boss_industry_raw.json", "boss_job_titles.json",
    "boss_fulltime_positions.json", "boss_city_full.json", "boss_country_config.json",
    "boss_overseas_languages.json", "boss_duration_config.json", "boss_parttime_preference.json",
    "boss_parttime_filter.json", "boss_certificates.json", "boss_job_categories_full.json",
    "liepin_job_categories.json", "liepin_industry_categories.json", "liepin_cities.json",
    "liepin_lang_dict.json", "liepin_cert_dict.json", "liepin_options.json", "liepin_salary_k.json",
    "liepin_dropdowns.json", "liepin_certificates.json", "liepin_languages.json",
    "51job_dd_funtype.json", "51job_it_skills.json", "51job_industry.json", "51job_options.json",
    "zhilian_options.json", "zhilian_work_jobtitles.json", "zhilian_work_skills_progress.json",
    "zhilian_industries.json", "zhilian_language_certificates.json",
]


def _reload_with(env: dict):
    saved = os.environ.get("JOBHUNTER_DATA_DIR")
    try:
        os.environ.pop("JOBHUNTER_DATA_DIR", None)
        os.environ.update(env)
        return importlib.reload(paths_mod)
    finally:
        if saved is None:
            os.environ.pop("JOBHUNTER_DATA_DIR", None)
        else:
            os.environ["JOBHUNTER_DATA_DIR"] = saved


def test_dev_and_packaged_anchors(tmp_path):
    try:
        m = _reload_with({})
        re_dir = Path(m.RESUME_EDITOR_DIR)
        assert Path(m.DATA_DIR) == re_dir / "data"
        assert Path(m.DICT_DIR) == re_dir / "dicts"

        data_dir = tmp_path / "userData"
        m = _reload_with({"JOBHUNTER_DATA_DIR": str(data_dir)})
        assert Path(m.DATA_DIR) == data_dir / "resume_editor"
        assert Path(m.DICT_DIR) == re_dir / "dicts"  # 字典随包，不随 env
        assert Path(m.SNAPSHOTS_DIR) == data_dir / "resume_editor" / "snapshots"
        assert Path(m.WRITEBACK_LOGS_DIR) == data_dir / "resume_editor" / "writeback_logs"
        assert Path(m.UNIFIED_PATH) == data_dir / "resume_editor" / "unified_resume.json"
    finally:
        importlib.reload(paths_mod)


def test_path_helpers_and_option_source_split():
    p = paths_mod
    assert p.dict_path("boss_options.json") == os.path.join(p.DICT_DIR, "boss_options.json")
    assert p.fields_path("boss") == os.path.join(p.DATA_DIR, "boss_fields.json")
    assert p.writeback_path("51job") == os.path.join(p.DATA_DIR, "51job_writeback.json")
    # 唯一的用户数据选项源 → DATA_DIR；字典 → DICT_DIR
    assert p.option_source_path("boss_fields.json") == os.path.join(p.DATA_DIR, "boss_fields.json")
    assert p.option_source_path("boss_options.json") == os.path.join(p.DICT_DIR, "boss_options.json")
    # 原始 spec 串带 @提取器 / #键 修饰符也能正确分流（code-review P2 防御）
    assert p.option_source_path("boss_fields.json@genders") == os.path.join(p.DATA_DIR, "boss_fields.json")
    assert p.option_source_path("boss_options.json#salary_ranges") == os.path.join(p.DICT_DIR, "boss_options.json")
    # 调用方可显式传入目录（agent_mapper 传自己的模块属性，测试 patch 仍生效）
    assert p.option_source_path("boss_fields.json", "/d", "/k") == "/d/boss_fields.json"
    assert p.option_source_path("liepin_cities.json", "/d", "/k") == "/k/liepin_cities.json"


def test_ensure_data_dir_is_idempotent(tmp_path):
    try:
        m = _reload_with({"JOBHUNTER_DATA_DIR": str(tmp_path / "ud")})
        assert m.ensure_data_dir() == m.DATA_DIR
        assert m.ensure_data_dir() == m.DATA_DIR
        for d in (m.DATA_DIR, m.SNAPSHOTS_DIR, m.SCHEMA_SNAPSHOTS_DIR, m.WRITEBACK_LOGS_DIR):
            assert Path(d).is_dir()
    finally:
        importlib.reload(paths_mod)


SUBPROCESS_SCRIPTS = {
    "boss_collector": "OUTPUT_PATH", "liepin_collector": "OUTPUT_PATH",
    "job51_collector": "OUTPUT_PATH", "zhilian_collector": "OUTPUT_PATH",
    "boss_write_back": "FIELDS_PATH", "liepin_pusher": "FIELDS_PATH",
    "job51_write_back": "FIELDS_PATH", "zhilian_write_back": "FIELDS_PATH",
}


def test_subprocess_scripts_resolve_user_data_dir_with_real_sys_path(tmp_path):
    """模拟 `python resume_editor/platforms/x.py` 的真实布局：sys.path 只有 platforms/（显式剔除 cwd 与 ''），
    若脚本没有先把 backend 根插入 sys.path，from resume_editor.paths import 会在此处崩掉。"""
    data_dir = tmp_path / "ud"
    env = {**os.environ, "JOBHUNTER_DATA_DIR": str(data_dir)}
    env.pop("PYTHONPATH", None)  # 不借打包态壳注入的 PYTHONPATH，证明脚本自举独立成立
    code_tpl = (
        "import sys, os\n"
        "sys.path.insert(0, {platforms!r})\n"
        "sys.path = [p for p in sys.path if p not in ('', os.getcwd())]\n"
        "import {mod} as m\n"
        "print(getattr(m, {attr!r}))\n"
    )
    for mod, attr in SUBPROCESS_SCRIPTS.items():
        proc = subprocess.run(
            [sys.executable, "-c", code_tpl.format(platforms=str(PLATFORMS_DIR), mod=mod, attr=attr)],
            capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=120,
        )
        assert proc.returncode == 0, f"{mod} 导入失败:\n{proc.stderr[-1500:]}"
        out = proc.stdout.strip().splitlines()[-1]
        assert out.startswith(str(data_dir / "resume_editor")), f"{mod}.{attr} 未落用户数据目录: {out}"


def test_runtime_dictionaries_live_in_dicts_and_are_tracked():
    dicts = Path(paths_mod.DICT_DIR)
    missing = [f for f in RUNTIME_DICTS if not (dicts / f).is_file()]
    assert not missing, f"dicts/ 缺运行时字典: {missing}"
    tracked = set(
        subprocess.run(
            ["git", "ls-files", "--", "resume_editor/dicts"],
            cwd=str(BACKEND), capture_output=True, text=True, check=True,
        ).stdout.split()
    )
    untracked = [f for f in RUNTIME_DICTS if f"resume_editor/dicts/{f}" not in tracked]
    assert not untracked, f"运行时字典未被 git 跟踪（全新 clone 会缺）: {untracked}"
