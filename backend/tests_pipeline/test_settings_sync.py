"""settings.json → 运行时桥接（sync_settings_to_runtime）单测。

覆盖开源用户的核心路径：只在页面上填配置（不写 .env）时，
os.environ 与 pydantic settings 单例都能拿到页面保存的值，且 settings.json 优先级高于 .env。
"""
import json
import os

import common.config as cc


def _seed(fake_data: dict, tmp_path, monkeypatch, env_keys=()):
    fake = tmp_path / "settings.json"
    fake.write_text(json.dumps(fake_data), encoding="utf-8")
    monkeypatch.setattr(cc, "SETTINGS_JSON_PATH", fake)
    for k in env_keys:
        monkeypatch.setenv(k, "seed-old-value")  # 预占位，teardown 时由 monkeypatch 还原
    from app.core.config import settings as pyd_settings, Settings
    valid_fields = set(Settings.model_fields.keys())
    for k in fake_data:
        if k in valid_fields:
            monkeypatch.setattr(pyd_settings, k, "seed-old-value", raising=False)


def test_sync_injects_env_and_pydantic(tmp_path, monkeypatch):
    _seed(
        {
            "FEISHU_APP_ID": "cli_test123456",
            "OPENAI_MODEL": "test-model-x",
            # 非 pydantic 字段也应进 os.environ（供 os.getenv 消费方读取）
            "USE_MAIN_LLM_FOR_CLEANER": "true",
        },
        tmp_path,
        monkeypatch,
        env_keys=("FEISHU_APP_ID", "OPENAI_MODEL", "USE_MAIN_LLM_FOR_CLEANER"),
    )

    injected = cc.sync_settings_to_runtime()

    assert injected >= 3
    assert os.environ["FEISHU_APP_ID"] == "cli_test123456"
    assert os.environ["USE_MAIN_LLM_FOR_CLEANER"] == "true"
    from app.core.config import settings as pyd_settings
    assert pyd_settings.FEISHU_APP_ID == "cli_test123456"
    assert pyd_settings.OPENAI_MODEL == "test-model-x"


def test_sync_priority_settings_json_over_env(tmp_path, monkeypatch):
    _seed({"OPENAI_MODEL": "from-json"}, tmp_path, monkeypatch, env_keys=("OPENAI_MODEL",))

    cc.sync_settings_to_runtime()

    # settings.json（页面配置）覆盖 .env —— 与文档承诺的优先级一致
    assert os.environ["OPENAI_MODEL"] == "from-json"
    from app.core.config import settings as pyd_settings
    assert pyd_settings.OPENAI_MODEL == "from-json"


def test_sync_skips_empty_values(tmp_path, monkeypatch):
    _seed({"OPENAI_BASE_URL": "  ", "FEISHU_APP_TOKEN": ""}, tmp_path, monkeypatch)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    cc.sync_settings_to_runtime()

    assert "OPENAI_BASE_URL" not in os.environ or os.environ["OPENAI_BASE_URL"] != "  "


def test_tool_meta_covers_all_chat_tools():
    """前端指令话术目录以后端 TOOL_META 为真源：注册的每个工具都必须有话术元数据。"""
    from app.services.chat_agent.tools import CHAT_TOOLS, TOOL_META

    tool_names = {t.name for t in CHAT_TOOLS}
    assert tool_names == set(TOOL_META.keys()), (
        f"CHAT_TOOLS 与 TOOL_META 不同步：缺元数据={tool_names - set(TOOL_META.keys())}，"
        f"多余元数据={set(TOOL_META.keys()) - tool_names}"
    )
    for name, meta in TOOL_META.items():
        assert meta.get("category"), f"工具 {name} 缺 category"
        assert meta.get("desc"), f"工具 {name} 缺 desc"
        assert meta.get("phrases"), f"工具 {name} 缺 phrases"


