#!/usr/bin/env python3
"""
Test Tool-Use Progressive Skill Agent Runner
============================================
测试基于 Tool-Use 的渐进式 Skill 智能体执行引擎（工具定义、文件查阅、阶段落盘、产物归档）。
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai_agents.skills.skill_agent_runner import run_progressive_skill_agent, SKILL_AGENT_TOOLS
from ai_agents.skills.skill_dirs import list_job_skill_artifacts, delete_job_results


class TestSkillAgentRunner(unittest.TestCase):

    def setUp(self):
        self.job_id = "test_agent_job_001"
        self.skill_id = "test_package_skill"
        self.ref_map = {
            "references/01_jd_analysis.md": "# 岗位解构规范\n必须提炼 3 个核心信号与硬性门槛。",
            "references/02_truth_boundary.md": "# 真实性边界规范\n严禁把自研 MVP 包装成千万级商业 SaaS。",
            "references/06_resume_rubric.md": "# 定制简历结构标准\n输出 5 大核心模块。"
        }
        self.main_skill = "# 测试大模型改写技能\nStep 1: 查阅 01_jd_analysis\nStep 2: 查阅 02_truth_boundary\nStep 3: 输出最终简历。"

    def tearDown(self):
        delete_job_results(self.job_id)

    def test_tools_schema_definition(self):
        """验证提供的工具集定义符合 OpenAI 标准"""
        tool_names = [t["function"]["name"] for t in SKILL_AGENT_TOOLS]
        self.assertIn("list_references", tool_names)
        self.assertIn("read_reference", tool_names)
        self.assertIn("save_step_artifact", tool_names)

    @patch("ai_agents.skills.skill_agent_runner.get_openai_client")
    def test_progressive_agent_loop_with_tool_calls(self, mock_get_client):
        """模拟 Agent 接收到 SOP 后，先调用 read_reference 查阅，再调用 save_step_artifact 落盘，最终完成定稿"""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # 模拟第 1 轮回复：Agent 发起 tool_call 查阅 01_jd_analysis.md 并保存第 1 步产物
        tc1 = MagicMock()
        tc1.id = "call_001"
        tc1.type = "function"
        tc1.function.name = "read_reference"
        tc1.function.arguments = '{"file_name": "references/01_jd_analysis.md"}'

        msg1 = MagicMock()
        msg1.content = "我先查阅 01_jd_analysis.md 规范"
        msg1.tool_calls = [tc1]
        msg1.reasoning_content = "准备执行 Step 1"

        resp1 = MagicMock()
        resp1.choices = [MagicMock(message=msg1)]
        resp1.usage = MagicMock(prompt_tokens=500, completion_tokens=100)

        # 模拟第 2 轮回复：Agent 保存第 1 步产物并查阅第 2 步规范
        tc2 = MagicMock()
        tc2.id = "call_002"
        tc2.type = "function"
        tc2.function.name = "save_step_artifact"
        tc2.function.arguments = '{"filename": "01_jd_analysis.md", "title": "岗位解构报告", "markdown_content": "## 岗位解构完成\\n- 核心信号: AI 全栈"}'

        msg2 = MagicMock()
        msg2.content = "已完成 Step 1，正在保存"
        msg2.tool_calls = [tc2]
        msg2.reasoning_content = "落盘第一阶段产物"

        resp2 = MagicMock()
        resp2.choices = [MagicMock(message=msg2)]
        resp2.usage = MagicMock(prompt_tokens=600, completion_tokens=150)

        # 模拟第 3 轮回复：Agent 生成最终简历并定稿
        msg3 = MagicMock()
        msg3.content = "<FINAL_RESUME>\n# 张三 - AI 全栈工程师\n## 个人优势\n- 熟练掌握 LangGraph 与 Agent 研发\n</FINAL_RESUME>"
        msg3.tool_calls = []
        msg3.reasoning_content = "完成定稿"

        resp3 = MagicMock()
        resp3.choices = [MagicMock(message=msg3)]
        resp3.usage = MagicMock(prompt_tokens=700, completion_tokens=200)

        mock_client.chat.completions.create.side_effect = [resp1, resp2, resp3]

        final_md, usage, artifacts = run_progressive_skill_agent(
            skill_id=self.skill_id,
            main_skill_content=self.main_skill,
            reference_map=self.ref_map,
            original_resume="原版简历文本",
            jd_text="目标 JD 文本",
            job_name="AI Agent 工程师",
            job_record_id=self.job_id,
            max_turns=5
        )

        # 验证断言
        self.assertIn("张三 - AI 全栈工程师", final_md)
        self.assertEqual(usage["total_tokens"], 2250)
        self.assertTrue(len(artifacts) >= 1)
        self.assertEqual(artifacts[0]["name"], "01_jd_analysis.md")

        # 验证文件系统确实落地了产物
        saved_files = list_job_skill_artifacts(self.job_id, self.skill_id)
        self.assertTrue(len(saved_files) >= 1)
        filenames = [f["name"] for f in saved_files]
        self.assertIn("01_jd_analysis.md", filenames)
        print("🎉 Tool-Use Skill Agent Runner Unit Test 100% PASS!")


if __name__ == "__main__":
    unittest.main()
