"""tests_pipeline 测试环境自举。

背景：全新克隆（CI、新机器）没有 backend/data/ 与 autopilot.db 等运行时数据，
部分接口测试会因缺表/缺库文件而 500。此 conftest 在会话开始时准备最小数据库，
保证 `pytest tests_pipeline/` 在任何环境一键跑绿。
"""
import importlib
import os
import sqlite3
import warnings
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_test_databases():
    # 1) autopilot.db：automation_configs / automation_logs / platform_status
    from app.automation.db import init_autopilot_db

    init_autopilot_db()

    # 2) data/job_hunter.db：job_strategies 表在代码库中无任何建表语句（历史手工库），
    #    此处提供最小兼容 schema；job_preferences / evaluation_weights 等表
    #    由各 service 内联 CREATE IF NOT EXISTS 自愈，只需库文件存在。
    data_dir = BACKEND_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    conn = sqlite3.connect(data_dir / "job_hunter.db")
    # schema 与生产库完全一致（曾因猜测列名与真实表不符导致本地套件报错）
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS job_strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT NOT NULL DEFAULT 'default',
            is_active INTEGER DEFAULT 0,
            min_salary_k INTEGER,
            max_salary_k INTEGER,
            experience_years_max INTEGER,
            exclude_education TEXT,
            allowed_cities TEXT,
            safe_phrases TEXT,
            keyword_rules TEXT,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            ai_scout_rules TEXT,
            require_education TEXT,
            veto_keywords TEXT DEFAULT '[]',
            positive_keywords TEXT DEFAULT '[]',
            llm_prompt_preference TEXT DEFAULT ''
        );
        INSERT INTO job_strategies (
            strategy_name, is_active, min_salary_k, max_salary_k, experience_years_max,
            exclude_education, allowed_cities, safe_phrases, keyword_rules, ai_scout_rules
        )
        SELECT 'default', 1, 0, 100, 20, '[]', '[]', '[]', '[]', '[]'
        WHERE NOT EXISTS (SELECT 1 FROM job_strategies WHERE is_active = 1);
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture(scope="session", autouse=True)
def _isolate_run_snapshot_db(tmp_path_factory):
    """自动将 run_snapshot 模块的底层数据库重定向到临时测试库，防止测试写入污染生产库 job_hunter.db"""
    from app.automation import run_snapshot as rs
    temp_dir = tmp_path_factory.mktemp("test_run_snapshot")
    temp_db = temp_dir / "test_snapshot.db"
    orig_db = rs._DB_PATH
    rs._DB_PATH = temp_db
    yield
    rs._DB_PATH = orig_db
    # 测试结束后恢复生产库的干净权威状态
    rs._load_from_db()


@pytest.fixture(scope="session", autouse=True)
def _isolate_inflight_registry(tmp_path_factory):
    """把进行中评估登记表重定向到临时文件，防止任何测试写生产 data/inflight_pipelines.json"""
    from app.automation import inflight_registry as reg
    temp = tmp_path_factory.mktemp("test_inflight_registry") / "inflight_pipelines.json"
    reg.reset_for_test(temp)
    yield
    reg.reset_for_test()


@pytest.fixture(scope="session", autouse=True)
def _isolate_resume_edit_stores(tmp_path_factory):
    """把 resume_edit_chat 的会话 store 全部重定向到临时目录。

    事故背景：test_resume_edit_chat 的 fixture 会 clear()+unlink() 这些路径，
    曾把生产的 last_delivered_job.json 清空——用户会话上下文丢失，
    下一条编辑指令误定位到 DeepSeek（品牌词被当公司名信号）。
    """
    from app.services import resume_edit_chat as rec

    d = tmp_path_factory.mktemp("test_resume_edit_stores")
    rec._EDIT_SESSION_PATH = d / "pending_resume_edit.json"
    rec._LAST_DELIVERED_PATH = d / "last_delivered_job.json"
    rec._PENDING_LOCATE_PATH = d / "pending_job_locate.json"
    rec._EDIT_TARGET_PATH = d / "active_edit_target.json"
    rec._PENDING_TARGET_CONFIRM_PATH = d / "pending_edit_target_confirm.json"
    rec._edit_sessions = rec._PendingStore(rec._EDIT_SESSION_PATH, rec._LINK_TTL_SECONDS)
    rec._last_delivered = rec._PendingStore(rec._LAST_DELIVERED_PATH, rec._LINK_TTL_SECONDS * 7)
    rec._pending_locate = rec._PendingStore(rec._PENDING_LOCATE_PATH, rec._LINK_TTL_SECONDS)
    rec._edit_target = rec._PendingStore(rec._EDIT_TARGET_PATH, rec._LINK_TTL_SECONDS)
    rec._pending_target_confirm = rec._PendingStore(rec._PENDING_TARGET_CONFIRM_PATH, rec._LINK_TTL_SECONDS)
    yield


