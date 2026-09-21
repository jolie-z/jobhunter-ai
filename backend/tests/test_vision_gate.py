"""视觉模型前置闸门测试：带图请求在未配置视觉模型时 fail-fast 为结构化 400。

注意：本文件不起 TestClient（lifespan 会启动 APScheduler 并绑定事件循环，
先于 tests/api 执行会引爆 test_automation 的 loop-closed 顺序污染），
路由层断言直调 router 协程捕获 HTTPException。
"""
import pytest
from fastapi import HTTPException

_FAKE_B64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def test_images_blocked_when_vision_missing(monkeypatch):
    """带图 + 视觉未配置 → VisionNotConfiguredError（带缺失键列表）。"""
    from app.jobs.import_parser import VisionNotConfiguredError, parse_job_from_sources

    monkeypatch.setattr("common.config.get_missing_vision_keys", lambda: ["VISION_MODEL"])

    import asyncio
    with pytest.raises(VisionNotConfiguredError) as exc_info:
        asyncio.run(parse_job_from_sources(raw_text="", images_base64=[_FAKE_B64]))
    assert exc_info.value.missing == ["VISION_MODEL"]


def test_text_only_not_blocked_when_vision_missing(monkeypatch):
    """纯文本请求不受视觉闸门影响（mock 文本解析器，不触达 LLM）。"""
    from app.jobs import import_parser
    from app.jobs.import_parser import parse_job_from_sources

    monkeypatch.setattr("common.config.get_missing_vision_keys", lambda: ["VISION_MODEL"])
    monkeypatch.setattr(
        import_parser,
        "_parse_fields_by_text",
        lambda raw_text, url="", platform="未知": {"公司名称": "测试公司", "岗位名称": "测试岗"},
    )

    import asyncio
    fields = asyncio.run(parse_job_from_sources(raw_text="测试公司招聘测试岗，薪资 20K", images_base64=None))
    assert fields["公司名称"] == "测试公司"


def test_images_pass_when_vision_ready(monkeypatch):
    """视觉就绪时闸门放行（mock 视觉解析器，不触达 LLM）。"""
    from app.jobs import import_parser
    from app.jobs.import_parser import parse_job_from_sources

    monkeypatch.setattr("common.config.get_missing_vision_keys", lambda: [])
    monkeypatch.setattr(
        import_parser,
        "_parse_fields_by_vision",
        lambda images: {"公司名称": "图解公司", "岗位名称": "视觉岗"},
    )

    import asyncio
    fields = asyncio.run(parse_job_from_sources(raw_text="", images_base64=[_FAKE_B64]))
    assert fields["公司名称"] == "图解公司"


def test_parse_router_structured_400(monkeypatch):
    """路由层：带图请求在视觉未配置时转换为 400 + detail.code=vision_not_configured。"""
    from app.jobs.router import parse_import_payload
    from app.jobs.schemas import JobImportParseRequest

    monkeypatch.setattr("common.config.get_missing_vision_keys", lambda: ["VISION_MODEL", "OPENAI_API_KEY"])

    import asyncio
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(parse_import_payload(JobImportParseRequest(raw_text="", images_base64=[_FAKE_B64])))
    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert detail["code"] == "vision_not_configured"
    assert detail["missing"] == ["VISION_MODEL", "OPENAI_API_KEY"]


def test_images_service_passes_gate_through(monkeypatch):
    """旧一步式图片服务：闸门异常从 parse 冒泡透传（不经 mock 即可验证）。"""
    from app.jobs import service

    monkeypatch.setattr("common.config.get_missing_vision_keys", lambda: ["VISION_MODEL"])

    import asyncio
    with pytest.raises(service.VisionNotConfiguredError):
        asyncio.run(service.import_job_from_images_service([_FAKE_B64]))
