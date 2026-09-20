#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Schema Diff 差分探针与元数据模版自愈引擎单元测试
"""

import json
import os
import shutil
import tempfile
import pytest

from resume_editor.schema_diff_engine import (
    is_runtime_noise,
    is_system_metadata,
    clean_runtime_noise,
    diff_platform_schema,
    apply_schema_patch,
    save_schema_snapshot,
)


def test_is_system_metadata_heuristics():
    """验证启发式底层系统元数据动态识别（时间戳、ID、CDN图床、影子字段等）"""
    # 时间戳模式
    assert is_system_metadata("createTime", "2020-09-12 00:21:51") is True
    assert is_system_metadata("update_time", "2026-08-19 20:46:54") is True
    # 业务月份不会被误杀
    assert is_system_metadata("startTime", "2023-09") is False

    # 系统ID与流水号
    assert is_system_metadata("resumeId", "369525152") is True
    assert is_system_metadata("moduleId", "0006") is True
    assert is_system_metadata("licenseId", "91440101MA5D64Q828") is True
    # 业务编号不会被误杀（如非系统ID）
    assert is_system_metadata("patentNumber", "ZL202310123456") is False

    # CDN 图床
    assert is_system_metadata("logoUrl", "https://imgjl.51jobcdn.com/im/mkt/app/homelogo/default.png") is True
    # 业务项目 URL 不会被误杀
    assert is_system_metadata("projectUrl", "https://github.com/myproject/core") is False

    # 系统标志位
    assert is_system_metadata("complete", True) is True
    assert is_system_metadata("isEnglish", False) is True
    assert is_system_metadata("seekType", 0) is True

    # 动态影子镜像字段
    parent = {
        "skills": ["Python", "Vue"],
        "industry": "113",
        "workIndustry": "113",
    }
    assert is_system_metadata("workVocationalSkills", ["Python", "Vue"], parent) is True
    assert is_system_metadata("workIndustryNew", "113", parent) is True
    assert is_system_metadata("workLabels", [], parent) is True
    # 真正的新业务字段绝不被误判
    assert is_system_metadata("customBonus", "50000", parent) is False


def test_is_runtime_noise():
    """验证前端运行态噪音属性过滤"""
    assert is_runtime_noise("_isHover") is True
    assert is_runtime_noise("isEditing") is True
    assert is_runtime_noise("__ob__") is True
    assert is_runtime_noise("industryTranslation") is True
    assert is_runtime_noise("workIndustryString") is True
    assert is_runtime_noise("_uid") is True
    assert is_runtime_noise("temp_preview") is True

    # 真正的业务字段不能被误杀
    assert is_runtime_noise("companyName") is False
    assert is_runtime_noise("jobTitle") is False
    assert is_runtime_noise("trainAddress") is False
    assert is_runtime_noise("patentCode") is False
    assert is_runtime_noise("workDesc") is False


def test_clean_runtime_noise():
    """验证嵌套结构中的噪音清洗"""
    raw_data = {
        "_isHover": True,
        "profile": {
            "name": "张三",
            "_editing": False,
            "genderTranslation": "男",
        },
        "workExperience": [
            {
                "companyName": "科技公司",
                "__ob__": {},
                "_uid": 123,
                "jobTitle": "前端专家",
            }
        ]
    }
    cleaned = clean_runtime_noise(raw_data)
    assert "_isHover" not in cleaned
    assert cleaned["profile"]["name"] == "张三"
    assert "_editing" not in cleaned["profile"]
    assert "genderTranslation" not in cleaned["profile"]
    assert cleaned["workExperience"][0]["companyName"] == "科技公司"
    assert "__ob__" not in cleaned["workExperience"][0]
    assert "_uid" not in cleaned["workExperience"][0]


def test_diff_platform_schema_no_changes():
    """验证结构一致时无变动识别"""
    baseline = {
        "profile": {"name": "张三", "mobile": "13800000000"},
        "workExperience": [{"companyName": "科技公司", "jobTitle": "研发"}]
    }
    fresh = {
        "profile": {"name": "张三", "mobile": "13800000000", "_isHover": True},
        "workExperience": [{"companyName": "科技公司", "jobTitle": "研发", "__ob__": {}}]
    }
    diff = diff_platform_schema("zhilian", fresh, baseline)
    assert diff["has_changes"] is False
    assert len(diff["added_fields"]) == 0
    assert len(diff["removed_fields"]) == 0
    assert len(diff["new_modules"]) == 0
    assert len(diff["removed_modules"]) == 0


def test_diff_platform_schema_added_and_removed_fields():
    """验证新增字段、废弃字段与全新模块识别"""
    baseline = {
        "profile": {"name": "张三", "oldField": "123"},
        "workExperience": [{"companyName": "科技公司", "jobTitle": "研发", "dailyWage": "500"}]
    }
    fresh = {
        "profile": {"name": "张三", "githubUrl": "https://github.com/abc"},
        "workExperience": [{"companyName": "科技公司", "jobTitle": "研发", "remoteWork": True}],
        "patentModule": [{"patentName": "AI发明专利", "patentCode": "CN10001"}]
    }
    diff = diff_platform_schema("zhilian", fresh, baseline)
    assert diff["has_changes"] is True
    
    # 验证全新模块
    new_mods = [m["module"] for m in diff["new_modules"]]
    assert "patentModule" in new_mods

    # 验证新增字段
    added = [(f["module"], f["field"]) for f in diff["added_fields"]]
    assert ("profile", "githubUrl") in added
    assert ("workExperience", "remoteWork") in added

    # 验证废弃字段
    removed = [(f["module"], f["field"]) for f in diff["removed_fields"]]
    assert ("profile", "oldField") in removed
    assert ("workExperience", "dailyWage") in removed


def test_apply_schema_patch_atomic_update():
    """验证应用补丁后模版原子级对齐与软归档"""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test_plat_fields.json")
        initial_data = {
            "profile": {"name": "李四", "obsoleteKey": "abc"},
            "workExperience": [{"companyName": "某厂", "jobTitle": "PM", "oldSalary": "10k"}]
        }
        with open(test_file, "w", encoding="utf-8") as f:
            json.dump(initial_data, f, ensure_ascii=False, indent=2)

        import resume_editor.schema_diff_engine as sde
        orig_data_dir = sde.DATA_DIR
        sde.DATA_DIR = tmpdir
        try:
            diff_result = {
                "platform": "test_plat",
                "has_changes": True,
                "summary": "新增 1 字段，下线 1 字段",
                "new_modules": [{"module": "awards", "type": "array", "item_count": 1}],
                "removed_modules": [],
                "added_fields": [{"module": "workExperience", "field": "department", "sample": "核心业务线"}],
                "removed_fields": [{"module": "workExperience", "field": "oldSalary", "last_value": "10k"}],
            }
            fresh_data = {
                "awards": [{"awardName": "最佳贡献奖", "awardYear": "2025"}]
            }
            res = apply_schema_patch("test_plat", diff_result, fresh_data=fresh_data)
            assert res["success"] is True

            with open(test_file, "r", encoding="utf-8") as f:
                patched = json.load(f)

            # 验证新模块添加
            assert "awards" in patched
            assert patched["awards"][0]["awardName"] == "最佳贡献奖"

            # 验证字段新增
            assert patched["workExperience"][0]["department"] == "核心业务线"

            # 验证废弃字段被软归档
            assert "oldSalary" not in patched["workExperience"][0]
            assert patched["workExperience"][0]["_deprecated_fields"]["oldSalary"] == "10k"

        finally:
            sde.DATA_DIR = orig_data_dir