@pytest.fixture(autouse=True)
def _isolate_51job_upload_quota(tmp_path, monkeypatch):
    """51job 日上传配额状态文件按测试隔离：真机撞过 720721 的当天，生产状态文件会让
    编排测试里的 51job 精投被预检跳过而误红；每个用例指向独立临时文件。"""
    from app.automation import upload_quota

    monkeypatch.setattr(upload_quota, "QUOTA_STATE_FILE", str(tmp_path / "51job_upload_quota.json"))
    yield


# ============ 测试密闭化：飞书出站边界全密封（2026-09-20 CI 红战役） ============
#
# 背景：部分管线用例未 mock 飞书触点，本地靠真实凭据"意外通过"（静默打生产 API），
# CI 占位凭据下 502 崩红。本 fixture 在源头与全部 import 期绑定两个层面密封：
#   - get_tenant_access_token() → 固定假 token（跳过真鉴权 HTTP）
#   - safe_feishu_request()     → HTTP 200 + 业务码 0 + 空数据集的假响应
# 单测自行 monkeypatch 同名属性时自然覆盖本密封（monkeypatch 栈后进先出）；
# 真机 E2E 仍走 RUN_LIVE_E2E=1 的既有逃生门（testing_guard 语义不变）。

_SEALED_FEISHU_TOKEN = "sealed-ci-token"

# 导入了两个密封名的全部模块（import 期绑定，patch 源头模块不影响它们）
_FEISHU_BOUNDARY_MODULES = (
    "app.core.feishu_utils",
    "app.services.feishu_service",
    "app.core.feishu_client",
    "app.core.feishu_messaging",
    "app.core.resume_html_builder",
    "app.agent_router",
    "app.main",
    "app.jobs.action_service",
    "app.automation.materials",
    "app.automation.routes.delivery_router",
    "app.pipeline.routes.feishu_status_router",
    "app.services.eval_report",
    "app.services.export_service",
    "app.services.job_service",
    "app.strategy.config_service",
    "app.strategy.jd_report_service",
    "app.strategy.service",
    "app.strategy.routes.ai_router",
    "app.strategy.routes.skill_agent_router",
    "app.strategy.routes.upload_router",
    "ai_agents.ai_evaluator",
    "ai_agents.markdown_to_json",
    "job_processor.step2_sync_feishu",
)


class _SealedFeishuResponse:
    """safe_feishu_request 密封假响应：HTTP 200 / 业务码 0 / 空数据集。

    data 固化为 records-search 形状（items/total/has_more），适配管线流程的
    「密封后放行、数据判空」消费语义；依赖其他端点形状的用例请自行 mock。
    """

    status_code = 200
    headers: dict = {}

    def json(self):
        return {"code": 0, "msg": "success", "data": {"items": [], "total": 0, "has_more": False}}

    def raise_for_status(self):
        return None

    @property
    def text(self):
        return ""


def _sealed_get_tenant_token(*_args, **_kwargs):
    return _SEALED_FEISHU_TOKEN


def _sealed_safe_feishu_request(method, url, **kwargs):
    return _SealedFeishuResponse()


_SEAL_WARNED_MODULES: set = set()


@pytest.fixture(autouse=True)
def _seal_feishu_boundaries(monkeypatch):
    # 真机 E2E 逃生门：RUN_LIVE_E2E=1 时完全放行，绝不让真机用例吃到假响应静默假绿
    if os.environ.get("RUN_LIVE_E2E") == "1":
        yield
        return

    for mod_name in _FEISHU_BOUNDARY_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:
            # 可选依赖缺失属正常跳过；清单写错模块名也会走到这里，必须可区分。
            # 每模块只告警一次，防止 autouse 下逐用例刷屏。
            if mod_name not in _SEAL_WARNED_MODULES:
                _SEAL_WARNED_MODULES.add(mod_name)
                warnings.warn(f"[feishu-seal] 模块 {mod_name} 导入失败，密封未覆盖: {e}")
            continue
        if hasattr(mod, "get_tenant_access_token"):
            monkeypatch.setattr(mod, "get_tenant_access_token", _sealed_get_tenant_token)
        if hasattr(mod, "safe_feishu_request"):
            monkeypatch.setattr(mod, "safe_feishu_request", _sealed_safe_feishu_request)
    yield
