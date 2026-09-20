"""批量任务链路 HTTP 路由冒烟测试。

背景：commit 269c286 曾把 `}` 与 `@router.post("/resume")` 粘成一行
（`}@router...`），Python 将其解析为 dict @ function 的矩阵乘法表达式——
装饰器失效导致 /resume 路由丢失 404、auto-heal-and-approve 执行到 return
必抛 TypeError 500。静态语法检查（ast.parse）抓不住这种「合法但错误」形态，
本文件用路由表反射 + TestClient 真实请求做端点级回归防护。
"""
import pytest
from fastapi.testclient import TestClient

import app.automation.routes.delivery_router as delivery_router


EXPECTED_PATHS = [
    "/api/automation/check-job-materials",
    "/api/automation/auto-heal-and-approve",
    "/api/automation/resume",
    "/api/automation/resume_batch",
    "/api/automation/deliver_approved",
]


def test_all_delivery_endpoints_registered():
    """路由表反射：五个端点必须全部注册（防装饰器被吞的粘连事故回归）。"""
    registered = {getattr(r, "path", "") for r in delivery_router.router.routes}
    missing = [p for p in EXPECTED_PATHS if p.rsplit("/", 1)[-1] not in
               {p2.rsplit("/", 1)[-1] for p2 in registered}]
    assert not missing, f"路由表缺失端点（装饰器可能被吞）: {missing}"


def test_no_stuck_decorator_lines():
    """源码扫描：禁止 `右花括号紧跟@装饰器` 形态（粘连装饰器事故的指纹）。"""
    import re
    src = delivery_router.__file__
    with open(src, encoding="utf-8") as f:
        content = f.read()
    stuck = [i + 1 for i, line in enumerate(content.splitlines())
             if re.search(r"[}\]]\s*@\w", line) and "{{" not in line]
    assert not stuck, f"发现右括号与装饰器@粘连行（会导致装饰器变矩阵乘法）: {stuck}"


@pytest.fixture
def client(monkeypatch):
    """构建挂载了 delivery_router 的最小 FastAPI 应用（不依赖整个 main.py 重启动）。"""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(delivery_router.router, prefix="/api/automation")

    async def _fake_async_call(fn, *a, **k):
        """asyncio.to_thread 的替身：直接同步调用（飞书读/写函数本身是同步阻塞实现）。"""
        return fn(*a, **k)

    monkeypatch.setattr(delivery_router.asyncio, "to_thread", _fake_async_call)
    monkeypatch.setattr(delivery_router.feishu_service, "update_feishu_record",
                        lambda record_id, fields, table_id=None: True)
    monkeypatch.setattr(delivery_router, "_mark_approved_guarded", lambda rid: True)
    return TestClient(app)


def test_resume_endpoint_http_ok(client, monkeypatch):
    """单岗位审批 /resume 必须 200 且写「待投递」（曾 404 的事故端点）。"""
    monkeypatch.setattr(delivery_router, "_get_autopilot_config", lambda: {"custom_deliver_mode": "immediate"})
    resp = client.post("/api/automation/resume", json={"thread_id": "BOSS直聘-recTEST", "action": "approve"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] in ("success", "approved", "scheduled")


def test_resume_reject_endpoint_http_ok(client):
    resp = client.post("/api/automation/resume", json={"thread_id": "recTEST", "action": "reject"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected_manual"


def test_resume_batch_endpoint_http_ok(client):
    resp = client.post("/api/automation/resume_batch",
                       json={"thread_ids": ["recT1", "recT2"], "action": "approve"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "success"
    assert data["data"]["success"] == 2


def test_auto_heal_endpoint_returns_dict_not_500(client, monkeypatch):
    """auto-heal 执行到 return 必须返回正常 dict（曾被粘连行变成 500 的事故端点）。

    飞书读取走 404 分支即可覆盖「函数能完整执行并 return dict」这一语义，
    无需真实渲染物料。
    """
    monkeypatch.setattr(delivery_router.feishu_service, "get_job_record_from_feishu",
                        lambda record_id, table_id=None: None)
    resp = client.post("/api/automation/auto-heal-and-approve", json={"record_id": "recTEST"})
    # 记录不存在走 404 业务语义（非 500 崩溃）
    assert resp.status_code == 404, f"auto-heal 应返回 404 业务语义而非崩溃: {resp.status_code} {resp.text}"
