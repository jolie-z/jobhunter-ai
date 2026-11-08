"""配置页「眼睛」按需读取完整密钥：只允许敏感键，且返回明文。"""
import asyncio

import pytest

from app.settings import service


def _run(coro):
    return asyncio.run(coro)


def test_reveal_sensitive_setting_returns_plaintext(monkeypatch):
    monkeypatch.setattr(service._config_module, "_cfg", lambda *args, **kwargs: "sk-full-secret-value")

    result = _run(service.reveal_system_setting("OPENAI_API_KEY"))

    assert result == {
        "code": 0,
        "data": {"key": "OPENAI_API_KEY", "value": "sk-full-secret-value"},
    }


def test_reveal_feishu_secret_is_allowed(monkeypatch):
    monkeypatch.setattr(service._config_module, "_cfg", lambda *args, **kwargs: "feishu-secret")

    result = _run(service.reveal_system_setting("FEISHU_APP_SECRET"))

    assert result["data"]["value"] == "feishu-secret"


def test_reveal_missing_value_returns_empty_string(monkeypatch):
    monkeypatch.setattr(service._config_module, "_cfg", lambda *args, **kwargs: None)

    result = _run(service.reveal_system_setting("BOCHA_API_KEY"))

    assert result["data"]["value"] == ""


@pytest.mark.parametrize("key", ["OPENAI_BASE_URL", "OPENAI_MODEL", "FEISHU_TABLE_ID_JOBS"])
def test_reveal_rejects_non_sensitive_keys(key):
    with pytest.raises(KeyError):
        _run(service.reveal_system_setting(key))


@pytest.mark.parametrize("key", ["PATH", "SECRET_TOKEN", ""])
def test_reveal_rejects_unknown_keys(key):
    with pytest.raises(KeyError):
        _run(service.reveal_system_setting(key))
