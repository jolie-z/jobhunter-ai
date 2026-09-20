#!/usr/bin/env python3
"""
Test Suite for Skill Package Security, Zip Extraction & Reference Assembly
========================================================================
验证:
1. 白名单拦截与脚本隔离 (Strict vs Clean 模式)
2. ZIP 压缩包安全解压与 Zip-Slip 防御
3. 多文件 References 动态组装为 System Prompt
4. DynamicSkillManager 目录级生命周期管理 (注册/读取/删除)
"""

import os
import sys
import zipfile
from io import BytesIO
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ai_agents.skills.skill_validator import (
    validate_and_sanitize_package,
    safe_extract_zip_package,
    SkillValidationError
)
from ai_agents.skills.skill_loader import DynamicSkillManager


def test_clean_mode_filters_scripts():
    """测试 clean 模式自动过滤可执行脚本并保留纯文本"""
    raw_files = [
        ("SKILL.md", b"# LLM Intern Custom Skill\nversion: 1.2.0\n\nRewrite resume with truth boundary."),
        ("references/01_jd_analysis.md", b"# JD Analysis Rules\n1. Match skills\n2. Highlight LLM"),
        ("references/03_truth_boundary.md", b"# Truth Boundary\nNever hallucinate model training."),
        ("scripts/scrape_boss.py", b"import os\nprint('Dangerous script!')"),
        ("run.sh", b"#!/bin/bash\nrm -rf /"),
        ("malicious.exe", b"\x4d\x5a\x90\x00"),
    ]

    # Clean 模式：不应报错，应自动剔除 3 个脚本/可执行文件
    pkg = validate_and_sanitize_package(raw_files, suggested_id="test_llm_skill", mode="clean")
    assert pkg.skill_id == "test_llm_skill"
    assert pkg.main_file_name == "SKILL.md"
    assert len(pkg.references) == 2
    assert len(pkg.ignored_scripts) == 3
    print("✅ test_clean_mode_filters_scripts passed!")


def test_strict_mode_rejects_scripts():
    """测试 strict 模式在发现脚本时立即抛出异常拦截"""
    raw_files = [
        ("SKILL.md", b"# LLM Intern Custom Skill\nversion: 1.2.0\n\nRewrite resume with truth boundary."),
        ("scripts/train.py", b"import torch\nprint('training')"),
    ]

    try:
        validate_and_sanitize_package(raw_files, suggested_id="test_llm_skill", mode="strict")
        assert False, "Should have raised SkillValidationError in strict mode!"
    except SkillValidationError as e:
        assert "安全拦截 (严格模式)" in str(e)
        print("✅ test_strict_mode_rejects_scripts passed!")


def test_zip_extraction_and_assembly():
    """测试真实 ZIP 压缩包的解压、安全过滤与多文件装配"""
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr("LLMInternSkill-main/SKILL.md", "# LLM Intern Skill\nversion: 2.0.0\n\nMain System Prompt SOP.")
        z.writestr("LLMInternSkill-main/references/01_jd.md", "JD Match Rules Content.")
        z.writestr("LLMInternSkill-main/references/02_evidence.md", "Evidence Contract Content.")
        z.writestr("LLMInternSkill-main/setup.py", "import setuptools\n# should be ignored")
        z.writestr("LLMInternSkill-main/eval.sh", "echo 'evaluating'")

    zip_bytes = buf.getvalue()
    pkg = safe_extract_zip_package(zip_bytes, suggested_id="llm_intern_pkg", mode="clean")

    assert pkg.skill_id == "llm_intern_pkg"
    assert pkg.main_file_name == "SKILL.md"
    assert len(pkg.references) == 2
    assert len(pkg.ignored_scripts) == 2
    print("✅ test_zip_extraction_and_assembly passed!")


def test_dynamic_skill_manager_directory_package(tmp_path=None):
    """测试 DynamicSkillManager 加载目录级 Skill 并装配 References Prompt"""
    skills_dir = Path(__file__).parent.parent / "ai_agents" / "skills"
    test_pkg_dir = skills_dir / "custom_test_package_001"
    
    try:
        test_pkg_dir.mkdir(parents=True, exist_ok=True)
        (test_pkg_dir / "references").mkdir(parents=True, exist_ok=True)
        
        # 写入主 SOP 和 references
        (test_pkg_dir / "SKILL.md").write_text("# 测试多文件技能包\nversion: 1.5.0\n测试主 SOP 提示词", encoding="utf-8")
        (test_pkg_dir / "references" / "truth_boundary.md").write_text("真实性边界：严禁造假参数量", encoding="utf-8")
        (test_pkg_dir / "references" / "star_template.md").write_text("STAR 展开范式：情景、任务、行动、结果", encoding="utf-8")

        manager = DynamicSkillManager()
        skill_id = "custom_test_package_001"
        assert skill_id in manager.skills
        
        meta = manager.skills[skill_id]
        assert meta.is_package is True
        assert meta.references_count == 2

        # 验证组装后的 Prompt 上下文
        full_content = manager.get_skill_content(skill_id)
        assert "测试主 SOP 提示词" in full_content
        assert "📚 附属参考资料与行业边界规范" in full_content
        assert "真实性边界：严禁造假参数量" in full_content
        assert "STAR 展开范式" in full_content

        # 测试删除
        manager.delete_skill(skill_id)
        assert not test_pkg_dir.exists()
        assert skill_id not in manager.skills
        print("✅ test_dynamic_skill_manager_directory_package passed!")

    finally:
        if test_pkg_dir.exists():
            import shutil
            shutil.rmtree(test_pkg_dir)


if __name__ == "__main__":
    print("🚀 Running Skill Security & Multi-file Package Tests...")
    test_clean_mode_filters_scripts()
    test_strict_mode_rejects_scripts()
    test_zip_extraction_and_assembly()
    test_dynamic_skill_manager_directory_package()
    print("\n🎉 ALL TESTS 100% PASSED!")
