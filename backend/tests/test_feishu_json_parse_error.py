"""飞书响应 JSON 解析失败的可取证性测试（2026-10-28 诊断三层改造第一层）。

背景：简历库保存报 `Extra data: line 1 column 5 (char 4)` 却无法取证——用户填错
数据表 ID 时飞书网关回了非 JSON body，resp.json() 的裸 JSONDecodeError 只进了
500 detail，原始响应体从未落任何日志，事后永久不可追溯。本组测试锁定：
1. parse_feishu_json 失败时 ValueError 带 HTTP 状态码 + body 前 200 字节快照
2. 非 UTF-8 异常 body（网关/代理篡改）不在此二次抛 UnicodeDecodeError
3. 合法 JSON 原样透传（零行为变化）
4. /api/strategy/save 路由：异常转 500 detail 透传 + logger.exception 落盘（traceback 进 shell.log）
"""
import json
import logging
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.feishu_utils import parse_feishu_json
from app.strategy.routes import rules_router


def _resp(body: bytes, status_code: int = 200):
    """构造 duck-typed 响应对象（httpx/requests 均有 .json/.status_code/.content 同形接口）"""
    return SimpleNamespace(
        status_code=status_code,
        content=body,
        json=lambda: json.loads(body.decode("utf-8")),
    )


def test_parse_failure_raises_with_status_and_body_snapshot():
    resp = _resp(b'null{"code":0}', status_code=502)
    try:
        parse_feishu_json(resp, "保存简历")
        raised = None
    except ValueError as e:
        raised = str(e)
    assert raised is not None
    assert "保存简历" in raised
    assert "HTTP 502" in raised
    assert 'null{"code":0}' in raised  # body 快照必须可见——这正是本次无法追溯的根因


def test_parse_failure_snapshot_long_body_truncated_to_200_bytes():
    resp = _resp(b"x" * 500)
    try:
        parse_feishu_json(resp, "删除简历")
        raised = None
    except ValueError as e:
        raised = str(e)
    assert raised is not None
    assert len(raised) < 500  # 快照截断，弹窗文案不被超长 body 撑爆


def test_parse_failure_non_utf8_body_no_secondary_raise():
    """非 UTF-8 异常流：容错解码出替换符，绝不抛 UnicodeDecodeError 掩盖原始现场"""
    resp = _resp(b"\xff\xfe\xfa" + b'{"a":1}', status_code=200)
    try:
        parse_feishu_json(resp, "查询生效简历")
        raised = None
    except UnicodeDecodeError:
        raised = "UnicodeDecodeError leaked"
    except ValueError as e:
        raised = str(e)
    assert raised is not None and raised != "UnicodeDecodeError leaked"
    assert "HTTP 200" in raised


def test_valid_json_passes_through_unchanged():
    resp = _resp(b'{"code":0,"data":{"record":{"record_id":"rec123"}}}')
    assert parse_feishu_json(resp, "保存简历")["data"]["record"]["record_id"] == "rec123"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(rules_router.router, prefix="/api/strategy")
    return TestClient(app)


def test_save_route_500_detail_passthrough_and_exception_logged(caplog):
    """路由 catch：traceback 落 logger（shell.log 可见）+ 原始异常文案透传给弹窗 detail"""

    async def _boom(payload):
        raise ValueError("保存简历响应非JSON（HTTP 200）: 'null{\"x\":1}'")

    import app.strategy.service as service_module

    original = service_module.save_strategy_config_service
    service_module.save_strategy_config_service = _boom
    try:
        with caplog.at_level(logging.ERROR, logger="strategy_rules_router"):
            resp = _client().post(
                "/api/strategy/save",
                json={"table_type": "resume", "fields": {"简历版本": "t"}},
            )
    finally:
        service_module.save_strategy_config_service = original

    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert detail.startswith("处理保存请求时出错: ")
    assert "HTTP 200" in detail  # helper 的现场快照穿透到弹窗 detail
    assert any("save_strategy_config" in r.message for r in caplog.records)  # traceback 落盘
