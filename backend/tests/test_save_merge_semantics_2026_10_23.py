"""保存接口模块级增量合并回归锁（2026-10-23 改造，plan-review R2 PASS 方案）。

背景：POST /api/resume-editor/save/{platform} 原为全量覆盖写——任何局部载荷都会把
未提及的模块整份销毁（实害：测试桩曾把 17 模块的 boss_fields.json 覆盖成 1 模块，
用户真实数据靠快照才恢复）。改造后语义：
- 请求体的顶层键整体替换同名模块，未提及模块原样保留；
- 值为 null 删除该模块（显式协议；整表清空仍走 /clear-data）；
- 现有文件损坏（解析失败/顶层非 dict）一律 fail-closed 500，绝不降级当空文件合并；
- 非 dict 入参 400；写入前快照备份，响应 backup 字段带路径。
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.main import app
from app.api.resume_editor.common import merge_platform_fields

client = TestClient(app)


@pytest.fixture
def sandbox_data_dir(tmp_path, monkeypatch):
    """数据目录沙箱：真实 resume_editor/data 绝不被触碰。"""
    from app.api.resume_editor import agent_map_routes, common, editor_routes
    for mod in (editor_routes, agent_map_routes, common):
        monkeypatch.setattr(mod, "DATA_DIR", str(tmp_path))
    return tmp_path


# ─────────────────────────────────────────────────────────────
# 1. 纯函数 merge_platform_fields
# ─────────────────────────────────────────────────────────────
def test_merge_replaces_mentioned_and_keeps_rest():
    existing = {"a": {"v": 1}, "b": {"v": 2}, "c": {"v": 3}}
    merged = merge_platform_fields(existing, {"a": {"v": 9}})
    assert merged == {"a": {"v": 9}, "b": {"v": 2}, "c": {"v": 3}}


def test_merge_none_deletes_module():
    existing = {"a": {"v": 1}, "b": {"v": 2}}
    merged = merge_platform_fields(existing, {"a": None})
    assert merged == {"b": {"v": 2}}
    # 删除不存在的模块不报错
    assert merge_platform_fields({"a": {}}, {"ghost": None}) == {"a": {}}


def test_merge_first_save_with_no_existing_file():
    assert merge_platform_fields(None, {"a": {"v": 1}}) == {"a": {"v": 1}}


def test_merge_empty_incoming_is_noop():
    existing = {"a": {"v": 1}}
    assert merge_platform_fields(existing, {}) == existing


def test_merge_rejects_non_dict_inputs():
    with pytest.raises(ValueError):
        merge_platform_fields({"a": {}}, ["not", "a", "dict"])  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        merge_platform_fields(["corrupt"], {"a": {}})  # type: ignore[arg-type]


def test_merge_does_not_mutate_inputs():
    existing = {"a": {"v": 1}}
    incoming = {"b": {"v": 2}}
    merge_platform_fields(existing, incoming)
    assert existing == {"a": {"v": 1}} and incoming == {"b": {"v": 2}}


# ─────────────────────────────────────────────────────────────
# 2. 端点级（沙箱）
# ─────────────────────────────────────────────────────────────
def _rich_seed(sandbox) -> dict:
    """17 模块富数据（对齐事故现场 boss_fields.json 的规模）。"""
    seed = {f"module_{i}": {"label": f"模块{i}", "current_value": f"值{i}"} for i in range(17)}
    path = sandbox / "boss_fields.json"
    path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    return seed


def test_partial_save_preserves_untouched_modules(sandbox_data_dir):
    """事故场景复现：17 模块文件 + 1 模块局部载荷 → 必须仍 17 模块（旧覆盖写会变 1）。"""
    seed = _rich_seed(sandbox_data_dir)
    res = client.post("/api/resume-editor/save/boss", json={"module_0": {"label": "模块0", "current_value": "新值"}})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["modules"] == 17
    saved = json.loads((sandbox_data_dir / "boss_fields.json").read_text(encoding="utf-8"))
    assert saved["module_0"]["current_value"] == "新值"
    for i in range(1, 17):
        assert saved[f"module_{i}"] == seed[f"module_{i}"], f"module_{i} 被局部载荷销毁"


def test_full_document_save_still_replaces_all(sandbox_data_dir):
    """兼容性：载荷携带全部模块时 merge == 旧覆盖写，结果与载荷完全一致；
    未提及=保留（省略不再表达删除，删除必须显式 null）。"""
    seed = {"a": {"v": "旧a"}, "b": {"v": "旧b"}}
    (sandbox_data_dir / "boss_fields.json").write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    full_doc = {"a": {"v": "新a"}, "b": {"v": "新b"}}
    res = client.post("/api/resume-editor/save/boss", json=full_doc)
    assert res.status_code == 200
    saved = json.loads((sandbox_data_dir / "boss_fields.json").read_text(encoding="utf-8"))
    assert saved == full_doc


def test_null_deletes_module_via_endpoint(sandbox_data_dir):
    _rich_seed(sandbox_data_dir)
    res = client.post("/api/resume-editor/save/boss", json={"module_3": None, "module_4": {"v": "x"}})
    assert res.status_code == 200
    saved = json.loads((sandbox_data_dir / "boss_fields.json").read_text(encoding="utf-8"))
    assert "module_3" not in saved
    assert saved["module_4"] == {"v": "x"}
    assert len(saved) == 16


def test_corrupted_existing_file_fails_closed(sandbox_data_dir):
    """损坏文件（非法 JSON）fail-closed 500，绝不降级当空文件合并（plan-review P1）。"""
    (sandbox_data_dir / "boss_fields.json").write_text("{corrupted!!!", encoding="utf-8")
    res = client.post("/api/resume-editor/save/boss", json={"module_0": {"v": 1}})
    assert res.status_code == 500
    assert "拒绝合并" in str(res.json().get("detail", ""))
    # 原文件原样保留，未被二次破坏
    assert (sandbox_data_dir / "boss_fields.json").read_text(encoding="utf-8") == "{corrupted!!!"


def test_non_dict_existing_file_fails_closed(sandbox_data_dir):
    """合法 JSON 但顶层非 dict（如数组）同样 fail-closed——「兜底 {}」会击穿防线。"""
    (sandbox_data_dir / "boss_fields.json").write_text("[1, 2, 3]", encoding="utf-8")
    res = client.post("/api/resume-editor/save/boss", json={"module_0": {"v": 1}})
    assert res.status_code == 500
    assert json.loads((sandbox_data_dir / "boss_fields.json").read_text(encoding="utf-8")) == [1, 2, 3]


def test_save_creates_backup_and_returns_path(sandbox_data_dir):
    """写入前快照备份：备份文件真实生成，响应 backup 字段带绝对路径（plan-review P2）。"""
    _rich_seed(sandbox_data_dir)
    res = client.post("/api/resume-editor/save/boss", json={"module_0": {"v": "changed"}})
    assert res.status_code == 200
    backup = res.json().get("backup")
    assert backup, "响应必须携带备份路径"
    assert "boss_save_" in str(backup) and str(backup).endswith(".bak.json")
    backup_file = Path(backup)
    assert backup_file.exists()
    # 备份内容 = 覆盖前的旧数据
    assert json.loads(backup_file.read_text(encoding="utf-8"))["module_0"]["current_value"] == "值0"


def test_empty_payload_is_true_noop_without_disk_io(sandbox_data_dir):
    """空载荷（前端零差异）真 no-op：成功返回但不产生备份、不写文件（code-review P2）。"""
    import os
    seed = _rich_seed(sandbox_data_dir)
    f = sandbox_data_dir / "boss_fields.json"
    before_mtime = os.path.getmtime(f)
    before_snapshots = list((sandbox_data_dir / "snapshots").glob("*.bak.json")) if (sandbox_data_dir / "snapshots").exists() else []
    res = client.post("/api/resume-editor/save/boss", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True and body["backup"] is None and body["modules"] == 17
    assert "未执行写入" in body["message"]
    assert os.path.getmtime(f) == before_mtime, "no-op 不得推高文件 mtime"
    after_snapshots = list((sandbox_data_dir / "snapshots").glob("*.bak.json")) if (sandbox_data_dir / "snapshots").exists() else []
    assert len(after_snapshots) == len(before_snapshots), "no-op 不得产生备份快照"
    assert json.loads(f.read_text(encoding="utf-8")) == seed


def test_first_save_without_existing_file_has_no_backup(sandbox_data_dir):
    """首存（文件不存在）无旧数据可备：backup=None，message 如实提示。"""
    res = client.post("/api/resume-editor/save/boss", json={"a": {"v": 1}})
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True and body["backup"] is None
    assert "未生成备份" in body["message"]
