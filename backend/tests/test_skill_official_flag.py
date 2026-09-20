"""官方/自定义技能判定（is_official）回归测试。

背景：判定逻辑曾用绝对路径子串 `"custom" in str(file_path)` 匹配，worktree 目录名
（qa-custom-panel）含 "custom" 时，全部官方技能被误判为自定义，详情弹窗给官方剧本
挂出删除按钮。修复后只看 id 前缀与相对 SKILLS_DIR 的路径。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai_agents.skills.skill_loader import DynamicSkillManager


def _make_manager(tmp_path: Path) -> DynamicSkillManager:
    manager = DynamicSkillManager.__new__(DynamicSkillManager)
    manager.SKILLS_DIR = tmp_path
    manager.skills = {}
    manager.loaded_contents = {}
    manager.reference_maps = {}
    return manager


def test_official_skill_in_worktree_dir_with_custom_in_abs_path():
    """核心回归：绝对路径含 custom（worktree 目录名 qa-custom-panel）不得影响判定。

    file_path 在 SKILLS_DIR 下，relative_to 成功 → 相对路径 resume_rewrite.md 不含
    custom → 官方。旧逻辑用绝对路径子串匹配，此场景误判为自定义。
    """
    manager = _make_manager(Path("/some/qa-custom-panel/backend/ai_agents/skills"))
    meta = manager._parse_metadata_from_text(
        "# 官方标准剧本\n本任务的目标是改写简历", "resume_rewrite", Path("/some/qa-custom-panel/backend/ai_agents/skills/resume_rewrite.md")
    )
    assert meta.is_official is True


def test_official_skill_outside_skills_dir_falls_back_to_filename(tmp_path):
    """ValueError 回退分支：file_path 不在 SKILLS_DIR 下，回退文件名判定"""
    manager = _make_manager(tmp_path / "skills")
    meta = manager._parse_metadata_from_text(
        "# 官方标准剧本\n描述", "resume_rewrite", Path("/elsewhere/resume_rewrite.md")
    )
    assert meta.is_official is True


def test_official_skill_at_skills_root(tmp_path):
    manager = _make_manager(tmp_path)
    meta = manager._parse_metadata_from_text(
        "# 官方标准剧本\n描述", "resume_rewrite", tmp_path / "resume_rewrite.md"
    )
    assert meta.is_official is True


def test_custom_id_is_custom(tmp_path):
    manager = _make_manager(tmp_path)
    meta = manager._parse_metadata_from_text(
        "# 岗位详情skill\n描述", "custom_interview_prep", tmp_path / "custom_interview_prep" / "SKILL.md"
    )
    assert meta.is_official is False


def test_custom_prefixed_file_at_root_is_custom(tmp_path):
    manager = _make_manager(tmp_path)
    meta = manager._parse_metadata_from_text(
        "# 某自定义技能\n描述", "custom_foo", tmp_path / "custom_foo.md"
    )
    assert meta.is_official is False
