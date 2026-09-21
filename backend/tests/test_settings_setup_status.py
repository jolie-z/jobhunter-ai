"""新手引导配置体检聚合端点测试（GET /api/settings/setup-status）。

全部 mock 配置读取与下游判定，不碰网络与真实 settings.json。
注意：被测模块一律在用例内 import——本文件若在 collection 期 import app.*，
会改变全量回归的全局初始化顺序（test_automation 的 scheduler loop 绑定已被实证波及）。
"""
import pytest

EXPECTED_MIN_KEYS = {
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
    "FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN",
    "FEISHU_TABLE_ID_JOBS", "FEISHU_TABLE_ID_RESUMES",
}


def _patch_pipeline(monkeypatch, modules: dict, all_configured: bool):
    """mock 指挥中心 9 模块判定（setup_status 在函数内延迟 import）。"""
    from app.pipeline.routes import feishu_status_router

    monkeypatch.setattr(
        feishu_status_router,
        "config_status",
        lambda: {"code": 0, "data": {"modules": modules, "all_configured": all_configured}},
    )


def test_base_fields_cover_exactly_eight_minimal_keys():
    from app.settings import setup_status

    keys = set(setup_status._FIELD_LABELS)
    assert keys == EXPECTED_MIN_KEYS


def test_all_configured(monkeypatch):
    from app.settings import setup_status

    monkeypatch.setattr(setup_status, "get_configured_value", lambda key: "fake-value")
    monkeypatch.setattr(setup_status, "_resume_exists", lambda: True)
    _patch_pipeline(monkeypatch, {"scraping": True, "cleaning": False}, all_configured=False)

    import asyncio
    data = asyncio.run(setup_status.get_setup_status())["data"]

    assert data["base"]["done"] is True
    assert data["resume"]["done"] is True
    assert data["pipeline"]["done"] is False  # 跟随 mock 值
    assert data["complete"] is True  # complete = base && resume，pipeline 不阻塞
    assert len(data["base"]["fields"]) == 8
    assert all(f["filled"] for f in data["base"]["fields"])
    # 展示归属：LLM 组 3 项 + 飞书组 5 项
    assert sum(1 for f in data["base"]["fields"] if f["group"] == "LLM 大模型") == 3
    assert sum(1 for f in data["base"]["fields"] if f["group"] == "飞书") == 5


def test_missing_fields_and_resume(monkeypatch):
    from app.settings import setup_status

    values = {key: "" for key in EXPECTED_MIN_KEYS}
    values["OPENAI_API_KEY"] = "sk-xxx"
    values["FEISHU_APP_ID"] = "cli_xxx"
    monkeypatch.setattr(setup_status, "get_configured_value", lambda key: values.get(key, ""))
    monkeypatch.setattr(setup_status, "_resume_exists", lambda: False)
    monkeypatch.setattr(setup_status, "get_missing_vision_keys", lambda: ["VISION_MODEL"])
    _patch_pipeline(monkeypatch, {}, all_configured=False)

    import asyncio
    data = asyncio.run(setup_status.get_setup_status())["data"]

    assert data["base"]["done"] is False
    assert data["resume"]["done"] is False
    assert data["complete"] is False
    assert data["vision_ready"] is False
    filled = {f["key"]: f["filled"] for f in data["base"]["fields"]}
    assert filled["OPENAI_API_KEY"] is True
    assert filled["FEISHU_APP_ID"] is True
    assert filled["OPENAI_BASE_URL"] is False
    assert filled["FEISHU_TABLE_ID_RESUMES"] is False


def test_pipeline_exception_fails_open(monkeypatch):
    """config_status 抛错时体检不炸，pipeline 按未配置处理。"""
    from app.settings import setup_status

    monkeypatch.setattr(setup_status, "get_configured_value", lambda key: "v")
    monkeypatch.setattr(setup_status, "_resume_exists", lambda: True)
    from app.pipeline.routes import feishu_status_router

    def _boom():
        raise RuntimeError("db gone")

    monkeypatch.setattr(feishu_status_router, "config_status", _boom)

    import asyncio
    data = asyncio.run(setup_status.get_setup_status())["data"]

    assert data["base"]["done"] is True
    assert data["complete"] is True
    assert data["pipeline"]["done"] is False
