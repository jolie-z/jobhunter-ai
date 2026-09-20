#!/usr/bin/env python3
"""
Test Suite for Adaptive Skill Rewrite Prompt Assembly & Diagnosis Control
========================================================================
验证:
1. 占位符插值机制 ({{resume}}, {{jd}}, {{diagnosis}})
2. 标准黄金融合三段式拼装 (无占位符时的 JD + 深度诊断避坑 + 简历)
3. include_diagnosis 开关控制 (开启时注入诊断，关闭时纯净模式)
4. format_diagnosis_context 结构化情报提取
"""

import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ai_agents.skill_rewrite import assemble_adaptive_prompt, format_diagnosis_context


def test_format_diagnosis_context():
    sample_diag = {
        "dream_picture": "大模型与Agent架构实战专家，具备端到端落地经验",
        "ats_ability_analysis": "LangChain, RAG, LoRA, VectorDB, Prompt Engineering",
        "risk_red_flags": "切忌只写理论概念，严禁无真实工程落地指标",
        "strong_fit_assessment": "候选人的 AI 导购与知识库开发经验与 JD 100% 契合",
        "deep_action_plan": "将经历重点聚焦在 RAG 性能调优与召回率提升上"
    }

    formatted = format_diagnosis_context(sample_diag)
    assert "🎯 理想画像与能力信号" in formatted
    assert "🏷️ 核心能力词典" in formatted
    assert "🚩 致命硬伤与毒点预警" in formatted
    assert "⚡ 高杠杆匹配点" in formatted
    assert "🛠️ 破局行动计划" in formatted
    assert "切忌只写理论概念" in formatted
    print("✅ test_format_diagnosis_context passed!")


def test_assemble_standard_chunks_with_diagnosis():
    system_prompt = "# 极简简历改写 Prompt\n根据岗位要求改写简历。"
    resume = "个人经历：2023-2024 AI 工程师，主导 RAG 搭建。"
    jd = "岗位：大模型应用专家，要求精通 LangChain。"
    diag = {
        "risk_red_flags": "忌写空洞套话",
        "strong_fit_assessment": "候选人具备 RAG 实战"
    }

    sys_res, user_res = assemble_adaptive_prompt(
        system_prompt=system_prompt,
        original_resume=resume,
        jd_text=jd,
        diagnosis_dict=diag,
        include_diagnosis=True
    )

    assert sys_res == system_prompt
    assert "【目标岗位 JD】" in user_res
    assert "【💡 针对该岗位的 AI 专家深度解构与避坑指南" in user_res
    assert "忌写空洞套话" in user_res
    assert "【候选人原始简历】" in user_res
    assert "2023-2024 AI 工程师" in user_res
    print("✅ test_assemble_standard_chunks_with_diagnosis passed!")


def test_assemble_standard_chunks_without_diagnosis():
    system_prompt = "# 极简简历改写 Prompt\n根据岗位要求改写简历。"
    resume = "个人经历：2023-2024 AI 工程师。"
    jd = "岗位：大模型应用专家。"
    diag = {"risk_red_flags": "忌写空洞套话"}

    # 当 include_diagnosis = False 时，诊断报告应被完全排除
    sys_res, user_res = assemble_adaptive_prompt(
        system_prompt=system_prompt,
        original_resume=resume,
        jd_text=jd,
        diagnosis_dict=diag,
        include_diagnosis=False
    )

    assert "【目标岗位 JD】" in user_res
    assert "【候选人原始简历】" in user_res
    assert "避坑指南" not in user_res
    assert "忌写空洞套话" not in user_res
    print("✅ test_assemble_standard_chunks_without_diagnosis passed!")


def test_assemble_variable_interpolation():
    system_prompt = (
        "你是一个改写专家。\n"
        "岗位信息如下：\n{{jd}}\n\n"
        "诊断避坑参考：\n{{diagnosis}}\n\n"
        "候选人简历：\n{{resume}}\n\n"
        "请开始输出。"
    )
    resume = "我的简历内容：某美妆电商运营"
    jd = "TikTok 运营经理 JD"
    diag = {"risk_red_flags": "严禁虚构 GMV 数据"}

    sys_res, user_res = assemble_adaptive_prompt(
        system_prompt=system_prompt,
        original_resume=resume,
        jd_text=jd,
        diagnosis_dict=diag,
        include_diagnosis=True
    )

    assert "{{jd}}" not in sys_res
    assert "TikTok 运营经理 JD" in sys_res
    assert "{{resume}}" not in sys_res
    assert "我的简历内容：某美妆电商运营" in sys_res
    assert "{{diagnosis}}" not in sys_res
    assert "严禁虚构 GMV 数据" in sys_res
    print("✅ test_assemble_variable_interpolation passed!")


if __name__ == "__main__":
    print("🚀 Running Adaptive Skill Rewrite Prompt Tests...")
    test_format_diagnosis_context()
    test_assemble_standard_chunks_with_diagnosis()
    test_assemble_standard_chunks_without_diagnosis()
    test_assemble_variable_interpolation()
    print("\n🎉 ALL ADAPTIVE PROMPT TESTS 100% PASSED!")
