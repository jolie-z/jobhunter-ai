"""Q17 防误触发守卫回归（质检批次3）。

POST /api/automation/trigger 原先无请求体校验，空参 POST 即启动真实全自动流水线
（抓取→评估→投递不可逆动作面）。守卫落地后：
- 空 body → 422（FastAPI 缺体校验）；confirm 缺省或 false → 400；仅 {"confirm": true} 放行
- 仅 {"confirm": true} 才放行（放行路径的全链路行为由既有集成用例与真机抽样覆盖，
  本文件不重复拉起流水线，避免测试期真实副作用）
"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402

client = TestClient(app)


def test_trigger_without_body_rejected():
    """空 body（原第4层冒烟事故形态）必须被拒：FastAPI 对缺失 body 返回 422，同样 fail-closed。"""
    resp = client.post("/api/automation/trigger")
    assert resp.status_code == 422


def test_trigger_without_confirm_rejected():
    """显式 JSON 但未确认 → 400。"""
    resp = client.post("/api/automation/trigger", json={})
    assert resp.status_code == 400
    assert "confirm" in resp.json()["detail"]


def test_trigger_confirm_false_rejected():
    """confirm=false → 400。"""
    resp = client.post("/api/automation/trigger", json={"confirm": False})
    assert resp.status_code == 400
    assert "confirm" in resp.json()["detail"]


def test_trigger_with_confirm_approved(monkeypatch):
    """confirm=true 正向放行契约：200 + pipeline_task_id（流水线本体 mock，零真实副作用）。"""
    from unittest.mock import patch
    import app.automation.full_auto as fa

    with patch.object(fa, "run_full_auto_pipeline", return_value="pipeline_guard_test"):
        resp = client.post("/api/automation/trigger", json={"confirm": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["pipeline_task_id"] == "pipeline_guard_test"
