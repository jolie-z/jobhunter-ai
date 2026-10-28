import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.jobs.router import UpdateJobResumeRequest, router
from app.main import app

client = TestClient(app)

# 非终态飞书记录桩：触发「写入跟进状态=简历人工复核」正常分支
_NON_TERMINAL_REC = {"record_id": "rec123", "fields": {"跟进状态": "新线索"}}
# 终态飞书记录桩：触发终态保护（仅更新物料，不倒流跟进状态）
_TERMINAL_REC = {"record_id": "rec123", "fields": {"跟进状态": "已投递"}}


def _assert_saved_fields(mock_update, expected_target_id: str, *, expect_status_key: bool):
    """结构化断言 update_job_field 入参（2026-10-11 序列化统一后 AI改写JSON 恒为
    indent-2 字符串，字符串精确比对脆弱，一律 json.loads 后比较结构）。"""
    mock_update.assert_awaited_once()
    args = mock_update.await_args.args
    assert args[0] == expected_target_id
    fields = args[1]
    assert json.loads(fields["AI改写JSON"]) == {"test": True}
    if expect_status_key:
        assert fields["跟进状态"] == "简历人工复核"
    else:
        assert "跟进状态" not in fields, "终态岗位严禁倒流跟进状态"


def test_update_job_resume_request_schema_supports_both_ids():
    # 验证 job_id 正常解析
    req1 = UpdateJobResumeRequest.model_validate({"job_id": "test-123", "resume_data": "{}"})
    assert req1.job_id == "test-123"
    assert req1.record_id is None

    # 验证 record_id 兼容解析
    req2 = UpdateJobResumeRequest.model_validate({"record_id": "recABC", "resume_data": "{}"})
    assert req2.record_id == "recABC"
    assert req2.job_id is None


def test_update_job_resume_endpoint_with_job_id():
    with patch("app.jobs.action_service.update_job_field", new_callable=AsyncMock) as mock_update, \
         patch("app.services.feishu_service.get_job_record_from_feishu", return_value=_NON_TERMINAL_REC):
        mock_update.return_value = {"status": "success", "message": "更新成功"}

        resp = client.put(
            "/api/update_job_resume",
            json={"job_id": "BOSS直聘-rec123", "resume_data": "{\"test\": true}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        # 未传 current_status → 查表得非终态 → 物料 + 跟进状态一起写
        _assert_saved_fields(mock_update, "BOSS直聘-rec123", expect_status_key=True)


def test_update_job_resume_endpoint_with_record_id():
    with patch("app.jobs.action_service.update_job_field", new_callable=AsyncMock) as mock_update, \
         patch("app.services.feishu_service.get_job_record_from_feishu", return_value=_NON_TERMINAL_REC):
        mock_update.return_value = {"status": "success", "message": "更新成功"}

        resp = client.put(
            "/api/update_job_resume",
            json={"record_id": "rec123", "resume_data": "{\"test\": true}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        _assert_saved_fields(mock_update, "rec123", expect_status_key=True)


def test_update_job_resume_endpoint_missing_both_ids():
    resp = client.put(
        "/api/update_job_resume",
        json={"resume_data": "{}"},
    )
    assert resp.status_code == 422


def test_update_job_resume_terminal_status_via_passthrough():
    """终态保护（正向）：调用方透传 current_status=已投递 → 仅保存物料，严禁倒流跟进状态。"""
    with patch("app.jobs.action_service.update_job_field", new_callable=AsyncMock) as mock_update, \
         patch("app.services.feishu_service.get_job_record_from_feishu") as mock_lookup:
        mock_update.return_value = {"status": "success", "message": "更新成功"}

        resp = client.put(
            "/api/update_job_resume",
            json={"record_id": "rec123", "resume_data": "{\"test\": true}", "current_status": "已投递"},
        )
        assert resp.status_code == 200
        _assert_saved_fields(mock_update, "rec123", expect_status_key=False)
        mock_lookup.assert_not_called()  # 已透传状态，不额外查表


def test_update_job_resume_terminal_status_via_feishu_lookup():
    """终态保护（负向路径回归锁，2026-10-23 修复）：不透传状态时查表得终态 → 不倒流。

    此前 router.py 误从 feishu_utils 导入 extract_record_id，ImportError 恒中断
    查表 try 块、cur_status 恒空，终态保护形同虚设——本用例锁死查表链路真实生效。
    """
    with patch("app.jobs.action_service.update_job_field", new_callable=AsyncMock) as mock_update, \
         patch("app.services.feishu_service.get_job_record_from_feishu", return_value=_TERMINAL_REC):
        mock_update.return_value = {"status": "success", "message": "更新成功"}

        resp = client.put(
            "/api/update_job_resume",
            json={"record_id": "rec123", "resume_data": "{\"test\": true}"},
        )
        assert resp.status_code == 200
        _assert_saved_fields(mock_update, "rec123", expect_status_key=False)


def test_update_job_resume_lookup_failure_fails_safe_to_review_status():
    """查表异常 fail-safe：物料照存、跟进状态按非终态处理（保持旧行为不回归）。"""
    with patch("app.jobs.action_service.update_job_field", new_callable=AsyncMock) as mock_update, \
         patch("app.services.feishu_service.get_job_record_from_feishu", side_effect=RuntimeError("飞书网关抖动")):
        mock_update.return_value = {"status": "success", "message": "更新成功"}

        resp = client.put(
            "/api/update_job_resume",
            json={"record_id": "rec123", "resume_data": "{\"test\": true}"},
        )
        assert resp.status_code == 200
        _assert_saved_fields(mock_update, "rec123", expect_status_key=True)
