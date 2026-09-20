"""老板手动拒绝（已拒绝门牌）回归测试。

覆盖 2026-08-28 修复：
- 拒绝动作此前是幽灵操作（后端不落库、看板卡片 6 秒弹回待审批）；
- 现约定：拒绝 → 飞书跟进状态写「已拒绝」（AI 草稿保留），快照归类为 rejected_manual，
  不进淘汰 Tab（淘汰 Tab 仅机器清洗）、不进待审批 Tab，仅保留在全部岗位列表。
"""
from pathlib import Path

import pytest

import app.automation.router as automation_router
import app.services.feishu_service as feishu_service

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
async def test_resume_reject_writes_feishu_status(monkeypatch):
    """单个拒绝：飞书跟进状态必须落库为「已拒绝」，接口返回 rejected_manual。"""
    captured = {}

    def _fake_update(rid, updates):
        captured[rid] = updates
        return True  # 接口在 34690da 后校验写库结果，mock 必须模拟成功

    monkeypatch.setattr(feishu_service, "update_feishu_record", _fake_update)
    result = await automation_router.resume_workflow(
        automation_router.ResumeRequest(thread_id="rec_reject_1", action="reject")
    )
    assert result["status"] == "rejected_manual"
    assert captured == {"rec_reject_1": {"跟进状态": "已拒绝"}}


@pytest.mark.asyncio
async def test_resume_batch_reject_writes_feishu_status(monkeypatch):
    """批量拒绝：每个岗位都落库「已拒绝」。"""
    captured = {}

    def _fake_update(rid, updates):
        captured[rid] = updates
        return True  # 接口在 34690da 后校验写库结果，mock 必须模拟成功

    monkeypatch.setattr(feishu_service, "update_feishu_record", _fake_update)
    result = await automation_router.resume_workflow_batch(
        automation_router.ResumeBatchRequest(thread_ids=["rec_r1", "rec_r2"], action="reject")
    )
    assert result["status"] == "success"
    assert set(captured) == {"rec_r1", "rec_r2"}
    assert all(u == {"跟进状态": "已拒绝"} for u in captured.values())
    assert all(d["status"] == "rejected_manual" for d in result["data"]["details"])


def test_manual_rejected_query_filters_by_status(monkeypatch):
    """已拒绝查询：过滤条件必须是跟进状态=已拒绝，并回传 follow_status。"""
    class _FakeResp:
        def json(self):
            return {
                "code": 0,
                "data": {
                    "items": [{
                        "record_id": "rec9",
                        "fields": {
                            "岗位名称": [{"text": "测试岗"}],
                            "公司名称": [{"text": "测试公司"}],
                            "跟进状态": "已拒绝",
                        },
                    }],
                    "has_more": False,
                },
            }

    captured = {}
    monkeypatch.setattr(feishu_service, "get_tenant_access_token", lambda: "token")

    def _fake_request(_method, _url, **kw):
        captured["payload"] = kw.get("json")
        return _FakeResp()

    monkeypatch.setattr(feishu_service, "safe_feishu_request", _fake_request)

    jobs = feishu_service.get_manual_rejected_jobs_from_feishu()
    assert captured["payload"]["filter"]["conditions"][0]["value"] == ["已拒绝"]
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "rec9"
    assert jobs[0]["follow_status"] == "已拒绝"


def test_rejected_manual_contract():
    """契约冻结：rejected_manual 不得混入淘汰 Tab 收货清单；后端口径必须统一。

    前端谓词 (job-predicates.ts) 无 Python 单测基建，用源码常量断言守住边界：
    rejected_manual 一旦进入 JOB_STATUS_SETS.REJECTED，老板拒绝就会污染机器清洗淘汰区。

    2026-09-12：be5e61a 将门面层拆分为模块化子路由，口径断言随实现迁移到
    routes/delivery_router.py（拒绝接口）与 snapshot_service.py（快照归类）。
    """
    predicates = (_REPO_ROOT / "frontend/components/command-center/job-predicates.ts").read_text(encoding="utf-8")
    assert '"rejected_manual"' not in predicates

    delivery = (_REPO_ROOT / "backend/app/automation/routes/delivery_router.py").read_text(encoding="utf-8")
    assert delivery.count('"rejected_manual"') >= 2, "单岗/批量拒绝接口必须持续使用统一的 rejected_manual 口径"
    assert delivery.count('"已拒绝"') >= 2, "单岗/批量拒绝落库必须同步认识「已拒绝」门牌"

    snapshot = (_REPO_ROOT / "backend/app/automation/snapshot_service.py").read_text(encoding="utf-8")
    assert snapshot.count('"rejected_manual"') >= 1, "快照归类必须使用统一的 rejected_manual 口径"
    assert snapshot.count('"已拒绝"') >= 1, "快照查询必须同步认识「已拒绝」门牌"
