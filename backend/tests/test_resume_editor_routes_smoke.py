"""模块五质检战役·层2 路由级冒烟（44 端点全集防御分支，QA_BASE 0ed2c46）。

原则：
- 不触发子进程、不连接真实平台浏览器（🔴🟠 动作只测参数校验/离线短路分支）
- DATA_DIR/UNIFIED_PATH 全链 monkeypatch 到 tmp_path，生产 resume_editor/data 零接触
- agent-map/resumes、master、generate 正向链路依赖真实飞书/LLM，仅在层4 GUI 授权窗口覆盖
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PLATFORMS = ["boss", "liepin", "51job", "zhilian"]


@pytest.fixture()
def isolated_data_dir(tmp_path, monkeypatch):
    """把模块五全部路由模块 + 平台子系统的 DATA_DIR/UNIFIED_PATH 指向 tmp_path。

    层2 实录教训：platforms 子系统（healer/probe_healer/schema_diff_engine/agent_mapper）
    的路径常量各自独立自算，绕过 common.DATA_DIR——漏 patch 任何一个都会把快照/备份/
    日志写进生产 data（S1 哨兵已在 2026-09-20 冒烟首跑截获一次并恢复）。新增写盘常量
    时必须同步加入本 fixture。
    """
    from app.api.resume_editor import (
        agent_map_routes,
        common,
        editor_routes,
        platforms_routes,
        unified_routes,
    )

    data_dir = str(tmp_path)
    for mod in (common, editor_routes, platforms_routes, unified_routes, agent_map_routes):
        if hasattr(mod, "DATA_DIR"):
            monkeypatch.setattr(mod, "DATA_DIR", data_dir)
    monkeypatch.setattr(common, "UNIFIED_PATH", str(tmp_path / "unified_resume.json"))

    # 平台子系统独立自算的路径常量（模块级，import 时已绑定）
    import resume_editor.agent_mapper as am
    import resume_editor.schema_diff_engine as sde
    import resume_editor.platforms.boss_healer_agent as boss_h
    import resume_editor.platforms.job51_healer_agent as job51_h
    import resume_editor.platforms.liepin_healer_agent as liepin_h
    import resume_editor.platforms.zhilian_healer_agent as zhilian_h
    import resume_editor.platforms.zhilian_probe_healer as zhilian_ph

    monkeypatch.setattr(am, "DATA_DIR", data_dir)
    monkeypatch.setattr(am, "REPORT_FILE", str(tmp_path / "agent_map_reports.json"))
    monkeypatch.setattr(sde, "DATA_DIR", data_dir)
    monkeypatch.setattr(sde, "SNAPSHOTS_DIR", str(tmp_path / "schema_snapshots"))
    monkeypatch.setattr(boss_h, "BOSS_WRITEBACK_FILE", str(tmp_path / "boss_writeback.json"))
    monkeypatch.setattr(boss_h, "BOSS_SNAPSHOTS_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setattr(job51_h, "JOB51_WRITEBACK_FILE", str(tmp_path / "51job_writeback.json"))
    monkeypatch.setattr(job51_h, "JOB51_SNAPSHOTS_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setattr(liepin_h, "LIEPIN_WRITEBACK_FILE", str(tmp_path / "liepin_writeback.json"))
    monkeypatch.setattr(liepin_h, "LIEPIN_SNAPSHOTS_DIR", str(tmp_path / "snapshots"))
    # zhilian_healer_agent 以 from-import 绑定 probe_healer 的常量（真实名无 ZHILIAN_ 前缀，R3-P1 修正）
    monkeypatch.setattr(zhilian_h, "WRITEBACK_FILE", str(tmp_path / "zhilian_writeback.json"))
    monkeypatch.setattr(zhilian_h, "FIELDS_FILE", str(tmp_path / "zhilian_fields.json"))
    monkeypatch.setattr(zhilian_ph, "DATA_DIR", data_dir)
    monkeypatch.setattr(zhilian_ph, "SNAPSHOTS_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setattr(zhilian_ph, "WRITEBACK_FILE", str(tmp_path / "zhilian_writeback.json"))
    return tmp_path


# ---------------------------------------------------------------
# editor_routes（9 端点）
# ---------------------------------------------------------------

def test_e01_get_all(isolated_data_dir):
    res = client.get("/api/resume-editor/all")
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_e02_get_platform_missing_returns_404(isolated_data_dir):
    res = client.get("/api/resume-editor/boss")
    assert res.status_code == 404
    assert res.json()["success"] is False


def test_e03_save_then_get_roundtrip(isolated_data_dir):
    payload = {"name": {"current_value": "张*"}}
    res = client.post("/api/resume-editor/save/boss", json=payload)
    assert res.status_code == 200
    assert res.json()["success"] is True
    res = client.get("/api/resume-editor/boss")
    assert res.status_code == 200
    assert res.json()["data"] == payload


def test_e04_options_platform_missing_404(isolated_data_dir):
    res = client.get("/api/resume-editor/options/boss")
    assert res.status_code == 404


def test_e05_options_field_unknown_404(isolated_data_dir):
    res = client.get("/api/resume-editor/options/boss/nonexistent_field")
    assert res.status_code == 404


def test_e06_options_platform_unknown_404(isolated_data_dir):
    res = client.get("/api/resume-editor/options/notaplatform/job_titles")
    assert res.status_code == 404


def test_e07_zhilian_language_certificates_missing_404(isolated_data_dir):
    res = client.get("/api/resume-editor/zhilian/language-certificates/1")
    assert res.status_code == 404


def test_e08_zhilian_work_skills_empty_is_ok(isolated_data_dir):
    res = client.get("/api/resume-editor/zhilian/work-skills/nonexistent_id")
    assert res.status_code == 200
    assert res.json() == {"success": True, "data": []}


def test_e09_total_roundtrip(isolated_data_dir):
    res = client.get("/api/resume-editor/total")
    assert res.status_code == 200
    assert res.json() == {"success": True, "data": {}}
    res = client.post("/api/resume-editor/total/save", json={"k": "v"})
    assert res.status_code == 200
    assert client.get("/api/resume-editor/total").json()["data"] == {"k": "v"}


# ---------------------------------------------------------------
# platforms_routes（25 端点：状态/清空/launch/goto 防御分支 + 自愈快照 + 差分）
# ---------------------------------------------------------------

def test_p01_status_shape(isolated_data_dir):
    res = client.get("/api/platforms/status")
    assert res.status_code == 200
    platforms = res.json()["platforms"]
    assert set(platforms.keys()) == set(PLATFORMS)
    for info in platforms.values():
        assert set(info.keys()) >= {"port", "online", "logged_in", "message"}


def test_p02_clear_data_explicit_list(isolated_data_dir):
    fields = isolated_data_dir / "boss_fields.json"
    fields.write_text(json.dumps({"name": {"current_value": "x"}}), encoding="utf-8")
    res = client.post("/api/platforms/clear-data", json={"platforms": ["boss"]})
    assert res.status_code == 200
    assert res.json()["cleared"] == ["boss"]
    assert json.loads(fields.read_text(encoding="utf-8")) == {}


def test_p03_clear_data_explicit_empty_is_noop(isolated_data_dir):
    """显式空列表 = 无操作（防 falsy 误判全量清空，platforms_routes.py:89-94）。"""
    fields = isolated_data_dir / "boss_fields.json"
    fields.write_text(json.dumps({"keep": 1}), encoding="utf-8")
    res = client.post("/api/platforms/clear-data", json={"platforms": []})
    assert res.status_code == 200
    assert res.json()["cleared"] == []
    assert json.loads(fields.read_text(encoding="utf-8")) == {"keep": 1}


def test_p04_clear_data_unknown_platform_filtered(isolated_data_dir):
    res = client.post("/api/platforms/clear-data", json={"platforms": ["notaplatform"]})
    assert res.status_code == 200
    assert res.json()["cleared"] == []


def test_p05_launch_unknown_platform_400():
    res = client.post("/api/platforms/launch", json={"platform": "notaplatform"})
    assert res.status_code == 400


def test_p06_goto_login_unknown_platform_400():
    res = client.post("/api/platforms/goto-login", json={"platform": "notaplatform"})
    assert res.status_code == 400


@pytest.mark.parametrize("platform", PLATFORMS)
def test_p07_snapshots_list(isolated_data_dir, platform):
    res = client.get(f"/api/platforms/{platform}/snapshots")
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert isinstance(res.json()["snapshots"], list)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_p08_rollback_snapshot(isolated_data_dir, platform, monkeypatch):
    """回滚矩阵冒烟（🔴 前置门槛）：4 平台 rollback 端点管道可达且结构化响应。

    层2 实录：boss/job51/liepin 的 SnapshotManager 默认参数曾类定义时绑定生产路径
    （Q-M5-2，晨间批次已改运行时读取）。本用例以 stub 替换 SnapshotManager 只验证
    路由管道；真实快照/回滚生命周期由 tests/resume_editor_guard/test_zhilian_snapshot_lifecycle.py
    （承接重建）+ 层4 GUI 授权窗口覆盖，承接映射见矩阵 §九。
    """
    import resume_editor.platforms.boss_healer_agent as boss_h
    import resume_editor.platforms.job51_healer_agent as job51_h
    import resume_editor.platforms.liepin_healer_agent as liepin_h
    import resume_editor.platforms.zhilian_probe_healer as zhilian_ph

    class _StubMgr:
        def __init__(self, *a, **k):
            pass

        def rollback(self, snapshot_id=None):
            return False, "smoke-stub：无快照可回滚（隔离 stub）"

        def list_snapshots(self):
            return []

    stubs = {
        "boss": (boss_h, "BossSnapshotManager"),
        "51job": (job51_h, "Job51SnapshotManager"),
        "liepin": (liepin_h, "LiepinSnapshotManager"),
        "zhilian": (zhilian_ph, "SnapshotManager"),
    }
    mod, cls = stubs[platform]
    monkeypatch.setattr(mod, cls, _StubMgr)

    res = client.post(f"/api/platforms/{platform}/rollback-snapshot", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert body["message"]


def test_p09_schema_diff_missing_fields_file(isolated_data_dir):
    res = client.post("/api/platforms/boss/schema-diff", json={})
    assert res.status_code == 200
    assert res.json()["success"] is False


def test_p10_apply_schema_patch_roundtrip(isolated_data_dir):
    fields = isolated_data_dir / "boss_fields.json"
    fields.write_text(json.dumps({"name": {"current_value": "旧"}}), encoding="utf-8")
    res = client.post(
        "/api/platforms/boss/apply-schema-patch",
        json={"diff_result": {"added_fields": [{"module": "basic", "field": "new_col", "type": "text"}]}},
    )
    assert res.status_code == 200


def test_p11_apply_schema_patch_unknown_platform_400():
    res = client.post(
        "/api/platforms/notaplatform/apply-schema-patch",
        json={"diff_result": {}},
    )
    assert res.status_code == 400


def test_p12_zhilian_self_heal_empty_diffs(isolated_data_dir):
    res = client.post("/api/platforms/zhilian/self-heal", json={"selected_diffs": []})
    assert res.status_code == 200


def test_p13_agent_diagnose_empty_module(isolated_data_dir):
    """空 target_module：agent 内部应返回结构化失败而非 500 崩溃（参数防御）。"""
    res = client.post("/api/platforms/zhilian/agent-diagnose", json={"target_module": "", "error_context": {}})
    assert res.status_code == 200


# ---------------------------------------------------------------
# unified_routes（2 端点）
# ---------------------------------------------------------------

def test_u01_collect_empty_platforms_400():
    res = client.post("/api/unified/collect", json={"platforms": []})
    assert res.status_code == 400


def test_u02_collect_unknown_platform_skipped():
    res = client.post("/api/unified/collect", json={"platforms": ["notaplatform"]})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is False
    assert body["results"][0]["message"] == "不支持的平台"


def test_u03_sync_back_empty_platforms_400():
    res = client.post("/api/unified/sync-back", json={"platforms": []})
    assert res.status_code == 400


# ---------------------------------------------------------------
# agent_map_routes（8 端点；resumes/master/generate 正向依赖真实飞书，层4 覆盖）
# ---------------------------------------------------------------

def test_a01_generate_unknown_platform_400():
    res = client.post("/api/agent-map/generate", json={"platforms": ["notaplatform"]})
    assert res.status_code == 400


def test_a02_generate_missing_fields_data(isolated_data_dir):
    res = client.post("/api/agent-map/generate", json={"platforms": ["boss"]})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is False  # 平台 fields 缺失：顶层聚合响亮失败
    assert body["reports"]["boss"]["success"] is False
    assert "请先采集" in body["reports"]["boss"]["message"]


def test_a03_reports_empty(isolated_data_dir):
    res = client.get("/api/agent-map/reports")
    assert res.status_code == 200
    assert res.json()["success"] is True


def test_a04_apply_unknown_platform_400():
    res = client.post("/api/agent-map/apply", json={"platform": "notaplatform", "entries": [{"path": "a", "value": "b"}]})
    assert res.status_code == 400


def test_a05_apply_empty_entries_400():
    res = client.post("/api/agent-map/apply", json={"platform": "boss", "entries": []})
    assert res.status_code == 400


def test_a06_apply_missing_fields_404(isolated_data_dir):
    res = client.post("/api/agent-map/apply", json={"platform": "boss", "entries": [{"path": "a", "value": "b"}]})
    assert res.status_code == 404


def test_a07_save_edits_no_report_404(isolated_data_dir):
    res = client.post("/api/agent-map/save-edits", json={"platform": "boss", "entries": [{"path": "a", "value": "b"}]})
    assert res.status_code == 404


def test_a08_writeback_save_missing_fields_404(isolated_data_dir):
    res = client.post("/api/agent-map/writeback-save", json={"platform": "boss"})
    assert res.status_code == 404


def test_a09_writeback_save_rich_data_rejected_when_empty(isolated_data_dir):
    """空数据拒绝（质检 C5）：非空模块 <3 拒绝保存为回写源。"""
    fields = isolated_data_dir / "boss_fields.json"
    fields.write_text(json.dumps({"name": {"current_value": "x"}}), encoding="utf-8")
    res = client.post("/api/agent-map/writeback-save", json={"platform": "boss"})
    assert res.status_code == 400


def test_a10_write_back_unknown_platform_400():
    res = client.post("/api/agent-map/write-back", json={"platform": "notaplatform"})
    assert res.status_code == 400


def test_a11_write_back_liepin_browser_precheck_rejected(isolated_data_dir):
    res = client.post("/api/agent-map/write-back", json={"platform": "liepin"})
    assert res.status_code == 400  # 预检拦截优先（浏览器未启动）或脚本缺失 500，两者皆为响亮失败
    assert res.json().get("success") is False
