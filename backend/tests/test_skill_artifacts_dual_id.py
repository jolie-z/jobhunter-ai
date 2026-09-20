"""Q-M4-1 回归：Skill 产物库「双口径 jobId」解析与合并逻辑。

写入侧存在两种历史口径：
- 异步改写通道按调用方完整 jobId 建目录（如 `BOSS直聘-rec123`）；
- 同步通道按 extract_record_id 清洗后的纯 record_id 建目录（如 `rec123`）。
读取/删除侧必须两种口径都覆盖，否则异步通道产物在产物库恒为空。
"""
# ruff: noqa: ARG001 —— 测试桩函数的未用参数是签名兼容契约本身
from app.strategy.routes.skill_artifacts_router import _artifact_id_candidates


class TestArtifactIdCandidates:
    def test_composite_job_id_yields_both_candidates(self):
        """完整复合 jobId（异步通道写入口径）→ 原样 + 清洗后两个候选"""
        cands = _artifact_id_candidates("BOSS直聘-recabc123")
        assert cands[0] == "BOSS直聘-recabc123"
        assert "recabc123" in cands

    def test_plain_record_id_dedupes_to_single(self):
        """纯 record_id：清洗后与原样相同，必须去重不重复扫描"""
        cands = _artifact_id_candidates("recabc123")
        assert cands == ["recabc123"]

    def test_empty_id_yields_no_candidates(self):
        """空 id：无候选（各路由安全空转），不得回落 default 目录"""
        assert _artifact_id_candidates("") == []

    def test_path_traversal_filtered_in_candidates(self):
        """路径穿越片段在候选层即被剔除（纵深防御；目录拼接层 _is_safe_segment 还有二次兜底）"""
        assert _artifact_id_candidates("../../etc/passwd") == []


class TestListMergeDedup:
    def test_list_merges_both_dirs_without_duplicate_paths(self, monkeypatch):
        """双口径列表合并：同名产物按 path 去重，不同产物全部保留"""
        import app.strategy.routes.skill_artifacts_router as mod

        def fake_list(job_id, skill_id=None):
            if job_id == "BOSS直聘-recabc123":
                return [{"path": "BOSS直聘-recabc123/resume/a.md", "name": "a.md"}]
            if job_id == "recabc123":
                return [
                    {"path": "recabc123/resume/b.md", "name": "b.md"},
                    # 与异步目录同 path（模拟同一文件被两个口径命中）→ 应被去重
                    {"path": "BOSS直聘-recabc123/resume/a.md", "name": "a.md"},
                ]
            return []

        monkeypatch.setattr(mod, "list_job_skill_artifacts", fake_list, raising=False)
        # 路由内是延迟 import，monkeypatch 需打在 skill_dirs 模块上
        import ai_agents.skills.skill_dirs as dirs
        monkeypatch.setattr(dirs, "list_job_skill_artifacts", fake_list)

        # 直接调用路由函数验证合并结果
        import asyncio
        # asyncio.run：get_event_loop() 在 3.12+ 无隐式建 loop，全量跑会顺序污染（单跑侥幸过）
        resp = asyncio.run(mod.list_skill_artifacts_api("BOSS直聘-recabc123"))
        paths = [a["path"] for a in resp["data"]]
        assert paths == ["BOSS直聘-recabc123/resume/a.md", "recabc123/resume/b.md"]
