"""config_status 判定体下沉(config_status_service)的搬移等价性测试。

背景（2026-09-26 新机体验小批）：判定体自 feishu_status_router.py 下沉到
app/pipeline/config_status_service.py（CLI 体检脚本与 Router 统一消费），
Router 保留同名薄壳。本组测试锁定：
1. 返回结构（code/data/modules/required_keys）与全 9 键不丢
2. Router 薄壳输出与 service 输出一致（同一进程同状态）
3. example 模板纯 JSON 合法且键集合 == CONFIG_GROUPS 展开（settings.json.example
   不含注释，复制即用不炸 json.load）
"""
import json
import os

from app.pipeline import config_status_service
from app.pipeline.routes import feishu_status_router

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUIRED_NINE = [
    "scraping", "cleaning", "feishu_sync", "evaluating",
    "deep_eval", "rewriting", "greeting", "review", "delivering",
]


def test_service_returns_full_structure():
    result = config_status_service.compute_config_status()
    assert result["code"] == 0
    data = result["data"]
    assert set(data["modules"].keys()) == set(REQUIRED_NINE)
    assert data["required_keys"] == [k for k in REQUIRED_NINE if k != "deep_eval"]
    assert isinstance(data["all_configured"], bool)
    # 8 个必填项里 deep_eval 默认就绪，其余必须有布尔值
    assert all(isinstance(v, bool) for v in data["modules"].values())


def test_router_shim_delegates_to_service():
    """薄壳与 service 同源：同一进程状态下两次调用结果一致。"""
    shim = feishu_status_router.config_status()
    direct = config_status_service.compute_config_status()
    assert shim == direct


def test_router_module_reexports_preserved():
    """setup_status.py / pipeline/router.py / monkeypatch 的既有 import 路径不变。"""
    assert hasattr(feishu_status_router, "_get_active_resume_meta_cached")
    assert hasattr(feishu_status_router, "invalidate_active_resume_meta_cache")
    assert hasattr(feishu_status_router, "DB_PATH")
    assert hasattr(feishu_status_router, "AUTOPILOT_DB")
    # 路径仍指向 backend/data/job_hunter.db（dirname 层数随文件位置同步调整过）
    assert feishu_status_router.DB_PATH.endswith(os.path.join("data", "job_hunter.db"))
    assert config_status_service.DB_PATH == feishu_status_router.DB_PATH
    assert config_status_service.AUTOPILOT_DB == feishu_status_router.AUTOPILOT_DB


def test_settings_example_is_valid_json_with_exact_key_set():
    example_path = os.path.join(_BACKEND_ROOT, "data", "settings.json.example")
    with open(example_path, encoding="utf-8") as f:
        payload = json.load(f)  # 含注释或非法 JSON 会直接抛

    from app.settings.service import CONFIG_GROUPS

    declared_keys = {key for _, fields in CONFIG_GROUPS for key, _, _ in fields}
    actual_keys = {k for k in payload.keys() if not k.startswith("_")}
    assert actual_keys == declared_keys
    assert all(payload[k] == "" for k in actual_keys), "模板值必须留空，禁止携带真实凭证"
