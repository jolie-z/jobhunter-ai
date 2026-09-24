"""简历同步中心配置链统一测试 (test_agent_mapper_config_chain.py)

背景（2026-09-24）：新克隆机器没有 backend/.env 时，简历同步中心报
「飞书简历库不可用：飞书配置缺失」——根因是 agent_mapper.load_env_config
只读 .env 文件，绕过了配置大盘（settings.json）。修复后走
common.config.get_configured_value 统一同源链：
settings.json（配置大盘页面保存）> 环境变量（.env 注入）。

用户目标：克隆仓库 → 前端配置大盘填值 → 简历同步中心直接可用，无需手填 .env。
"""

import json

import pytest

import resume_editor.agent_mapper as am
from resume_editor.agent_mapper import (
    RESUME_SYNC_CONFIG_KEYS,
    _require_feishu_cfg,
    load_env_config,
)


@pytest.fixture
def isolate_settings_json(tmp_path, monkeypatch):
    """settings.json 重定向到临时目录，防测试污染生产配置文件。"""
    fake_path = tmp_path / "settings.json"
    monkeypatch.setattr("common.config.SETTINGS_JSON_PATH", fake_path)
    # 清掉进程内可能已注入的环境变量，模拟「新机器无任何配置」
    for k in RESUME_SYNC_CONFIG_KEYS:
        monkeypatch.delenv(k, raising=False)
    return fake_path


class TestLoadEnvConfigUnifiedChain:
    def test_reads_from_settings_json_first(self, isolate_settings_json):
        """配置大盘保存的值（settings.json）优先生效——新机器无 .env 的核心场景。"""
        isolate_settings_json.write_text(json.dumps({
            "FEISHU_APP_ID": "cli_from_page",
            "FEISHU_APP_TOKEN": "basexxx",
            "FEISHU_TABLE_ID_RESUMES": "tbl_resumes",
        }))
        cfg = load_env_config()
        assert cfg["FEISHU_APP_ID"] == "cli_from_page"
        assert cfg["FEISHU_APP_TOKEN"] == "basexxx"
        assert cfg["FEISHU_TABLE_ID_RESUMES"] == "tbl_resumes"

    def test_env_fallback_when_no_settings_json(self, isolate_settings_json, monkeypatch):
        """settings.json 没有时回落环境变量（.env 注入的旧机器场景不受影响）。"""
        monkeypatch.setenv("FEISHU_APP_ID", "cli_from_env")
        cfg = load_env_config()
        assert cfg.get("FEISHU_APP_ID") == "cli_from_env"

    def test_settings_json_wins_over_env(self, isolate_settings_json, monkeypatch):
        """同键两处都有值：settings.json > 环境变量（全仓统一优先级）。"""
        monkeypatch.setenv("FEISHU_APP_ID", "cli_from_env")
        isolate_settings_json.write_text(json.dumps({"FEISHU_APP_ID": "cli_from_page"}))
        cfg = load_env_config()
        assert cfg["FEISHU_APP_ID"] == "cli_from_page"

    def test_empty_values_dropped(self, isolate_settings_json):
        """空值/纯空白键从结果 dict 剔除：保住消费方 cfg.get(key, default) 的默认值语义
        （键存在但值为空会吞掉 OPENAI_MODEL 的 'gpt-4o-mini' 默认）；
        纯空格值单独覆盖 strip 过滤路径。"""
        isolate_settings_json.write_text(json.dumps({
            "OPENAI_MODEL": "", "OPENAI_BASE_URL": "   ", "OPENAI_API_KEY": "sk-x",
        }))
        cfg = load_env_config()
        assert "OPENAI_MODEL" not in cfg
        assert "OPENAI_BASE_URL" not in cfg  # 纯空格：strip 过滤路径
        assert cfg.get("OPENAI_MODEL", "gpt-4o-mini") == "gpt-4o-mini"
        assert cfg["OPENAI_API_KEY"] == "sk-x"

    def test_base_url_normalized(self, isolate_settings_json):
        """OPENAI_BASE_URL 写成完整请求路径时归一化回基址（旧行为保持）。"""
        isolate_settings_json.write_text(json.dumps({
            "OPENAI_BASE_URL": "https://api.example.com/v1/chat/completions",
        }))
        cfg = load_env_config()
        assert cfg["OPENAI_BASE_URL"] == "https://api.example.com/v1"

    def test_no_config_at_all(self, isolate_settings_json):
        """全新机器零配置：返回空 dict 而非报错（报错留给 _require_feishu_cfg 层）。"""
        assert load_env_config() == {}


class TestRequireFeishuCfg:
    def test_error_message_guides_to_config_page(self):
        """未配置时报错文案带「配置大盘」指引，新用户照着报错即可操作。"""
        with pytest.raises(RuntimeError) as exc_info:
            _require_feishu_cfg({})
        msg = str(exc_info.value)
        assert "配置大盘" in msg
        assert "FEISHU_APP_ID" in msg

    def test_error_lists_only_missing_keys(self):
        """只缺部分键时，报错仅指缺的那几个（全配齐则不报错）。"""
        partial = {"FEISHU_APP_ID": "cli_x", "FEISHU_APP_TOKEN": "base_x"}
        with pytest.raises(RuntimeError) as exc_info:
            _require_feishu_cfg(partial)
        msg = str(exc_info.value)
        assert "FEISHU_TABLE_ID_RESUMES" in msg
        # 已配置的键不该出现在缺失清单里
        assert "FEISHU_APP_ID" not in msg
        assert "FEISHU_APP_TOKEN" not in msg

        _require_feishu_cfg({**partial, "FEISHU_TABLE_ID_RESUMES": "tbl_x"})  # 不抛


class TestListFeishuResumesIntegration:
    def test_list_feishu_resumes_missing_config_no_crash(self, isolate_settings_json):
        """端到端：零配置新机器调用简历库列表接口，返回 ok=False + 指引文案（不抛异常）。"""
        result = am.list_feishu_resumes()
        assert result["ok"] is False
        assert result["resumes"] == []
        assert "配置大盘" in result["message"]
