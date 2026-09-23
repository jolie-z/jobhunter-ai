"""check-ai-artifacts 端点冒烟测试（重复发起 AI 任务二次确认门禁的后端补查口）。

主页列表接口裁掉了大文本字段（record_normalizer.DETAIL_ONLY_FIELDS），前端列表数据
判断不了深评/改写/打招呼语是否已存在；本端点按记录回源飞书补查三布尔。
测试聚焦：路由注册、复合 ID 解析、三布尔判定口径、单条读取失败软降级（全 False 不阻断）。
"""
import pytest
from fastapi.testclient import TestClient

import app.jobs.router as jobs_router
from app.services import feishu_service


EXPECTED_PATH = "/api/jobs/check-ai-artifacts"


def test_check_ai_artifacts_registered():
    """路由表反射：端点必须注册（防装饰器被吞的粘连事故回归）。"""
    registered = {getattr(r, "path", "") for r in jobs_router.router.routes}
    assert EXPECTED_PATH in registered


@pytest.fixture
def client(monkeypatch):
    """构建挂载了 jobs_router 的最小 FastAPI 应用（不依赖整个 main.py 重启动）。"""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(jobs_router.router)

    def _fake_record(record_id, table_id):
        # recHIT：深评命中（高杠杆匹配点非空）；recRW：改写命中；recCT：打招呼语命中
        return {
            "fields": {
                "高杠杆匹配点": "强匹配信号" if record_id == "recHIT" else "",
                "AI改写JSON": "已改写内容" if record_id == "recRW" else "",
                "打招呼语": "您好" if record_id == "recCT" else "",
            }
        }

    monkeypatch.setattr(feishu_service, "get_job_record_from_feishu", _fake_record)
    return TestClient(app)


def test_check_ai_artifacts_http_ok_and_verdicts(client):
    resp = client.post(
        EXPECTED_PATH,
        json={"record_ids": ["recHIT", "智联招聘-recRW", "recCT", "recCLEAN"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    data = body["data"]
    # 复合 ID 解析为纯 record_id 作 key
    assert set(data.keys()) == {"recHIT", "recRW", "recCT", "recCLEAN"}
    assert data["recHIT"]["has_deep_eval"] is True
    assert data["recRW"]["has_rewrite"] is True
    assert data["recCT"]["has_greeting"] is True
    for flag in ("has_deep_eval", "has_rewrite", "has_greeting"):
        assert data["recCLEAN"][flag] is False


def test_check_ai_artifacts_soft_fail_on_read_error(client, monkeypatch):
    """单条读取失败按无产物（全 False）返回，不阻断批量派发前的门禁预检。"""

    def _boom(record_id, table_id):
        return None

    monkeypatch.setattr(feishu_service, "get_job_record_from_feishu", _boom)
    resp = client.post(EXPECTED_PATH, json={"record_ids": ["recGONE"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["recGONE"] == {
        "has_deep_eval": False,
        "has_rewrite": False,
        "has_greeting": False,
    }


def test_check_ai_artifacts_soft_fail_on_raised_exception(client, monkeypatch):
    """读取函数直接抛异常（网络断/SDK 升级等）同样按全 False 软降级，整批不 500。"""

    def _explode(record_id, table_id):
        raise RuntimeError("feishu sdk exploded")

    monkeypatch.setattr(feishu_service, "get_job_record_from_feishu", _explode)
    resp = client.post(EXPECTED_PATH, json={"record_ids": ["recOK", "recBAD"]})
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["recBAD"] == {"has_deep_eval": False, "has_rewrite": False, "has_greeting": False}
    assert data["recOK"] == {"has_deep_eval": False, "has_rewrite": False, "has_greeting": False}


def test_check_ai_artifacts_rejects_empty_ids(client):
    resp = client.post(EXPECTED_PATH, json={"record_ids": []})
    assert resp.status_code == 422
