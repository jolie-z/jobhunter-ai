"""自定义技能根 db_paths 阀门回归（2026-10-26，更新清空用户数据事故第二波）。

事故：自定义技能与内置技能同目录（SKILLS_DIR = 模块所在目录），打包形态位于安装目录
resources 内，自动更新整体替换 resources 即清空用户上传的全部技能——与 skill_runs 同根因。

回归口径：
  1. 开发态（无 env）→ CUSTOM_SKILLS_DIR 与 SKILLS_DIR 同目录，历史行为逐字保持；
  2. 打包态（JOBHUNTER_DATA_DIR）→ CUSTOM_SKILLS_DIR = <DATA_DIR>/skills，内置根不变；
  3. 两根拆开时：内置技能从 SKILLS_DIR 加载且 is_official；自定义根下一律非官方（含未加前缀的）；
     自定义根不存在（全新安装）静默跳过，不影响内置技能；
  4. 上传只落 CUSTOM_SKILLS_DIR，内置根零写入。
"""

import importlib
import os
from pathlib import Path

import ai_agents.skills.skill_loader as loader_mod
from ai_agents.skills.skill_loader import DynamicSkillManager
from ai_agents.skills.skill_validator import SanitizedSkillPackage

_ENV_KEYS = ("JOBHUNTER_DATA_DIR",)


def _reload_with(env: dict):
    saved = {k: os.environ.get(k) for k in _ENV_KEYS}
    try:
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        os.environ.update(env)
        return importlib.reload(loader_mod)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_custom_skills_dir_follows_data_dir_valve(tmp_path):
    try:
        mod = _reload_with({})
        bundled = Path(mod.__file__).parent
        assert mod.DynamicSkillManager.SKILLS_DIR == bundled
        assert mod.DynamicSkillManager.CUSTOM_SKILLS_DIR == bundled  # 开发态同目录

        data_dir = tmp_path / "userData"
        mod = _reload_with({"JOBHUNTER_DATA_DIR": str(data_dir)})
        assert mod.DynamicSkillManager.SKILLS_DIR == bundled  # 内置根不随 env 变
        assert mod.DynamicSkillManager.CUSTOM_SKILLS_DIR == data_dir / "skills"
    finally:
        importlib.reload(loader_mod)


def _write_pkg(root: Path, name: str, title: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"# {title}\n\n剧本正文\n", encoding="utf-8")
    (d / "references" ).mkdir()
    (d / "references" / "rules.md").write_text("# 规则\n", encoding="utf-8")


def test_split_roots_load_both_and_flag_official_correctly(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    custom = tmp_path / "userData" / "skills"
    bundled.mkdir()
    custom.mkdir(parents=True)
    (bundled / "resume_rewrite.md").write_text("# 官方简历改写\n\n正文\n", encoding="utf-8")
    _write_pkg(custom, "custom_pkg", "自定义技能包")
    (custom / "custom_single.md").write_text("# 单文件自定义\n\n正文\n", encoding="utf-8")
    _write_pkg(custom, "mytool", "未加前缀的手动放入技能")  # 用户手动丢进数据目录

    monkeypatch.setattr(DynamicSkillManager, "SKILLS_DIR", bundled)
    monkeypatch.setattr(DynamicSkillManager, "CUSTOM_SKILLS_DIR", custom)
    mgr = DynamicSkillManager()

    assert set(mgr.skills) == {"resume_rewrite", "custom_pkg", "custom_single", "mytool"}
    assert mgr.skills["resume_rewrite"].is_official is True
    assert mgr.skills["custom_pkg"].is_official is False
    assert mgr.skills["custom_single"].is_official is False
    # 自定义根下不依赖命名：未加前缀也必须可删，否则用户数据目录里出现"官方技能"
    assert mgr.skills["mytool"].is_official is False
    assert mgr.skills["custom_pkg"].references_count == 1


def test_missing_custom_root_is_silently_skipped(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "greeting_writer.md").write_text("# 打招呼\n\n正文\n", encoding="utf-8")

    monkeypatch.setattr(DynamicSkillManager, "SKILLS_DIR", bundled)
    monkeypatch.setattr(DynamicSkillManager, "CUSTOM_SKILLS_DIR", tmp_path / "userData" / "skills")
    mgr = DynamicSkillManager()  # 全新安装：自定义根尚未创建

    assert set(mgr.skills) == {"greeting_writer"}
    assert mgr.skills["greeting_writer"].is_official is True


def test_upload_persists_only_into_custom_root(tmp_path, monkeypatch):
    import app.api.routes.skills_upload as upload_mod

    bundled = tmp_path / "bundled"
    custom = tmp_path / "userData" / "skills"
    bundled.mkdir()

    class _Fake:
        SKILLS_DIR = bundled
        CUSTOM_SKILLS_DIR = custom

    monkeypatch.setattr(upload_mod, "get_skill_manager", lambda: _Fake())

    pkg = SanitizedSkillPackage(
        skill_id="valve_pkg",
        main_file_name="SKILL.md",
        main_file_content="# 阀门技能包\n\n正文\n",
        references=[{"name": "references/a.md", "content": "# A\n", "size": 4}],
    )
    out_dir = upload_mod._persist_sanitized_package(pkg, custom_name="阀门技能包")
    assert out_dir == custom / "custom_valve_pkg"
    assert (out_dir / "SKILL.md").exists()
    assert (out_dir / "meta.json").exists()

    single = SanitizedSkillPackage(
        skill_id="valve_single",
        main_file_name="x.md",
        main_file_content="# 单文件\n\n正文\n",
    )
    out_file = upload_mod._persist_sanitized_package(single)
    assert out_file == custom / "custom_valve_single.md"
    assert (custom / "custom_valve_single.json").exists()

    # 内置根零写入
    assert list(bundled.iterdir()) == []
