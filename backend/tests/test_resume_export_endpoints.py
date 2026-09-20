from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.jobs.router import UpdateJobResumeRequest, router
from app.main import app

client = TestClient(app)


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
    with patch("app.jobs.action_service.update_job_field", new_callable=AsyncMock) as mock_update:
        mock_update.return_value = {"status": "success", "message": "更新成功"}

        resp = client.put(
            "/api/update_job_resume",
            json={"job_id": "BOSS直聘-rec123", "resume_data": "{\"test\": true}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        mock_update.assert_awaited_once_with(
            "BOSS直聘-rec123",
            {"AI改写JSON": "{\"test\": true}", "跟进状态": "简历人工复核"},
        )


def test_update_job_resume_endpoint_with_record_id():
    with patch("app.jobs.action_service.update_job_field", new_callable=AsyncMock) as mock_update:
        mock_update.return_value = {"status": "success", "message": "更新成功"}

        resp = client.put(
            "/api/update_job_resume",
            json={"record_id": "rec123", "resume_data": "{\"test\": true}"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        mock_update.assert_awaited_once_with(
            "rec123",
            {"AI改写JSON": "{\"test\": true}", "跟进状态": "简历人工复核"},
        )


def test_update_job_resume_endpoint_missing_both_ids():
    resp = client.put(
        "/api/update_job_resume",
        json={"resume_data": "{}"},
    )
    assert resp.status_code == 422
