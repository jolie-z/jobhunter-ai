#!/usr/bin/env python3
"""
Test Suite for Skill Multi-Artifacts & Markdown Fill Endpoints
=============================================================
验证:
1. skill_dirs 多产物本地归档、扫描列表与安全读取
2. /api/strategy/skill_artifacts/{job_id} 路由
3. /api/strategy/fill_resume_from_markdown 非标 Markdown 结构化转换与隐私缝合
"""

import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app
from ai_agents.skills.skill_dirs import (
    save_skill_result,
    list_job_skill_artifacts,
    get_artifact_content,
    delete_job_results,
    is_resume_filename
)


client = TestClient(app)


def test_skill_dirs_core_logic():
    test_job_id = "test-job-artifacts-999"
    test_skill_id = "llm-intern-skill"

    # 1. 保存多产物文件
    files = [
        {"name": "01_jd_analysis.md", "content": "# 目标岗位 JD 深度解构\n要求精通 RAG 与 Agent。"},
        {"name": "06_targeted_resume.md", "content": "# 定制版简历\n## 个人优势\n- 精通大模型应用开发。"},
        {"name": "07_interview_grilling.md", "content": "# 面试追问卡\nQ: 如何评估 RAG 召回率？\nA: 使用 Hit Rate 和 MRR。"}
    ]
    res = save_skill_result(
        job_record_id=test_job_id,
        skill_id=test_skill_id,
        files=files,
        token_usage={"total_tokens": 3500}
    )
    assert res["success"] is True
    assert len(res["files_saved"]) == 3

    # 2. 验证智能标签判断
    assert is_resume_filename("06_targeted_resume.md") is True
    assert is_resume_filename("01_jd_analysis.md") is False
    assert is_resume_filename("07_interview_grilling.md") is False

    # 3. 扫描列表
    artifacts = list_job_skill_artifacts(test_job_id)
    assert len(artifacts) == 3
    # 推荐简历应该排在最前面
    assert artifacts[0]["is_resume_candidate"] is True
    assert artifacts[0]["name"] == "06_targeted_resume.md"

    # 4. 安全读取内容
    content = get_artifact_content(test_job_id, test_skill_id, "07_interview_grilling.md")
    assert content is not None
    assert "面试追问卡" in content

    # 5. 防目录遍历注入测试
    unsafe_content = get_artifact_content(test_job_id, test_skill_id, "../../../etc/passwd")
    assert unsafe_content is None

    # 6. 清理
    delete_job_results(test_job_id)
    print("✅ test_skill_dirs_core_logic passed!")