def test_diag_tables_match_config_groups():
    """诊断服务检查的表清单必须与配置分组里的飞书表字段一致，防止两处漂移。"""
    from app.settings.diagnostics import _TABLE_KEYS
    from app.settings.service import CONFIG_GROUPS

    feishu_group = dict(CONFIG_GROUPS)["飞书"]
    group_table_keys = {k for k, _, _ in feishu_group if k.startswith("FEISHU_TABLE_ID")}
    diag_keys = {k for k, _ in _TABLE_KEYS}
    assert group_table_keys == diag_keys


def test_delete_keys_falls_back_to_dotenv(tmp_path, monkeypatch):
    """页面「清除」语义：键从 settings.json 删除后，环境变量与 pydantic 单例回落 .env 值。

    用 AMAP_BASE_URL（不在保存钩子名单里）：避免单测触发 ChatAgent 重建
    （langchain 全家桶 + 与活服务共用的 checkpoint SQLite，曾把测试挂死）。
    """
    import os
    import json as _json

    fake_dir = tmp_path / "common" / "data"
    fake_dir.mkdir(parents=True)
    fake_json = fake_dir / "settings.json"
    fake_json.write_text(_json.dumps({"AMAP_BASE_URL": "https://bad.example.com/geo"}), encoding="utf-8")
    # 模拟 backend/.env（fake json 路径向上两级即其所在 .env）
    (tmp_path / ".env").write_text("AMAP_BASE_URL=https://dotenv.example.com/geo\n", encoding="utf-8")

    monkeypatch.setattr(cc, "SETTINGS_JSON_PATH", fake_json)
    # save() 内部会 reload common.config（会把真实 SETTINGS_JSON_PATH 带回来），
    # 测试中打桩为 no-op；后续回落由 save() 内的 load_dotenv + 显式 sync 完成
    import importlib as _importlib
    monkeypatch.setattr(_importlib, "reload", lambda m: None)

    from app.settings import service as svc
    monkeypatch.setattr(svc, "SETTINGS_DATA_PATH", fake_json)

    # 预置「页面注入过坏值」的运行时状态
    monkeypatch.setenv("AMAP_BASE_URL", "https://bad.example.com/geo")
    from app.core.config import settings as pyd_settings
    monkeypatch.setattr(pyd_settings, "AMAP_BASE_URL", "https://bad.example.com/geo")

    import asyncio
    from app.settings.schemas import SettingsPayload

    async def run():
        return await svc.save_system_settings(SettingsPayload(**{"__delete__": ["AMAP_BASE_URL"]}))

    result = asyncio.run(run())

    assert result["deleted"] == ["AMAP_BASE_URL"]
    # 1) json 里已删除
    assert "AMAP_BASE_URL" not in _json.loads(fake_json.read_text(encoding="utf-8"))
    # 2) 环境变量回落 .env 值
    assert os.environ["AMAP_BASE_URL"] == "https://dotenv.example.com/geo"
    # 3) pydantic 单例同步回落
    assert pyd_settings.AMAP_BASE_URL == "https://dotenv.example.com/geo"


def test_delete_rejects_unknown_keys(tmp_path, monkeypatch):
    """清除只认配置分组里声明过的键，防止误删任意环境变量。"""
    import json as _json
    from app.settings import service as svc
    from app.settings.schemas import SettingsPayload

    fake_json = tmp_path / "settings.json"
    fake_json.write_text(_json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(svc, "SETTINGS_DATA_PATH", fake_json)
    import importlib as _importlib
    monkeypatch.setattr(_importlib, "reload", lambda m: None)  # 打桩防真实 reload 泄漏
    monkeypatch.setattr(svc._config_module, "sync_settings_to_runtime", lambda reset_keys=None: 0)

    result = asyncio.run(svc.save_system_settings(SettingsPayload(**{"__delete__": ["PATH", "NOT_A_KEY"]})) )

    assert result["deleted"] == []
    assert _json.loads(fake_json.read_text(encoding="utf-8")) == {}


import asyncio  # noqa: E402  供上方 async 测试使用