def test_skill_artifacts_endpoints():
    test_job_id = "rec123456789api"
    test_skill_id = "llm-intern-skill"

    # 预置产物
    save_skill_result(
        job_record_id=test_job_id,
        skill_id=test_skill_id,
        files=[
            {"name": "01_jd_analysis.md", "content": "# JD分析"},
            {"name": "06_targeted_resume.md", "content": "# 简历主稿"}
        ],
        token_usage={"total_tokens": 1200}
    )

    try:
        # GET 列表
        resp = client.get(f"/api/strategy/skill_artifacts/{test_job_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert len(data["data"]) == 2

        # GET 单文件内容
        file_resp = client.get(f"/api/strategy/skill_artifacts/{test_job_id}/{test_skill_id}/06_targeted_resume.md")
        assert file_resp.status_code == 200
        file_data = file_resp.json()
        assert file_data["status"] == "success"
        assert "# 简历主稿" in file_data["data"]["content"]

        # DELETE 单文件
        del_file_resp = client.delete(f"/api/strategy/skill_artifacts/{test_job_id}/{test_skill_id}/01_jd_analysis.md")
        assert del_file_resp.status_code == 200

        # 再次获取列表，应该只剩 1 个
        resp_after_del = client.get(f"/api/strategy/skill_artifacts/{test_job_id}")
        assert len(resp_after_del.json()["data"]) == 1

        # DELETE 整个技能产物
        del_skill_resp = client.delete(f"/api/strategy/skill_artifacts/{test_job_id}/{test_skill_id}")
        assert del_skill_resp.status_code == 200

    finally:
        delete_job_results(test_job_id)
    print("✅ test_skill_artifacts_endpoints passed!")


def test_fill_resume_from_markdown_api(monkeypatch):
    from unittest.mock import AsyncMock
    mock_json = {
        "personalInfo": {"name": "张三", "phone": "13800000000"},
        "summary": "AI 算法研究与工程专家",
    }
    monkeypatch.setattr("ai_agents.markdown_to_json.parse_markdown_to_json", lambda md: mock_json)
    monkeypatch.setattr("app.core.feishu_client.feishu_client.get_tenant_access_token", AsyncMock(return_value=None))

    sample_custom_md = """# 张三 - AI 算法研究与工程专家

## 💡 个人优势亮点
- 拥有 5 年大模型与智能体实战开发经验，主导百亿参数模型应用落地。
- 熟悉 LangChain, RAG 架构与多 Agent 协作系统。

## 🏷️ 核心技术栈
- 大模型技术：LLM, Prompt Engineering, RAG, LoRA 微调
- 编程语言与框架：Python, FastAPI, PyTorch, LangChain, React

## 💼 算法与工程实战
### 智谱AI | 大模型应用架构师 (2022.06 - 至今)
- **[情景与任务]** 负责企业级智能知识库与 Agent 平台从 0 到 1 的搭建
- **[行动与成果]** 设计分层向量检索机制，将检索准确率提升 35%，问答耗时降低 40%

## 🎓 教育背景
### 清华大学 | 计算机科学与技术 (硕士, 2017.09 - 2020.06)
"""

    resp = client.post(
        "/api/strategy/fill_resume_from_markdown",
        json={"markdown_content": sample_custom_md}
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "success"
    parsed_json = res_data["data"]["parsed_json"]

    assert "personalInfo" in parsed_json
    assert "summary" in parsed_json
    print("✅ test_fill_resume_from_markdown_api passed!")


def test_skill_rewrite_async_and_logs_api():
    """测试异步改写任务创建与 SSE 日志流接口"""
    resp = client.post(
        "/api/strategy/skill_rewrite_async",
        json={
            "job_id": "test_job_async_123",
            "jd_text": "招聘 AI Agent 工程师，精通 LangGraph",
            "job_name": "AI Agent 工程师",
            "skill_id": "resume_rewrite"
        }
    )
    assert resp.status_code == 200
    res_json = resp.json()
    assert res_json["status"] == "success"
    assert "task_id" in res_json
    task_id = res_json["task_id"]
    assert task_id.startswith("skill_task_")

    # 验证 SSE 日志流是否能够正常握手
    sse_resp = client.get(f"/api/strategy/skill_agent_logs?task_id={task_id}")
    assert sse_resp.status_code == 200
    assert "text/event-stream" in sse_resp.headers.get("content-type", "")
    print("✅ test_skill_rewrite_async_and_logs_api passed!")


def test_artifacts_job_id_dual_scope_resolution():
    """锁住产物目录双口径解析：agent 写入用完整 job_id，读取兼容清洗/原始两种口径（Q-M4-1 候选集实现）"""
    from app.strategy.routes.skill_artifacts_router import _artifact_id_candidates

    full_id = "测试平台-recDualScope01"
    pure_id = "recDualScope01"
    try:
        # 场景1：仅完整口径目录存在（agent 现行写入口径）→ 候选集含两种口径，API 可查
        save_skill_result(
            job_record_id=full_id,
            skill_id="llm-intern-skill",
            files=[{"name": "01_dual_a.md", "content": "# 双口径原始"}],
            token_usage={},
        )
        assert _artifact_id_candidates(full_id) == [full_id, pure_id]
        resp = client.get(f"/api/strategy/skill_artifacts/{full_id}")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

        # 场景2：纯 record_id 目录也存在（历史口径）→ 双口径并集均可见
        save_skill_result(
            job_record_id=pure_id,
            skill_id="llm-intern-skill",
            files=[{"name": "01_dual_b.md", "content": "# 双口径清洗"}],
            token_usage={},
        )
        resp2 = client.get(f"/api/strategy/skill_artifacts/{full_id}")
        assert len(resp2.json()["data"]) == 2
        assert {r["name"] for r in resp2.json()["data"]} == {"01_dual_a.md", "01_dual_b.md"}
    finally:
        delete_job_results(full_id)
        delete_job_results(pure_id)
    print("✅ test_artifacts_job_id_dual_scope_resolution passed!")


def test_artifacts_rejects_unsafe_job_id():
    """fail-closed：非法路径段（穿越/分隔符/盘符）在候选层即被剔除，绝不进入文件系统操作（Q-M4-1 契约）"""
    from app.strategy.routes.skill_artifacts_router import _artifact_id_candidates

    for bad in ["..", ".", "a/b", "a\\b", "C:", ""]:
        assert _artifact_id_candidates(bad) == []
    # API 层 fail-closed：非法 id 安全空转（200 空清单），不抛 500、不触碰文件系统（用盘符样例避免路由层斜杠语义）
    resp = client.get("/api/strategy/skill_artifacts/C:")
    assert resp.status_code == 200
    assert resp.json()["data"] == []
    print("✅ test_artifacts_rejects_unsafe_job_id passed!")


if __name__ == "__main__":
    print("🚀 Running Skill Artifacts & Fill API Tests...")
    test_skill_dirs_core_logic()
    test_skill_artifacts_endpoints()
    test_fill_resume_from_markdown_api()
    test_skill_rewrite_async_and_logs_api()
    print("\n🎉 ALL SKILL ARTIFACTS TESTS 100% PASSED!")
